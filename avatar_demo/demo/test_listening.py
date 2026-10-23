import importlib.util
import random
import unittest

import numpy as np

from listening import NOD_S, NodScheduler, NodWarp, nod_curve

HAS_CV2 = importlib.util.find_spec("cv2") is not None
TICK = 0.04  # frames are sent at 25 fps


class Sim:
    """Drives a scheduler frame by frame, recording when nods start."""

    def __init__(self, **kw):
        self.s = NodScheduler(rng=random.Random(0), **kw)
        self.t = 0.0
        self.nods = []
        self._prev = 0.0

    def run(self, seconds):
        for _ in range(int(round(seconds / TICK))):
            a = self.s.amount(self.t)
            if a > 0 and self._prev == 0:
                self.nods.append(round(self.t, 2))
            self._prev = a
            self.t += TICK

    def talk(self, seconds):
        self.s.set_listening(True, self.t)
        self.run(seconds)

    def stop(self, seconds):
        self.s.set_listening(False, self.t)
        self.run(seconds)


class NodCurveTest(unittest.TestCase):
    def test_shape(self):
        self.assertEqual(nod_curve(0.0), 0.0)
        self.assertEqual(nod_curve(NOD_S), 0.0)
        self.assertAlmostEqual(nod_curve(0.4 * NOD_S), 1.0)
        self.assertTrue(0 < nod_curve(0.1) < 1)


class NodSchedulerTest(unittest.TestCase):
    def test_short_answer_gets_no_nod(self):
        sim = Sim()
        sim.talk(2.0)
        sim.stop(3.0)
        sim.talk(1.5)  # "yes", "October eighth, nineteen fifty"
        sim.stop(5.0)
        self.assertEqual(sim.nods, [])

    def test_nod_at_the_first_pause_after_talking_a_lot(self):
        sim = Sim()
        sim.talk(6.0)  # past the 5 s gate, no pause yet
        self.assertEqual(sim.nods, [])  # the periodic timer starts at the gate, not before
        sim.s.pause(sim.t)
        sim.run(0.2)
        self.assertEqual(len(sim.nods), 1)

    def test_pauses_before_the_gate_do_not_count(self):
        sim = Sim()
        for _ in range(4):  # 4 x 1 s of speech with flickering pauses
            sim.talk(1.0)
            sim.s.pause(sim.t)
        sim.talk(0.5)
        self.assertEqual(sim.nods, [])

    def test_long_answer_without_pauses_nods_every_5_to_8_s(self):
        sim = Sim()
        sim.talk(30.0)
        self.assertGreaterEqual(len(sim.nods), 3)
        gaps = np.diff([5.0] + sim.nods)  # the timer starts when the gate opens at 5 s
        self.assertTrue(all(4.9 <= g <= 8.1 for g in gaps), gaps)

    def test_nods_are_at_least_3_s_apart(self):
        sim = Sim()
        sim.talk(6.0)
        for _ in range(20):  # a pause every 0.3 s
            sim.s.pause(sim.t)
            sim.run(0.3)
        self.assertTrue(all(g >= 3.0 - 1e-6 for g in np.diff(sim.nods)), sim.nods)

    def test_short_pauses_keep_the_count_and_a_nurse_reply_resets_it(self):
        sim = Sim()
        sim.talk(3.0)
        sim.stop(1.0)  # short silence: still the same turn
        sim.talk(2.5)  # 5.5 s in total
        sim.s.pause(sim.t)
        sim.run(0.2)
        self.assertEqual(len(sim.nods), 1)
        sim.s.set_agent_speaking(True, sim.t)
        sim.run(2.0)
        sim.s.set_agent_speaking(False, sim.t)
        sim.talk(3.0)  # new turn: only 3 s
        sim.s.pause(sim.t)
        sim.run(0.2)
        self.assertEqual(len(sim.nods), 1)

    def test_no_nod_while_the_nurse_speaks_or_right_after_a_flush(self):
        sim = Sim()
        sim.talk(6.0)
        sim.s.set_agent_speaking(True, sim.t)
        sim.s.pause(sim.t)
        sim.run(10.0)
        self.assertEqual(sim.nods, [])

        sim = Sim()
        sim.talk(6.0)
        sim.s.flush(sim.t)  # barge-in
        sim.s.pause(sim.t)
        sim.run(1.0)
        self.assertEqual(sim.nods, [])  # quiet for 2 s after a flush
        sim.run(1.5)
        self.assertEqual(len(sim.nods), 1)


class NodWarpTest(unittest.TestCase):
    def setUp(self):
        self.w = NodWarp(px=5.0)

    def test_displacement_field(self):
        dy = self.w.dy_unit
        self.assertLess(dy[500, 20], 1e-3)  # shoulders / background corner: no motion
        self.assertLess(dy[480, 230], 1e-3)  # chest below the head
        face = dy[150:300, 180:280]
        self.assertGreater(face.min(), 4.0)  # the face moves as a whole, not squashed
        self.assertLessEqual(face.max(), 5.0 * 1.15 + 1e-4)
        self.assertGreater(dy[130, 230], dy[300, 230])  # forehead moves more than the chin

    @unittest.skipUnless(HAS_CV2, "cv2 not installed")
    def test_apply(self):
        frame = (np.random.default_rng(0).random((512, 512, 3)) * 255).astype(np.uint8)
        self.assertIs(self.w.apply(frame, 0.0), frame)  # no nod: untouched
        out = self.w.apply(frame, 1.0)
        self.assertEqual(out.shape, frame.shape)
        np.testing.assert_array_equal(out[480:, :], frame[480:, :])  # below the head is unchanged


if __name__ == "__main__":
    unittest.main()
