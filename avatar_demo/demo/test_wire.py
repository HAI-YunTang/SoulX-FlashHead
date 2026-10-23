import unittest

import numpy as np

from wire import float_to_pcm16, pack_frame, pcm16_to_float, unpack_frame


class WireTest(unittest.TestCase):
    def test_frame_roundtrip(self):
        jpeg = b"\xff\xd8fake-jpeg\xff\xd9"
        pcm = float_to_pcm16(np.linspace(-0.5, 0.5, 640, dtype=np.float32))
        j2, p2 = unpack_frame(pack_frame(jpeg, pcm))
        self.assertEqual(j2, jpeg)
        self.assertEqual(p2, pcm)

    def test_empty_jpeg_still_parses(self):
        j, p = unpack_frame(pack_frame(b"", b"\x00\x00"))
        self.assertEqual(j, b"")
        self.assertEqual(p, b"\x00\x00")

    def test_pcm_roundtrip_is_close(self):
        x = np.linspace(-1, 1, 1000, dtype=np.float32)
        y = pcm16_to_float(float_to_pcm16(x))
        self.assertLess(np.abs(x - y).max(), 1 / 32767 + 1e-6)

    def test_pcm_clips_out_of_range(self):
        y = pcm16_to_float(float_to_pcm16(np.array([2.0, -3.0], dtype=np.float32)))
        self.assertAlmostEqual(float(y[0]), 32767 / 32768, places=4)
        self.assertAlmostEqual(float(y[1]), -32767 / 32768, places=4)


if __name__ == "__main__":
    unittest.main()
