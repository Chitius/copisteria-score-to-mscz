from __future__ import annotations

import unittest

from scorepipe.core.pairing import Endpoint, pair_endpoints


def endpoint(key, measure, onset, kind):
    return Endpoint(key=key, position=(measure, onset), kind=kind, payload=(measure, onset))


class PairEndpointsTest(unittest.TestCase):
    def test_clean_pair(self):
        pairing = pair_endpoints([endpoint(("1", "1"), 1, 0, "start"), endpoint(("1", "1"), 2, 0, "stop")])
        self.assertEqual(len(pairing.pairs), 1)
        self.assertEqual(pairing.orphans, [])

    def test_stop_before_start_is_orphaned(self):
        pairing = pair_endpoints([endpoint(("1", "1"), 2, 0, "stop"), endpoint(("1", "1"), 1, 0, "start")])
        self.assertEqual(pairing.pairs, [])
        self.assertEqual(len(pairing.orphans), 2)

    def test_duplicate_start_blocks_the_key_until_a_stop(self):
        pairing = pair_endpoints(
            [
                endpoint(("1", "1"), 7, 0, "start"),
                endpoint(("1", "1"), 8, 3, "start"),  # same number, still open
                endpoint(("1", "1"), 8, 0, "stop"),
                endpoint(("1", "1"), 10, 0, "stop"),
                endpoint(("1", "1"), 10, 3, "start"),
                endpoint(("1", "1"), 12, 0, "stop"),
            ]
        )
        self.assertEqual(len(pairing.pairs), 1)
        start, stop = pairing.pairs[0]
        self.assertEqual(start.position, (10, 3))
        self.assertEqual(stop.position, (12, 0))
        self.assertIn(("1", "1"), pairing.ambiguous_keys)

    def test_max_span_rejects_both_endpoints(self):
        pairing = pair_endpoints(
            [endpoint(("1", "1"), 1, 0, "start"), endpoint(("1", "1"), 10, 0, "stop")],
            max_span=6,
        )
        self.assertEqual(pairing.pairs, [])
        self.assertEqual(len(pairing.orphans), 2)


if __name__ == "__main__":
    unittest.main()
