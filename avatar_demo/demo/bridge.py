"""Bridge between the Mac page and the GPU server (replaces relay.py on port 8765).

Mac page --ws--> bridge (container :8765) --ws--> GPU server (tunnel :8767)

- Binary and control messages from the page are forwarded to the GPU server unchanged.
- Video/audio frames from the GPU server are forwarded back to the page unchanged.
- {"type": "patient_text", "text": ...} from the page starts a nurse turn:
  LLM reply (Anthropic) -> ElevenLabs TTS (Rebecka v2, 16 kHz PCM) -> GPU server.
  The reply text is sent back to the page as {"type": "nurse_text", "text": ...}.

Without ANTHROPIC_API_KEY the bridge uses a fixed placeholder reply, so the pipeline can be tested.

  source ~/.bashrc
  python3 bridge.py
"""

import asyncio
import json
import os
import threading
import urllib.request

import websockets

from tts_to_server import tts_pcm_stream, PCM_CHUNK

LISTEN = ("127.0.0.1", 8765)
UPSTREAM = "ws://127.0.0.1:8767"
LLM_MODEL = "claude-haiku-5-5"
PREBUFFER_S = 4.0
SYSTEM = (
    "You are a friendly nurse on a call with a patient about their appointments. "
    "Reply in one or two short, plain spoken sentences, with no lists or markdown. "
    "Confirm any change clearly."
)


def llm_reply(messages):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        last = messages[-1]["content"]
        return f"Thanks, I heard you say: {last}. Let me check that for you."
    body = {"model": LLM_MODEL, "max_tokens": 120, "system": SYSTEM, "messages": messages}
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(), method="POST",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text").strip()


async def tts_async(text):
    """Yield ElevenLabs PCM chunks as they arrive (the blocking HTTP read runs in a thread)."""
    loop = asyncio.get_running_loop()
    q = asyncio.Queue()

    def worker():
        try:
            for chunk in tts_pcm_stream(text):
                loop.call_soon_threadsafe(q.put_nowait, chunk)
        finally:
            loop.call_soon_threadsafe(q.put_nowait, None)

    threading.Thread(target=worker, daemon=True).start()
    while (chunk := await q.get()) is not None:
        yield chunk


async def nurse_turn(text, history, up, page, lock):
    async with lock:
        history.append({"role": "user", "content": text})
        reply = await asyncio.to_thread(llm_reply, list(history))
        history.append({"role": "assistant", "content": reply})
        print(f"[turn] patient: {text!r}\n[turn] nurse:   {reply!r}", flush=True)
        await page.send(json.dumps({"type": "nurse_text", "text": reply}))
        await up.send(json.dumps({"type": "start", "prebuffer_s": PREBUFFER_S}))
        pending = bytearray()
        async for chunk in tts_async(reply):
            pending.extend(chunk)
            while len(pending) >= PCM_CHUNK:
                await up.send(bytes(pending[:PCM_CHUNK]))
                del pending[:PCM_CHUNK]
                await asyncio.sleep(0.1)  # live pace
        if pending:
            await up.send(bytes(pending))
        await up.send(json.dumps({"type": "end"}))


async def handle_page(page):
    print("[bridge] page connected", flush=True)
    history, lock = [], asyncio.Lock()
    async with websockets.connect(UPSTREAM, max_size=2 ** 22) as up:
        async def up_to_page():
            async for msg in up:
                await page.send(msg)

        async def page_to_up():
            async for msg in page:
                if isinstance(msg, bytes):
                    await up.send(msg)
                    continue
                cmd = json.loads(msg)
                if cmd.get("type") == "patient_text" and cmd.get("text", "").strip():
                    asyncio.create_task(nurse_turn(cmd["text"].strip(), history, up, page, lock))
                else:
                    await up.send(msg)

        tasks = [asyncio.create_task(up_to_page()), asyncio.create_task(page_to_up())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
    print("[bridge] page disconnected", flush=True)


async def main():
    async with websockets.serve(handle_page, *LISTEN, max_size=2 ** 22):
        mode = "Anthropic LLM" if os.environ.get("ANTHROPIC_API_KEY") else "placeholder replies (no ANTHROPIC_API_KEY)"
        print(f"[bridge] listening on {LISTEN[0]}:{LISTEN[1]} -> {UPSTREAM}; {mode}", flush=True)
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
