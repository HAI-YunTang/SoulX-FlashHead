import unittest

import numpy as np

from playback_buffer import PlaybackBuffer, SAMPLES_PER_FRAME


def chunk(n_frames, value):
    frames = np.full((n_frames, 4, 4, 3), value, dtype=np.uint8)
    audio = np.full(n_frames * SAMPLES_PER_FRAME, float(value), dtype=np.float32)
    return frames, audio


class PlaybackBufferTest(unittest.TestCase):
    def test_waits_for_prebuffer_then_plays_in_order(self):
        b = PlaybackBuffer(prebuffer_seconds=2.0)  # 50 frames
        b.push_chunk(*chunk(28, 1))
        self.assertIsNone(b.pop_frame())  # 28 < 50
        b.push_chunk(*chunk(28, 2))  # 56 >= 50
        frame, audio = b.pop_frame()
        self.assertEqual(frame[0, 0, 0], 1)
        self.assertEqual(audio[0], 1.0)
        self.assertTrue(b.started)

    def test_frames_and_audio_stay_aligned(self):
        b = PlaybackBuffer(prebuffer_seconds=0.0)
        frames = np.stack([np.full((4, 4, 3), i, dtype=np.uint8) for i in range(28)])
        audio = np.arange(28 * SAMPLES_PER_FRAME, dtype=np.float32)
        b.push_chunk(frames, audio)
        for i in range(28):
            f, a = b.pop_frame()
            self.assertEqual(f[0, 0, 0], i)
            np.testing.assert_array_equal(a, audio[i * SAMPLES_PER_FRAME:(i + 1) * SAMPLES_PER_FRAME])

    def test_underrun_returns_none_and_resumes(self):
        b = PlaybackBuffer(prebuffer_seconds=0.0)
        b.push_chunk(*chunk(1, 7))
        self.assertIsNotNone(b.pop_frame())
        self.assertIsNone(b.pop_frame())  # nothing left
        b.push_chunk(*chunk(1, 8))
        self.assertEqual(b.pop_frame()[0][0, 0, 0], 8)

    def test_flush_resets_to_prebuffer(self):
        b = PlaybackBuffer(prebuffer_seconds=1.0)  # 25 frames
        b.push_chunk(*chunk(28, 3))
        self.assertIsNotNone(b.pop_frame())
        b.flush()
        self.assertFalse(b.started)
        self.assertEqual(b.buffered_frames, 0)
        b.push_chunk(*chunk(10, 4))
        self.assertIsNone(b.pop_frame())  # must rebuffer again

    def test_rejects_mismatched_audio(self):
        b = PlaybackBuffer()
        frames = np.zeros((28, 4, 4, 3), dtype=np.uint8)
        with self.assertRaises(ValueError):
            b.push_chunk(frames, np.zeros(10, dtype=np.float32))

    def test_buffered_seconds(self):
        b = PlaybackBuffer()
        b.push_chunk(*chunk(25, 0))
        self.assertAlmostEqual(b.buffered_seconds, 1.0)

    def test_idle_filler_does_not_open_prebuffer_gate(self):
        b = PlaybackBuffer(prebuffer_seconds=1.0)  # 25 frames
        frames, audio = chunk(40, 9)
        b.push_chunk(frames, audio, speech=False)
        self.assertIsNone(b.pop_frame())
        self.assertFalse(b.started)

    def test_new_reply_after_idle_drops_filler_and_rearms(self):
        b = PlaybackBuffer(prebuffer_seconds=1.0)
        b.push_chunk(*chunk(28, 1))  # speech
        b.push_chunk(*chunk(28, 1))  # speech
        b.pop_frame()
        self.assertTrue(b.started)
        # drain to idle playback
        while b.buffered_frames:
            b.pop_frame()
        b.push_chunk(*chunk(28, 5), speech=False)  # idle filler after the reply
        self.assertTrue(b.started)
        b.push_chunk(*chunk(10, 7))  # new reply arrives
        self.assertFalse(b.started)  # gate closed again
        self.assertEqual(b.buffered_frames, 10)  # filler dropped
        self.assertIsNone(b.pop_frame())
        b.push_chunk(*chunk(20, 7))  # now 30 speech frames >= 25
        self.assertEqual(b.pop_frame()[0][0, 0, 0], 7)


class ContinuousPlaybackBufferTest(unittest.TestCase):
    """continuous=True: live idle rendering keeps the stream going between replies."""

    def test_idle_opens_prebuffer_gate(self):
        b = PlaybackBuffer(prebuffer_seconds=1.0, continuous=True)  # 25 frames
        b.push_chunk(*chunk(20, 9), speech=False)
        self.assertIsNone(b.pop_frame())  # 20 < 25
        b.push_chunk(*chunk(20, 9), speech=False)
        self.assertEqual(b.pop_frame()[0][0, 0, 0], 9)
        self.assertTrue(b.started)

    def test_speech_after_idle_keeps_only_the_next_idle_frames(self):
        b = PlaybackBuffer(prebuffer_seconds=0.0, continuous=True, idle_keep_seconds=0.24)  # 6 frames
        b.push_chunk(*chunk(28, 5), speech=False)
        b.pop_frame()
        b.push_chunk(*chunk(28, 7))  # reply arrives while 27 idle frames are queued
        self.assertTrue(b.started)  # no re-prebuffer, so no freeze
        self.assertEqual(b.buffered_frames, 6 + 28)  # the idle lead beyond 6 frames is dropped
        values = [b.pop_frame()[0][0, 0, 0] for _ in range(34)]
        self.assertEqual(values, [5] * 6 + [7] * 28)

    def test_later_speech_chunks_are_not_trimmed(self):
        b = PlaybackBuffer(prebuffer_seconds=0.0, continuous=True, idle_keep_seconds=0.0)
        b.push_chunk(*chunk(28, 7))
        b.push_chunk(*chunk(28, 8))  # second chunk of the same reply
        self.assertEqual(b.buffered_frames, 56)

    def test_flush_keeps_playing(self):
        b = PlaybackBuffer(prebuffer_seconds=1.0, continuous=True)
        b.push_chunk(*chunk(28, 7))
        b.pop_frame()
        b.flush()
        self.assertTrue(b.started)
        self.assertIsNone(b.pop_frame())  # empty until the next render
        b.push_chunk(*chunk(10, 5), speech=False)  # idle resumes without waiting for 25 frames
        self.assertEqual(b.pop_frame()[0][0, 0, 0], 5)


if __name__ == "__main__":
    unittest.main()
