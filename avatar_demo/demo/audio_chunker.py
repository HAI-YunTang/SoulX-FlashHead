"""Turns streamed speech audio into fixed-size chunks for FlashHead.

FlashHead consumes audio in chunks of `frames_per_chunk` new video frames at 25 fps
(Lite: 24 frames, Pro: 28 frames). This buffer collects TTS PCM as it arrives and
hands out exactly one chunk at a time. When nothing is queued, the caller takes an
idle (silence) chunk so the avatar keeps moving without a visible cut.
"""

from collections import deque

import numpy as np

SAMPLE_RATE = 16000
VIDEO_FPS = 25
FRAMES_PER_CHUNK = {"lite": 24, "pro": 28}


class AudioChunker:
    def __init__(self, model_type: str, sample_rate: int = SAMPLE_RATE):
        if model_type not in FRAMES_PER_CHUNK:
            raise ValueError(f"unknown model_type {model_type!r}, expected lite or pro")
        self.sample_rate = sample_rate
        self.frames_per_chunk = FRAMES_PER_CHUNK[model_type]
        self.chunk_samples = round(self.frames_per_chunk / VIDEO_FPS * sample_rate)
        self._buf = deque()  # float32 arrays, oldest first
        self._queued = 0  # total samples in _buf

    @property
    def queued_seconds(self) -> float:
        return self._queued / self.sample_rate

    @property
    def queued_samples(self) -> int:
        return self._queued

    def pad_to_chunk(self) -> None:
        """Pad queued speech with silence to a whole chunk, so the final partial chunk renders at end of reply."""
        remainder = self._queued % self.chunk_samples
        if remainder:
            self.push(np.zeros(self.chunk_samples - remainder, dtype=np.float32))

    def push(self, pcm: np.ndarray) -> None:
        """Append speech audio (float32 mono at sample_rate)."""
        pcm = np.asarray(pcm, dtype=np.float32).reshape(-1)
        if pcm.size:
            self._buf.append(pcm)
            self._queued += pcm.size

    def pop_chunk(self):
        """Return the next full chunk of speech, or None if not enough audio is queued yet."""
        if self._queued < self.chunk_samples:
            return None
        out = np.empty(self.chunk_samples, dtype=np.float32)
        filled = 0
        while filled < self.chunk_samples:
            head = self._buf[0]
            take = min(head.size, self.chunk_samples - filled)
            out[filled:filled + take] = head[:take]
            filled += take
            if take == head.size:
                self._buf.popleft()
            else:
                self._buf[0] = head[take:]
        self._queued -= self.chunk_samples
        return out

    def idle_chunk(self) -> np.ndarray:
        """Silence for one chunk, used while the nurse is not speaking."""
        return np.zeros(self.chunk_samples, dtype=np.float32)

    def flush(self) -> None:
        """Drop all queued speech, e.g. when the patient barges in."""
        self._buf.clear()
        self._queued = 0
