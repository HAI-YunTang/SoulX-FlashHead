"""GPU server: FlashHead streaming over a WebSocket (TCP), on one GPU or several.

Runs on the RTX pod. The dev box connects through an SSH tunnel, sends TTS speech as
16 kHz PCM, and receives one JPEG frame plus its 640 audio samples per 1/25 s tick.
See wire.py for the message format.

Multi-GPU (sequence parallel, e.g. Pro on 2 GPUs): start with torchrun. Every rank holds the
model and renders the same chunk in lockstep; only rank 0 serves the WebSocket and keeps the
frames. Rank 0 tells the other ranks what to render over a gloo (CPU) group, so idle gaps
between replies never trip NCCL's watchdog.

Run from the repo root on the pod:
  # 1 GPU
  python avatar_demo/demo/gpu_server.py --model_type pro   # cond image defaults to avatar_demo/figures/
  # 2 GPUs
  torchrun --nproc_per_node=2 avatar_demo/demo/gpu_server.py --model_type pro
(avatar_demo/demo/start_gpu_server.sh picks between them.)
Add --fake to run the protocol without the model (for transport tests).
"""

import argparse
import asyncio
import json
import os
import sys
import threading
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

from audio_chunker import AudioChunker  # noqa: E402
from avatar_engine import StreamingAvatarEngine  # noqa: E402
from listening import NodScheduler, NodWarp  # noqa: E402
from playback_buffer import PlaybackBuffer, VIDEO_FPS  # noqa: E402
from wire import float_to_pcm16, pack_frame, pcm16_to_float  # noqa: E402

# Live idle filler: between replies, render idle motion from silence so the stream never stops,
# keeping about this many seconds buffered. Needs a GPU faster than real time: on for the H200
# (1.45x, AVATAR_IDLE_TARGET_S=1.0), off (0) for 2x RTX Pro 6000 (about 1.0x), where the client
# shows its pre-rendered idle clip between replies instead.
IDLE_TARGET_S = float(os.environ.get("AVATAR_IDLE_TARGET_S", "0"))
# Must exceed one chunk's render time (0.77 s on the H200), or the buffer runs dry while the next
# idle chunk renders. When a reply starts, only this much queued idle is kept ahead of it:
IDLE_KEEP_S = float(os.environ.get("AVATAR_IDLE_KEEP_S", "0.25"))
# Active listening: nod while the patient talks a lot (listening.py). Driven by the client's
# "listen" / "pause" / "agent_speaking" messages (snow's forwarder); off unless AVATAR_LISTEN_NODS=1.
LISTEN_NODS = os.environ.get("AVATAR_LISTEN_NODS", "0") == "1"
NOD_PX = float(os.environ.get("AVATAR_NOD_PX", "5"))
NOD_AFTER_S = float(os.environ.get("AVATAR_NOD_AFTER_S", "5"))
NOD_INTERVAL_S = tuple(float(v) for v in os.environ.get("AVATAR_NOD_INTERVAL_S", "5,8").split(","))
SPEECH_PEAK = 300 / 32768  # a frame whose audio peaks above this carries the nurse's speech: never nod it
DEBUG = bool(os.environ.get("GPU_SERVER_DEBUG"))
# 85 was about 6 Mbit/s over the SSH proxy and Tailscale; 70 is about 4 (see runbook).
JPEG_QUALITY = int(os.environ.get("AVATAR_JPEG_QUALITY", "70"))


class RankLink:
    """Rank 0 -> other ranks: which chunk to render next, or reset/stop. Uses a gloo group on CPU."""

    RENDER, RESET, STOP = 0, 1, 2

    def __init__(self, chunk_samples: int):
        from datetime import timedelta

        import torch
        import torch.distributed as dist

        self.torch = torch
        self.dist = dist
        # A long timeout: the follower ranks wait here for as long as nobody is talking.
        self.group = dist.new_group(backend="gloo", timeout=timedelta(days=7))
        self.header = torch.zeros(2, dtype=torch.int64)
        self.chunk = torch.zeros(chunk_samples, dtype=torch.float32)

    def send(self, cmd: int, chunk: np.ndarray = None, speech: bool = False) -> None:
        self.header[0], self.header[1] = cmd, int(speech)
        self.dist.broadcast(self.header, src=0, group=self.group)
        if cmd == self.RENDER:
            self.chunk.copy_(self.torch.from_numpy(np.ascontiguousarray(chunk, dtype=np.float32)))
            self.dist.broadcast(self.chunk, src=0, group=self.group)

    def recv(self):
        self.dist.broadcast(self.header, src=0, group=self.group)
        cmd, speech = int(self.header[0]), bool(self.header[1])
        chunk = None
        if cmd == self.RENDER:
            self.dist.broadcast(self.chunk, src=0, group=self.group)
            chunk = self.chunk.numpy().copy()
        return cmd, chunk, speech


