"""Render the nurse's idle clip: streams near-silent audio to the GPU server and saves the frames.

The browser loops this clip between replies (AvatarPanel), so the nurse never freezes on the last
frame. Live idle rendering on the server would delay each reply behind an idle chunk.

  python render_idle_clip.py --url ws://127.0.0.1:8767 --seconds 8 --out_dir /tmp/idle_frames
  then build the loop with make_idle_loop.sh
"""

import argparse
import asyncio
import json
import os
import time

import numpy as np
import websockets

from wire import float_to_pcm16, unpack_frame


async def run(args):
    rng = np.random.default_rng(0)
    # Pure zeros can look frozen; a -60 dB noise floor is still heard as silence.
    pcm = float_to_pcm16(rng.normal(0.0, 10 ** (-60 / 20), int(args.seconds * 16000)))
    os.makedirs(args.out_dir, exist_ok=True)
    async with websockets.connect(args.url, max_size=2 ** 22) as ws:
        await ws.send(json.dumps({"type": "start", "prebuffer_s": 0.0}))

        async def send_audio():
            step = 16000 // 10 * 2  # 100 ms of int16 per message, paced like live TTS
            for i in range(0, len(pcm), step):
                await ws.send(pcm[i:i + step])
                await asyncio.sleep(0.1)
            await ws.send(json.dumps({"type": "end"}))

        sender = asyncio.create_task(send_audio())
        frames = 0
        t_end = time.time() + args.seconds + 10
        while time.time() < t_end:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=3.0 if frames else 10.0)
            except asyncio.TimeoutError:
                break
            jpeg, _ = unpack_frame(msg)
            with open(os.path.join(args.out_dir, f"{frames:05d}.jpg"), "wb") as f:
                f.write(jpeg)
            frames += 1
        await sender
    print(f"saved {frames} frames to {args.out_dir}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:8767")
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--out_dir", required=True)
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
