"""Playback buffer between the FlashHead engine and the client.

The engine renders chunks faster or slower than real time. This buffer holds the
rendered frames with their matching audio and releases one frame at a time at 25 fps.
Playback waits until `prebuffer_seconds` of media is ready, so the lag accepted for
Pro on one GPU does not turn into stalls mid-reply.

Each chunk carries frames and audio that line up: chunk_samples / frames = 640 samples
per frame at 16 kHz / 25 fps, so frame i is always paired with samples [640*i, 640*(i+1)).

continuous=True is for live idle rendering (the server renders idle motion from silence between
replies, so the stream never stops): idle frames open the prebuffer gate, a flush does not stop
playback, and speech after idle is queued behind the next idle_keep_seconds of idle frames. The
rest of the queued idle is dropped, so the reply isn't delayed by the idle lead.
"""

from collections import deque

import numpy as np

VIDEO_FPS = 25
SAMPLE_RATE = 16000
SAMPLES_PER_FRAME = SAMPLE_RATE // VIDEO_FPS  # 640


class PlaybackBuffer:
    def __init__(self, prebuffer_seconds: float = 0.0, continuous: bool = False, idle_keep_seconds: float = 0.25):
        self.prebuffer_frames = round(prebuffer_seconds * VIDEO_FPS)
        self.continuous = continuous
        self.idle_keep_frames = round(idle_keep_seconds * VIDEO_FPS)
        self._frames = deque()  # (frame uint8 HWC, audio float32 640 samples, is_speech)
        self._speech_buffered = 0  # speech frames in the queue; idle filler never opens the prebuffer gate
        self._started = False

    @property
    def buffered_frames(self) -> int:
        return len(self._frames)

    @property
    def buffered_seconds(self) -> float:
        return len(self._frames) / VIDEO_FPS

    @property
    def started(self) -> bool:
        return self._started

    def push_chunk(self, frames: np.ndarray, audio: np.ndarray, speech: bool = True) -> None:
        """Add one engine chunk. frames: (T, H, W, 3) uint8; audio: T * 640 float32 samples.
        speech=False marks idle filler."""
        t = frames.shape[0]
        if audio.size != t * SAMPLES_PER_FRAME:
            raise ValueError(f"audio has {audio.size} samples, expected {t * SAMPLES_PER_FRAME} for {t} frames")
        if speech and self._started and self._speech_buffered == 0 and not self.continuous:
            # A new reply after idle playback: drop the queued filler and wait for this reply's prebuffer,
            # so the reply starts with its lag budget instead of stalling mid-reply.
            self._frames.clear()
            self._started = False
        elif speech and self.continuous and self._speech_buffered == 0:
            while len(self._frames) > self.idle_keep_frames:  # all queued frames are idle here
                self._frames.pop()
        for i in range(t):
            seg = audio[i * SAMPLES_PER_FRAME:(i + 1) * SAMPLES_PER_FRAME]
            self._frames.append((frames[i], seg, speech))
        if speech:
            self._speech_buffered += t

    def pop_frame(self):
        """Return the next (frame, audio) pair to send, or None if playback has not started
        or nothing is buffered. Call once per 1/25 s tick."""
        if not self._started:
            gate = len(self._frames) if self.continuous else self._speech_buffered
            if gate < self.prebuffer_frames:
                return None
            self._started = True
        if not self._frames:
            return None  # underrun: caller should show the idle clip, and playback resumes on the next push
        frame, audio, speech = self._frames.popleft()
        if speech:
            self._speech_buffered -= 1
        return frame, audio

    def flush(self) -> None:
        """Barge-in: drop everything and wait for the next prebuffer (continuous: keep playing,
        idle frames resume with the next render)."""
        self._frames.clear()
        self._speech_buffered = 0
        if not self.continuous:
            self._started = False
