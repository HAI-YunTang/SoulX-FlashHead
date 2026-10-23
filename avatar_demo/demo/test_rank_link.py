"""Multi-GPU plumbing: rank 0's Session mirrors renders/resets to followers, in order."""

import os
import socket
import tempfile
import threading
import time
import unittest

import numpy as np
import torch.multiprocessing as mp

from audio_chunker import AudioChunker
from avatar_engine import StreamingAvatarEngine
from gpu_server import RankLink, Session, follower_loop

FRAMES = 33
MOTION = 5


def fake_model(_emb):
    return np.zeros((FRAMES, 4, 4, 3), dtype=np.uint8)


class RecordingLink:
    def __init__(self):
        self.sent = []

    def send(self, cmd, chunk=None, speech=False):
        self.sent.append((cmd, None if chunk is None else float(chunk[0]), speech))


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


class SessionMirrorTest(unittest.TestCase):
    def setUp(self):
        self.chunker = AudioChunker("pro")
        self.engine = StreamingAvatarEngine(self.chunker, lambda w: w, fake_model, motion_frames_num=MOTION)
        self.link = RecordingLink()
        self.resets = []
        self.s = Session(self.engine, self.chunker, link=self.link, reset_model=lambda: self.resets.append(1))
        threading.Thread(target=self.s.render_loop, daemon=True).start()

    def tearDown(self):
        self.s.running = False

    def test_start_resets_every_rank_before_rendering(self):
        self.s.start(prebuffer_s=0.0)
        c = self.chunker.chunk_samples
        self.s.push_speech(np.ones(c, dtype=np.float32) * 0.5)
        self.assertTrue(wait_for(lambda: self.s.buffer.buffered_frames >= 28))
        self.assertEqual(self.link.sent[0], (RankLink.RESET, None, False))
        self.assertEqual(self.link.sent[1], (RankLink.RENDER, 0.5, True))
        self.assertEqual(self.resets, [1])

    def test_reset_clears_audio_context(self):
        self.s.start(prebuffer_s=0.0)
        c = self.chunker.chunk_samples
        self.s.push_speech(np.ones(c, dtype=np.float32))
        self.assertTrue(wait_for(lambda: self.engine.chunk_idx == 1))
        self.s.start(prebuffer_s=0.0)  # a new conversation
        self.assertTrue(wait_for(lambda: len(self.resets) == 2))
        self.assertEqual(self.engine.chunk_idx, 0)
        self.assertEqual(max(self.engine.audio_dq), 0.0)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _rank_main(rank, port, out_dir):
    import torch.distributed as dist

    os.environ.update(MASTER_ADDR="127.0.0.1", MASTER_PORT=str(port))
    dist.init_process_group("gloo", rank=rank, world_size=2)
    chunker = AudioChunker("pro")
    seen = []

    def model(window):
        seen.append(float(window[-1]))
        return np.zeros((FRAMES, 2, 2, 3), dtype=np.uint8)

    engine = StreamingAvatarEngine(chunker, lambda w: w, model, motion_frames_num=MOTION)
    link = RankLink(chunker.chunk_samples)
    c = chunker.chunk_samples
    if rank == 0:
        link.send(RankLink.RENDER, np.full(c, 0.25, np.float32), True)
        link.send(RankLink.RESET)
        link.send(RankLink.RENDER, np.full(c, 0.75, np.float32), True)
        link.send(RankLink.STOP)
    else:
        resets = []
        follower_loop(engine, link, lambda: resets.append(1))
        seen.append(("resets", len(resets), engine.chunk_idx))
    with open(os.path.join(out_dir, f"rank{rank}.txt"), "w") as f:
        f.write(repr(seen))
    dist.destroy_process_group()


class GlooLinkTest(unittest.TestCase):
    def test_follower_mirrors_renders_and_resets(self):
        with tempfile.TemporaryDirectory() as d:
            mp.spawn(_rank_main, args=(_free_port(), d), nprocs=2, join=True)
            with open(os.path.join(d, "rank1.txt")) as f:
                seen = eval(f.read())
        self.assertEqual(seen, [0.25, 0.75, ("resets", 1, 1)])


if __name__ == "__main__":
    unittest.main()
