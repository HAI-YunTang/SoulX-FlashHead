import unittest

import numpy as np

from audio_chunker import AudioChunker, SAMPLE_RATE


class AudioChunkerTest(unittest.TestCase):
    def test_chunk_sizes_match_model(self):
        # Lite: 24 frames at 25 fps = 0.96 s; Pro: 28 frames = 1.12 s
        self.assertEqual(AudioChunker("lite").chunk_samples, 15360)
        self.assertEqual(AudioChunker("pro").chunk_samples, 17920)

    def test_unknown_model_rejected(self):
        with self.assertRaises(ValueError):
            AudioChunker("huge")

    def test_no_chunk_until_enough_audio(self):
        c = AudioChunker("lite")
        c.push(np.ones(c.chunk_samples - 1, dtype=np.float32))
        self.assertIsNone(c.pop_chunk())
        c.push(np.ones(1, dtype=np.float32))
        self.assertEqual(c.pop_chunk().size, c.chunk_samples)
        self.assertEqual(c.queued_seconds, 0.0)

    def test_chunks_span_pushes_without_gaps_or_reordering(self):
        c = AudioChunker("pro")
        data = np.arange(c.chunk_samples * 2 + 100, dtype=np.float32)
        out = []
        for piece in np.array_split(data, 37):  # uneven, small TTS packets
            c.push(piece)
            while (chunk := c.pop_chunk()) is not None:
                out.append(chunk)
        self.assertEqual(len(out), 2)
        np.testing.assert_array_equal(np.concatenate(out), data[: 2 * c.chunk_samples])
        self.assertAlmostEqual(c.queued_seconds, 100 / SAMPLE_RATE)

    def test_idle_chunk_is_silence_of_chunk_length(self):
        c = AudioChunker("lite")
        idle = c.idle_chunk()
        self.assertEqual(idle.size, c.chunk_samples)
        self.assertFalse(idle.any())

    def test_flush_drops_queued_speech(self):
        c = AudioChunker("lite")
        c.push(np.ones(c.chunk_samples * 3, dtype=np.float32))
        c.flush()
        self.assertIsNone(c.pop_chunk())
        self.assertEqual(c.queued_seconds, 0.0)


if __name__ == "__main__":
    unittest.main()
