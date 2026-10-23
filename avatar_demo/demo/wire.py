"""Binary wire format for the GPU server's WebSocket.

Server -> client, one message per video frame:
    uint32 little-endian jpeg_len | jpeg bytes | 640 samples of int16 little-endian PCM (16 kHz)

Client -> server:
    binary message = int16 little-endian PCM at 16 kHz (speech from TTS)
    text message   = JSON control: {"type": "start", "prebuffer_s": float} | {"type": "end"} | {"type": "flush"}
"""

import struct

import numpy as np


def pack_frame(jpeg: bytes, pcm16: bytes) -> bytes:
    return struct.pack("<I", len(jpeg)) + jpeg + pcm16


def unpack_frame(msg: bytes):
    (n,) = struct.unpack_from("<I", msg, 0)
    return msg[4:4 + n], msg[4 + n:]


def float_to_pcm16(x: np.ndarray) -> bytes:
    # same 32768 scale as pcm16_to_float, so the round trip is exact to one step
    return np.clip(np.asarray(x, dtype=np.float32) * 32768.0, -32768, 32767).astype("<i2").tobytes()


def pcm16_to_float(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype="<i2").astype(np.float32) / 32768.0
