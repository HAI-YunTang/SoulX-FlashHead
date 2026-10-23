"""Against a running gpu_server (e.g. --fake): a second client replaces the first and gets every frame.

  python test_one_client.py --url ws://127.0.0.1:8799
"""

import argparse
import asyncio
import json

import numpy as np
import websockets

from wire import float_to_pcm16


async def run(url: str) -> None:
    speech = float_to_pcm16(np.zeros(16000 * 3, dtype=np.float32))  # 3 s
    first = await websockets.connect(url, max_size=2 ** 22)
    await first.send(json.dumps({"type": "start", "prebuffer_s": 0.0}))
    await asyncio.sleep(0.5)

    second = await websockets.connect(url, max_size=2 ** 22)
    await second.send(json.dumps({"type": "start", "prebuffer_s": 0.0}))
    await second.send(speech)
    await second.send(json.dumps({"type": "end"}))

    first_closed = False
    try:
        await asyncio.wait_for(first.recv(), timeout=2.0)
    except websockets.ConnectionClosed:
        first_closed = True
    except asyncio.TimeoutError:
        pass

    frames = 0
    try:
        while True:
            await asyncio.wait_for(second.recv(), timeout=3.0)
            frames += 1
    except asyncio.TimeoutError:
        pass
    await second.close()
    print(f"first closed: {first_closed}  second frames: {frames} (expect about 75 for 3 s)")
    assert first_closed and frames >= 70


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:8799")
    asyncio.run(run(ap.parse_args().url))