def new_buffer(prebuffer_s: float = 0.0) -> PlaybackBuffer:
    return PlaybackBuffer(prebuffer_seconds=prebuffer_s, continuous=IDLE_TARGET_S > 0, idle_keep_seconds=IDLE_KEEP_S)


class Session:
    """One conversation. The demo has one patient, so the server runs one session at a time.

    link / reset_model are only set for real models: link mirrors every render and reset to the
    follower ranks; reset_model clears the pipeline's motion state for a new conversation.
    """

    def __init__(self, engine: StreamingAvatarEngine, chunker: AudioChunker,
                 link: RankLink = None, reset_model=None):
        self.engine = engine
        self.chunker = chunker
        self.link = link
        self.reset_model = reset_model
        self.buffer = new_buffer()
        self.lock = threading.Lock()  # guards chunker and buffer; never held during GPU work
        self.running = True
        self.active = False  # set by the client's "start"; nothing is sent before that
        self.speaking = False  # True from speech until "end"; idle filler must not block speech renders
        self.reset_requested = False  # done by the render thread, so collectives stay on one thread
        self.flush_gen = 0  # bumped by flush/start/stop; a chunk rendered across one is discarded
        # Nods live on the asyncio thread only (client messages and the sender), so they need no lock.
        self.nod_warp = NodWarp(px=NOD_PX) if LISTEN_NODS else None
        self.nods = self._new_nods()
        self.chunk_seconds = chunker.chunk_samples / chunker.sample_rate

    @staticmethod
    def _new_nods():
        return NodScheduler(after_s=NOD_AFTER_S, interval_s=NOD_INTERVAL_S) if LISTEN_NODS else None

    # --- active listening (asyncio thread) ---
    def listening_event(self, kind: str, on: bool, now: float) -> None:
        """Client messages "listen" / "pause" / "agent_speaking" from snow's forwarder."""
        if self.nods is None:
            return
        if kind == "listen":
            self.nods.set_listening(on, now)
        elif kind == "pause":
            self.nods.pause(now)
        elif kind == "agent_speaking":
            self.nods.set_agent_speaking(on, now)

    def nod_frame(self, frame: np.ndarray, audio: np.ndarray, now: float) -> np.ndarray:
        """The frame to send at `now`: with the listening nod applied while one plays."""
        if self.nods is None:
            return frame
        nurse_speaking = bool(audio.size) and float(np.abs(audio).max()) > SPEECH_PEAK
        amount = self.nods.amount(now, allow_start=not nurse_speaking)  # her voice never starts a nod
        return self.nod_warp.apply(frame, amount) if amount > 0.0 else frame

    # --- client-driven state changes (called from the asyncio thread) ---
    def push_speech(self, pcm: np.ndarray) -> None:
        with self.lock:
            self.speaking = True
            self.chunker.push(pcm)

    def end_speech(self) -> None:
        with self.lock:
            self.speaking = False
            self.chunker.pad_to_chunk()

    def flush(self) -> None:
        """Barge-in: stop talking now. Drops queued speech and frames, discards the chunk being rendered,
        and resets motion to the reference image and the audio context to silence, so the next frames
        are fresh (mouth closed) instead of continuing the interrupted reply."""
        with self.lock:
            self.speaking = False
            self.chunker.flush()
            self.buffer.flush()
            self.flush_gen += 1
            self.reset_requested = True
        if self.nods is not None:
            self.nods.flush(time.monotonic())

    def start(self, prebuffer_s: float) -> None:
        with self.lock:
            self.chunker.flush()
            self.buffer = new_buffer(prebuffer_s)
            self.active = True
            self.reset_requested = True
            self.flush_gen += 1  # a chunk still rendering belongs to the previous call
        self.nods = self._new_nods()  # a new call: no carried-over turn state

    def stop(self) -> None:
        with self.lock:
            self.speaking = False
            self.chunker.flush()
            self.buffer = new_buffer()
            self.active = False
            self.flush_gen += 1

    def pop_frame(self):
        with self.lock:
            return self.buffer.pop_frame() if self.active else None

    # --- render thread ---
    def reset_conversation(self) -> None:
        if self.link is not None:
            self.link.send(RankLink.RESET)
        self.engine.reset()
        if self.reset_model is not None:
            self.reset_model()

    def render_loop(self) -> None:
        while self.running:
            with self.lock:
                do_reset, self.reset_requested = self.reset_requested, False
                gen = self.flush_gen
                if not do_reset:
                    has_speech = self.chunker.queued_samples >= self.chunker.chunk_samples
                    if has_speech:
                        chunk, speech = self.chunker.pop_chunk(), True
                    else:
                        need_idle = self.active and not self.speaking and self.buffer.buffered_seconds < IDLE_TARGET_S
                        chunk, speech = (self.chunker.idle_chunk(), False) if need_idle else (None, False)
            if do_reset:
                self.reset_conversation()
                continue
            if chunk is None:
                time.sleep(0.005)
                continue
            t0 = time.monotonic()
            if self.link is not None:
                self.link.send(RankLink.RENDER, chunk, speech)
            out = self.engine.render_chunk(chunk, speech)  # GPU work, lock released
            dt = time.monotonic() - t0
            with self.lock:
                if gen != self.flush_gen:  # flushed while rendering: this chunk belongs to the interrupted reply
                    continue
                self.buffer.push_chunk(out["frames"], out["audio"], speech=out["speech"])
                buffered = self.buffer.buffered_seconds
            if DEBUG:
                print(f"[render] speech={speech} took={dt:.2f}s buffered={buffered:.2f}s t={time.monotonic():.2f}", flush=True)


