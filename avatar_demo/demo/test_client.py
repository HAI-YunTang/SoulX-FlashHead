"""Protocol test client: streams a WAV to the GPU server as if it were TTS, then counts the frames back.

  python test_client.py --url ws://127.0.0.1:8766 --wav ../results/tts_rebecka_test.wav --prebuffer_s 1.0
"""

import argparse
import asyncio
import json
import time
import wave

import numpy as np
import websockets

from wire import float_to_pcm16, unpack_frame, pcm16_to_float


def read_wav_16k_mono(path):
    with wave.open(path, "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2, \
            "need 16 kHz mono 16-bit WAV"
        return w.readframes(w.getnframes())


async def run(args):
    pcm = read_wav_16k_mono(args.wav)
    async with websockets.connect(args.url, max_size=2 ** 22) as ws:
        await ws.send(json.dumps({"type": "start", "prebuffer_s": args.prebuffer_s}))
        t_send = time.time()

        async def send_speech():
            step = 16000 // 10 * 2  # 100 ms of int16 per message, paced like a live TTS stream
            for i in range(0, len(pcm), step):
                await ws.send(pcm[i:i + step])
                await asyncio.sleep(0.1)
            await ws.send(json.dumps({"type": "end"}))

        sender = asyncio.create_task(send_speech())
        frames, first_t, bad, jpeg_bytes = 0, None, 0, 0
        speech_frames, first_speech_t = 0, None  # with live idle, frames flow before any speech
        last_t, max_gap = None, 0.0
        t_end = time.time() + args.listen_s
        while time.time() < t_end:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=max(0.1, t_end - time.time()))
            except asyncio.TimeoutError:
                break
            jpeg, audio = unpack_frame(msg)
            if len(audio) != 640 * 2 or not jpeg.startswith(b"\xff\xd8"):
                bad += 1
                continue
            now = time.time()
            if first_t is None:
                first_t = now - t_send
            elif last_t is not None:
                max_gap = max(max_gap, now - last_t)
            last_t = now
            frames += 1
            jpeg_bytes += len(jpeg)
            if np.abs(np.frombuffer(audio, dtype='<i2')).max() > 300:
                speech_frames += 1
                if first_speech_t is None:
                    first_speech_t = now - t_send
        await sender
        print(f"frames received: {frames}  bad: {bad}  max gap between frames: {max_gap:.2f} s")
        if first_t is not None:
            print(f"time to first frame after start: {first_t:.2f} s")
        if first_speech_t is not None:
            print(f"time to first speech frame: {first_speech_t:.2f} s  (speech frames {speech_frames}, idle {frames - speech_frames})")
        if first_t is not None and frames > 1:
            span = last_t - (t_send + first_t)  # first frame to last frame, not the whole listen window
            print(f"delivery rate while playing: {(frames - 1) / span:.1f} frames/s (25 needed for live playback)")
        if frames:
            kb = jpeg_bytes / frames / 1000
            print(f"jpeg size: {kb:.1f} kB per frame = {kb * 8 * 25 / 1000:.1f} Mbit/s at 25 fps")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:8766")
    ap.add_argument("--wav", required=True)
    ap.add_argument("--prebuffer_s", type=float, default=0.0)
    ap.add_argument("--listen_s", type=float, default=20.0)
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
