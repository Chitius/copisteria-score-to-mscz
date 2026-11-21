from __future__ import annotations

import unittest

from scorepipe.core.positions import between


class PositionsTest(unittest.TestCase):
    def test_same_measure_uses_onset(self):
        self.assertTrue(between(2, 1.0, 2, 0.0, 2, 2.0))
        self.assertFalse(between(2, 2.0, 2, 0.0, 2, 2.0))

    def test_later_measure_is_not_between_an_earlier_span(self):
        self.assertFalse(between(3, 1.0, 1, 0.0, 2, 2.0))

    def test_intermediate_and_stop_measures(self):
        self.assertTrue(between(2, 0.0, 1, 0.0, 3, 0.0))
        self.assertTrue(between(3, 0.5, 2, 0.0, 3, 2.0))


if __name__ == "__main__":
    unittest.main()
