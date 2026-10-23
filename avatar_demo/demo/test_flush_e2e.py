"""End to end against a running gpu_server (e.g. --fake with AVATAR_IDLE_TARGET_S=1.0): a flush mid-reply
is acknowledged with "flushed", and after it only silent (fresh idle) frames arrive, never the old reply.

  AVATAR_IDLE_TARGET_S=1.0 python gpu_server.py --fake --port 8799 ... &
  python test_flush_e2e.py --url ws://127.0.0.1:8799
"""

import argparse
import asyncio
import json

import numpy as np
import websockets

from wire import float_to_pcm16, unpack_frame


async def run(url: str) -> None:
    async with websockets.connect(url, max_size=2 ** 22) as ws:
        await ws.send(json.dumps({"type": "start", "prebuffer_s": 0.0}))
        await ws.send(float_to_pcm16(np.full(16000 * 6, 0.25, dtype=np.float32)))  # a 6 s reply, all at once
        speech_before = 0
        while speech_before < 10:  # the reply is playing
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            if isinstance(msg, bytes) and np.abs(np.frombuffer(unpack_frame(msg)[1], "<i2")).max() > 300:
                speech_before += 1
        await ws.send(json.dumps({"type": "flush"}))  # the patient barges in
        stale, flushed, after = 0, False, []
        loop = asyncio.get_running_loop()
        end = loop.time() + 4.0
        while loop.time() < end:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=max(0.1, end - loop.time()))
            except asyncio.TimeoutError:
                break
            if isinstance(msg, str):
                flushed = flushed or json.loads(msg).get("type") == "flushed"
                continue
            peak = int(np.abs(np.frombuffer(unpack_frame(msg)[1], "<i2")).max())
            if flushed:
                after.append(peak)
            else:
                stale += 1
    speech_after = sum(p > 300 for p in after)
    print(f"speech frames before flush {speech_before}, in flight {stale}, flushed={flushed}, "
          f"after: {len(after)} frames, {speech_after} with speech")
    assert flushed, "no flushed acknowledgement"
    assert after, "no fresh frames after the flush (live idle off?)"
    assert speech_after == 0, "the interrupted reply kept playing"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:8799")
    asyncio.run(run(ap.parse_args().url))
