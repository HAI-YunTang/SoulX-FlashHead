"""Streaming chunk loop for FlashHead, mirroring generate_video.py's 'stream' mode.

Each step takes one chunk of audio (speech, or silence when idle), appends it to a
rolling window of cached audio, encodes the window, runs the model, and drops the
motion-frame overlap. The model and the audio encoder are injected so the loop can
be tested without a GPU; the real ones come from flash_head/inference.py.
"""

from collections import deque

import numpy as np

from audio_chunker import AudioChunker


class StreamingAvatarEngine:
    def __init__(self, chunker: AudioChunker, encode_audio, run_model,
                 motion_frames_num: int, cached_audio_duration: float = 8.0,
                 sample_rate: int = 16000):
        """
        chunker: source of speech chunks (pop_chunk / idle_chunk).
        encode_audio(window: np.ndarray) -> embedding for the model.
        run_model(embedding) -> uint8 frames, shape (T, H, W, 3), T = frames incl. motion overlap.
        motion_frames_num: overlap frames to drop from each output (5 for FlashHead).
        cached_audio_duration: seconds of audio context kept for the encoder (8 s in the repo).
        """
        self.chunker = chunker
        self.encode_audio = encode_audio
        self.run_model = run_model
        self.motion_frames_num = motion_frames_num
        self.cached_samples = int(cached_audio_duration * sample_rate)
        self.audio_dq = deque([0.0] * self.cached_samples, maxlen=self.cached_samples)
        self.chunk_idx = 0

    def reset(self) -> None:
        """Start a new conversation: clear the audio context and the chunk counter."""
        self.audio_dq = deque([0.0] * self.cached_samples, maxlen=self.cached_samples)
        self.chunk_idx = 0

    def step(self):
        """Render the next chunk. Returns dict(frames, audio, speech) with matching lengths."""
        chunk = self.chunker.pop_chunk()
        speech = chunk is not None
        if not speech:
            chunk = self.chunker.idle_chunk()
        return self.render_chunk(chunk, speech)

    def render_chunk(self, chunk: np.ndarray, speech: bool):
        """Render one already-popped chunk. Split out so callers can release their audio lock during the GPU call."""
        self.audio_dq.extend(chunk.tolist())
        window = np.array(self.audio_dq, dtype=np.float32)
        embedding = self.encode_audio(window)
        frames = self.run_model(embedding)[self.motion_frames_num:]

        self.chunk_idx += 1
        return {"frames": frames, "audio": chunk, "speech": speech}
