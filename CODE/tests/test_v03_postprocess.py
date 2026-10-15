from __future__ import annotations

import unittest

from run_v03_postprocess import holm_adjust, paired_result


class V03PostprocessTests(unittest.TestCase):
    def test_holm_adjustment_is_monotone_in_rank(self) -> None:
        adjusted = holm_adjust([0.01, 0.04, 0.03])
        self.assertEqual(adjusted, [0.03, 0.06, 0.06])

    def test_paired_result_counts_independent_pairs(self) -> None:
        result = paired_result("R7", "stable", "rps", "BPlus", "Baseline", [(2, 1), (3, 1), (4, 1)])
        self.assertEqual(result["independent_replicate_n"], 3)
        self.assertEqual(result["paired_mean_difference"], 2.0)
        self.assertEqual(result["positive_pairs"], 3)


if __name__ == "__main__":
    unittest.main()
