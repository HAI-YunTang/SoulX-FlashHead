import unittest

import numpy as np

from audio_chunker import AudioChunker
from avatar_engine import StreamingAvatarEngine

FRAMES = 33
MOTION = 5


def fake_run_model(embedding):
    # One frame per (fake) input step; the real model returns FRAMES frames per window.
    return np.zeros((FRAMES, 4, 4, 3), dtype=np.uint8)


class StreamingAvatarEngineTest(unittest.TestCase):
    def make_engine(self, model_type="pro"):
        chunker = AudioChunker(model_type)
        seen_windows = []

        def encode(window):
            seen_windows.append(window)
            return window

        engine = StreamingAvatarEngine(chunker, encode, fake_run_model, motion_frames_num=MOTION)
        return engine, chunker, seen_windows

    def test_output_frames_and_audio_match_chunk(self):
        engine, chunker, _ = self.make_engine("pro")
        chunker.push(np.ones(chunker.chunk_samples, dtype=np.float32))
        out = engine.step()
        self.assertTrue(out["speech"])
        self.assertEqual(out["frames"].shape[0], FRAMES - MOTION)  # 28 frames for Pro
        self.assertEqual(out["audio"].size, chunker.chunk_samples)

    def test_idle_step_is_silent_and_flagged(self):
        engine, _, _ = self.make_engine("lite")
        out = engine.step()
        self.assertFalse(out["speech"])
        self.assertFalse(out["audio"].any())
        self.assertEqual(out["frames"].shape[0], FRAMES - MOTION)

    def test_window_slides_and_keeps_fixed_length(self):
        engine, chunker, windows = self.make_engine("pro")
        chunker.push(np.full(chunker.chunk_samples, 0.5, dtype=np.float32))
        engine.step()
        engine.step()
        self.assertEqual(len(windows[0]), engine.cached_samples)
        self.assertEqual(len(windows[1]), engine.cached_samples)
        # step 1's speech chunk moved back one chunk; step 2 appended silence at the end
        c = chunker.chunk_samples
        np.testing.assert_allclose(windows[1][-2 * c:-c], 0.5)
        self.assertFalse(windows[1][-c:].any())

    def test_chunk_index_advances(self):
        engine, _, _ = self.make_engine("lite")
        engine.step()
        engine.step()
        self.assertEqual(engine.chunk_idx, 2)


if __name__ == "__main__":
    unittest.main()
