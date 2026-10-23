import threading
import time
import unittest

import numpy as np

from audio_chunker import AudioChunker
from avatar_engine import StreamingAvatarEngine
from gpu_server import Session

FRAMES = 33
MOTION = 5


def fake_model(_emb):
    return np.zeros((FRAMES, 4, 4, 3), dtype=np.uint8)


def make_session(model_type="pro"):
    chunker = AudioChunker(model_type)
    engine = StreamingAvatarEngine(chunker, lambda w: w, fake_model, motion_frames_num=MOTION)
    s = Session(engine, chunker)
    t = threading.Thread(target=s.render_loop, daemon=True)
    t.start()
    return s


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


class SessionTest(unittest.TestCase):
    def setUp(self):
        self.s = make_session("pro")

    def tearDown(self):
        self.s.running = False

    def test_no_idle_filler_without_speech(self):
        # idle filler is off (Pro renders it slower than real time); the client shows its own idle clip
        time.sleep(0.3)
        self.assertEqual(self.s.buffer.buffered_frames, 0)

    def test_speech_renders_in_order_and_is_paced_by_chunks(self):
        self.s.start(prebuffer_s=0.0)
        c = self.s.chunker.chunk_samples
        self.s.push_speech(np.ones(c, dtype=np.float32) * 0.25)
        self.assertTrue(wait_for(lambda: self.s.buffer.buffered_frames >= 28))
        frame, audio = self.s.pop_frame()
        self.assertEqual(audio.size, 640)
        self.assertAlmostEqual(float(audio[0]), 0.25)

    def test_partial_speech_waits_until_end_pads_it(self):
        self.s.start(prebuffer_s=0.0)
        self.s.flush()
        c = self.s.chunker.chunk_samples
        self.s.push_speech(np.ones(c // 2, dtype=np.float32))
        time.sleep(0.2)
        self.assertEqual(self.s.chunker.queued_samples, c // 2)  # not rendered yet
        self.s.end_speech()
        self.assertTrue(wait_for(lambda: self.s.buffer.buffered_frames >= 28))

    def test_prebuffer_gates_playback(self):
        self.s.start(prebuffer_s=2.0)  # 50 frames
        c = self.s.chunker.chunk_samples
        self.s.push_speech(np.ones(c, dtype=np.float32))  # one chunk = 28 frames < 50
        self.assertTrue(wait_for(lambda: self.s.buffer.buffered_frames >= 28))
        self.assertIsNone(self.s.pop_frame())
        self.assertFalse(self.s.buffer.started)

    def test_no_idle_render_while_speaking(self):
        # a half-chunk of speech is pending; idle filler must not be rendered (it would block the speech render)
        self.s.start(prebuffer_s=0.0)
        c = self.s.chunker.chunk_samples
        calls = []
        orig = self.s.engine.render_chunk

        def spy(chunk, speech):
            calls.append(speech)
            return orig(chunk, speech)

        self.s.engine.render_chunk = spy
        self.s.push_speech(np.ones(c // 2, dtype=np.float32))
        time.sleep(0.3)
        self.assertEqual(calls, [])
        self.s.end_speech()
        self.assertTrue(wait_for(lambda: self.s.buffer.buffered_frames >= 28))
        self.assertIn(True, calls)  # the padded final chunk was rendered as speech

    def test_flush_drops_pending_speech(self):
        self.s.start(prebuffer_s=0.0)
        c = self.s.chunker.chunk_samples
        self.s.push_speech(np.ones(c * 4, dtype=np.float32))
        self.s.flush()
        self.assertEqual(self.s.chunker.queued_samples, 0)


class LiveIdleSessionTest(unittest.TestCase):
    """AVATAR_IDLE_TARGET_S > 0 (H200): idle motion is rendered live, so frames never stop."""

    def setUp(self):
        import gpu_server

        self.gpu_server = gpu_server
        self.saved = gpu_server.IDLE_TARGET_S
        gpu_server.IDLE_TARGET_S = 0.5
        self.s = make_session("pro")

    def tearDown(self):
        self.s.running = False
        self.gpu_server.IDLE_TARGET_S = self.saved

    def test_no_idle_before_start(self):
        time.sleep(0.3)
        self.assertEqual(self.s.buffer.buffered_frames, 0)

    def test_idle_flows_after_start_and_stays_near_target(self):
        self.s.start(prebuffer_s=0.3)
        self.assertTrue(wait_for(lambda: self.s.buffer.buffered_frames >= 28))
        frame, audio = self.s.pop_frame()  # idle opens the gate: no speech needed
        self.assertEqual(float(np.abs(audio).max()), 0.0)
        time.sleep(0.2)
        self.assertLessEqual(self.s.buffer.buffered_seconds, 0.5 + 28 / 25)  # one chunk past the target at most

    def test_speech_follows_idle_without_a_gap(self):
        self.s.start(prebuffer_s=0.3)
        self.assertTrue(wait_for(lambda: self.s.buffer.buffered_frames >= 28))
        c = self.s.chunker.chunk_samples
        self.s.push_speech(np.ones(c, dtype=np.float32) * 0.25)
        self.assertTrue(wait_for(lambda: self.s.buffer._speech_buffered >= 28))
        levels = []
        while True:
            item = self.s.pop_frame()
            self.assertIsNotNone(item)  # no gap while idle hands over to speech
            levels.append(float(audio_level(item[1])))
            if levels[-1] > 0:
                break
        self.assertTrue(all(v == 0.0 for v in levels[:-1]))  # queued idle played first, then speech


class BargeInFlushTest(unittest.TestCase):
    """flush() is the barge-in: the avatar must stop, not finish the interrupted reply."""

    def setUp(self):
        self.render_started = threading.Event()
        self.resets = []

        def slow_model(_emb):
            self.render_started.set()
            time.sleep(0.3)  # a render in flight when the barge-in lands
            return np.zeros((FRAMES, 4, 4, 3), dtype=np.uint8)

        chunker = AudioChunker("pro")
        engine = StreamingAvatarEngine(chunker, lambda w: w, slow_model, motion_frames_num=MOTION)
        self.s = Session(engine, chunker, reset_model=lambda: self.resets.append(time.time()))
        threading.Thread(target=self.s.render_loop, daemon=True).start()
        self.s.start(prebuffer_s=0.0)
        self.assertTrue(wait_for(lambda: len(self.resets) == 1))  # the start reset

    def tearDown(self):
        self.s.running = False

    def test_chunk_rendering_at_flush_is_discarded(self):
        c = self.s.chunker.chunk_samples
        self.render_started.clear()
        self.s.push_speech(np.ones(c * 3, dtype=np.float32) * 0.25)  # a 3-chunk reply
        self.assertTrue(self.render_started.wait(2.0))
        self.s.flush()  # mid-render of chunk 1
        time.sleep(0.8)
        self.assertEqual(self.s.buffer._speech_buffered, 0)  # no frames of the interrupted reply
        self.assertEqual(self.s.chunker.queued_samples, 0)

    def test_flush_resets_motion_and_audio_to_silence(self):
        c = self.s.chunker.chunk_samples
        self.s.push_speech(np.ones(c, dtype=np.float32) * 0.25)
        self.assertTrue(wait_for(lambda: self.s.buffer._speech_buffered >= 28))
        self.assertGreater(max(self.s.engine.audio_dq), 0.0)  # speech is in the audio context
        self.s.flush()
        self.assertTrue(wait_for(lambda: len(self.resets) == 2))  # motion back to the reference image
        self.assertEqual(max(self.s.engine.audio_dq), 0.0)  # next video is conditioned on silence


    def test_chunk_rendering_across_a_new_call_is_discarded(self):
        # e.g. the forwarder reconnects mid-reply and sends "start" while a speech chunk renders
        c = self.s.chunker.chunk_samples
        self.render_started.clear()
        self.s.push_speech(np.ones(c, dtype=np.float32) * 0.25)
        self.assertTrue(self.render_started.wait(2.0))
        self.s.start(prebuffer_s=0.0)  # the next call
        time.sleep(0.8)
        self.assertEqual(self.s.buffer._speech_buffered, 0)  # the old call's speech never reaches it


def audio_level(audio):
    return np.abs(audio).max()


if __name__ == "__main__":
    unittest.main()
