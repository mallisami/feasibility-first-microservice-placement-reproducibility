from __future__ import annotations

import unittest

from run_v03_r5_repair import throughput_summary


class R5RepairTests(unittest.TestCase):
    def test_two_stream_summary(self) -> None:
        parsed = throughput_summary("noise\nTotal throughput [Mbps] during each service period allocation:\nSP1 = 149.1\nSP2 = 148.2\n")
        self.assertEqual(parsed, {"SP1": 149.1, "SP2": 148.2})


if __name__ == "__main__":
    unittest.main()