def follower_loop(engine: StreamingAvatarEngine, link: RankLink, reset_model) -> None:
    """Ranks > 0: mirror rank 0's renders so the sequence-parallel collectives line up."""
    while True:
        cmd, chunk, speech = link.recv()
        if cmd == RankLink.STOP:
            return
        if cmd == RankLink.RESET:
            engine.reset()
            reset_model()
        else:
            engine.render_chunk(chunk, speech)  # frames discarded; rank 0 keeps the output


def encode_jpeg(frame_rgb: np.ndarray) -> bytes:
    import cv2

    bgr = np.ascontiguousarray(frame_rgb[..., ::-1])  # OpenCV expects BGR and a contiguous array
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise RuntimeError("jpeg encode failed")
    return buf.tobytes()


async def sender(ws, session: Session) -> None:
    tick = 1.0 / VIDEO_FPS
    next_t = time.monotonic()
    was_playing = False
    while True:
        item = session.pop_frame()
        if DEBUG and item is None and was_playing and session.buffer.started:
            print(f"[underrun] t={time.monotonic():.2f}", flush=True)
        was_playing = item is not None
        if item is not None:
            frame, audio = item
            frame = session.nod_frame(np.asarray(frame), audio, time.monotonic())
            await ws.send(pack_frame(encode_jpeg(frame), float_to_pcm16(audio)))
        next_t += tick
        await asyncio.sleep(max(0.0, next_t - time.monotonic()))


_current_ws = None  # the one connected client; frames come from one shared session buffer


async def handle(ws, session: Session) -> None:
    # One client at a time: two senders would pop alternate frames from the shared buffer and
    # both streams would stutter (seen when a stale link outlived its call). The newest wins.
    global _current_ws
    old, _current_ws = _current_ws, ws
    if old is not None:
        print(f"closing previous client {old.remote_address} for {ws.remote_address}", flush=True)
        await old.close()
    session.stop()
    send_task = asyncio.create_task(sender(ws, session))
    print(f"client connected: {ws.remote_address}", flush=True)
    try:
        async for msg in ws:
            if isinstance(msg, bytes):
                session.push_speech(pcm16_to_float(msg))
                continue
            cmd = json.loads(msg)
            kind = cmd.get("type")
            if kind == "start":
                session.start(float(cmd.get("prebuffer_s", 0.0)))
            elif kind == "end":
                session.end_speech()
            elif kind in ("listen", "pause", "agent_speaking"):
                session.listening_event(kind, bool(cmd.get("on", False)), time.monotonic())
            elif kind == "flush":
                session.flush()
                # Every frame sent before this is the interrupted reply; the client drops those. The sender
                # pops and sends each frame with no await in between, so the order on the socket is exact.
                await ws.send(json.dumps({"type": "flushed"}))
            else:
                print(f"unknown command: {cmd}", flush=True)
    finally:
        send_task.cancel()
        if _current_ws is ws:  # a replaced client must not stop its successor's session
            _current_ws = None
            session.stop()
        print("client disconnected", flush=True)


