from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from run_v03_r4 import IMAGE_STATES, LOADS, NETWORKS, STATE_SIZES, STORAGE, TOTAL, cell_id


class R4MatrixTests(unittest.TestCase):
    def test_full_matrix_has_72_unique_cells(self):
        ids = {
            cell_id(storage, image, size, network, load)
            for storage in STORAGE for image in IMAGE_STATES for size in STATE_SIZES
            for network in NETWORKS for load in LOADS
        }
        self.assertEqual(TOTAL, 72)
        self.assertEqual(len(ids), 72)

    def test_three_justified_state_sizes(self):
        self.assertEqual(set(STATE_SIZES), {"small", "medium", "large"})
        self.assertEqual(STATE_SIZES["small"], 1024**2)
        self.assertGreaterEqual(STATE_SIZES["medium"], 16 * 1024**2)
        self.assertGreaterEqual(STATE_SIZES["large"], 64 * 1024**2)


if __name__ == "__main__":
    unittest.main()
