import math
import unittest
from studio.audio_balance import LevelController


class BalanceTests(unittest.TestCase):
    def feed(self, controller, level_db, start, seconds):
        values = []
        for index in range(int(seconds * 4)):
            peak = 10 ** (level_db / 20)
            values.append(controller.update(peak, start + index / 4))
        return values

    def test_continuous_changes_converge_both_directions_with_limits(self):
        controller = LevelController()
        quiet = self.feed(controller, -30, 0, 12)
        self.assertAlmostEqual(quiet[-1], 6, delta=.21)
        loud = self.feed(controller, -15, 12, 12)
        self.assertAlmostEqual(loud[-1], -9, delta=.21)
        quiet_again = self.feed(controller, -30, 24, 25)
        self.assertAlmostEqual(quiet_again[-1], 6, delta=.21)
        for values in (quiet, loud, quiet_again):
            self.assertTrue(all(-24 <= value <= 6 for value in values))
            self.assertTrue(all(-1.501 <= b - a <= .501 for a, b in zip(values, values[1:])))

    def test_silence_noise_and_invalid_meter_do_not_increase_gain(self):
        controller = LevelController()
        self.assertEqual(self.feed(controller, -65, 0, 20)[-1], 0)
        self.feed(controller, -30, 20, 12)
        self.assertGreater(controller.gain_db, 5)
        self.assertAlmostEqual(self.feed(controller, -65, 32, 12)[-1], 0)
        for peak in (None, float('nan'), float('inf'), -1):
            self.assertEqual(controller.update(peak, 60), 0)

    def test_brief_speech_gaps_do_not_reset_learning(self):
        controller = LevelController()
        for index in range(60):
            peak = 0 if index % 5 == 0 else 10 ** (-30 / 20)
            controller.update(peak, index / 4)
        self.assertGreater(controller.gain_db, 5)
        controller.reset()
        self.assertEqual(controller.gain_db, 0)
        self.assertFalse(controller.samples)