def build_fake_session(args) -> Session:
    chunker = AudioChunker(args.model_type)

    def encode(window):
        return window

    def run_model(_embedding):
        # gray frames, so the client can test transport and A/V sync without a GPU
        return np.full((33, 512, 512, 3), 128, dtype=np.uint8)

    engine = StreamingAvatarEngine(chunker, encode, run_model, motion_frames_num=5)
    return Session(engine, chunker)


def build_model(args, world_size: int):
    """Load FlashHead on this rank. Returns (engine, chunker, reset_model, link)."""
    import torch
    from flash_head.inference import (
        get_audio_embedding,
        get_base_data,
        get_infer_params,
        get_pipeline,
        run_pipeline,
    )

    pipe = get_pipeline(world_size=world_size, ckpt_dir="models/SoulX-FlashHead-1_3B", model_type=args.model_type,
                        wav2vec_dir="models/wav2vec2-base-960h")
    get_base_data(pipe, cond_image_path_or_dir=args.cond_image, base_seed=42, use_face_crop=False)
    p = get_infer_params()
    audio_end_idx = p["cached_audio_duration"] * p["tgt_fps"]
    audio_start_idx = audio_end_idx - p["frame_num"]

    chunker = AudioChunker(args.model_type, sample_rate=p["sample_rate"])

    def encode(window):
        return get_audio_embedding(pipe, window, audio_start_idx, audio_end_idx)

    def run_model(embedding):
        frames = run_pipeline(pipe, embedding)
        return frames.round().clamp(0, 255).to(torch.uint8).cpu().numpy()

    engine = StreamingAvatarEngine(chunker, encode, run_model, motion_frames_num=p["motion_frames_num"],
                                   cached_audio_duration=p["cached_audio_duration"],
                                   sample_rate=p["sample_rate"])
    link = RankLink(chunker.chunk_samples) if world_size > 1 else None
    return engine, chunker, pipe.reset_person_name, link


async def serve(args, session: Session) -> None:
    import websockets

    threading.Thread(target=session.render_loop, daemon=True).start()

    async def handler(ws):
        await handle(ws, session)

    async with websockets.serve(handler, args.host, args.port, max_size=2 ** 22):
        print(f"gpu_server listening on {args.host}:{args.port} (fake={args.fake})", flush=True)
        await asyncio.Future()  # run forever


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model_type", choices=["lite", "pro"], default="pro")
    ap.add_argument("--cond_image", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "figures", "nurse_image3.png"))
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--fake", action="store_true", help="skip the model; gray frames only")
    args = ap.parse_args()

    if args.fake:
        asyncio.run(serve(args, build_fake_session(args)))
        return

    world_size = int(os.environ.get("WORLD_SIZE", 1))
    rank = int(os.environ.get("RANK", 0))
    engine, chunker, reset_model, link = build_model(args, world_size)

    # Warm up every rank together (the first chunk compiles; about 80 s for Pro on 2 GPUs).
    if rank == 0:
        print(f"warming up model on {world_size} GPU(s) (first chunk is slow)...", flush=True)
    t0 = time.time()
    if link is not None and rank == 0:
        link.send(RankLink.RENDER, chunker.idle_chunk(), False)
    if link is not None and rank > 0:
        cmd, chunk, speech = link.recv()
        engine.render_chunk(chunk, speech)
    else:
        engine.render_chunk(chunker.idle_chunk(), False)  # output discarded
    engine.reset()
    reset_model()

    if rank > 0:
        print(f"[rank {rank}] warmup done in {time.time() - t0:.1f}s; following rank 0", flush=True)
        follower_loop(engine, link, reset_model)
        return
    print(f"warmup done in {time.time() - t0:.1f}s", flush=True)
    asyncio.run(serve(args, Session(engine, chunker, link=link, reset_model=reset_model)))


if __name__ == "__main__":
    main()
