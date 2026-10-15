from __future__ import annotations

import unittest

from unittest.mock import patch

from run_v03_r7 import deployment_health, job_manifest, parse_duration_ms, parse_probe, parse_wrk, transform_manifest


class R7ParserTests(unittest.TestCase):
    def test_transform_manifest_rewrites_memcached_and_sets_pull_policy(self) -> None:
        source = "        - image: memcached\n          name: cache\n"
        transformed = transform_manifest(source)
        self.assertIn("image: memcached:alpine", transformed)
        self.assertIn("imagePullPolicy: IfNotPresent", transformed)

    def test_transform_manifest_pins_static_volume(self) -> None:
        transformed = transform_manifest(
            "spec:\n  storageClassName: standard\n",
            __import__("pathlib").Path("geo/geo-pvc.yaml"),
        )
        self.assertIn("volumeName: geo-pv", transformed)

    def test_parse_duration_ms(self) -> None:
        self.assertEqual(parse_duration_ms("250us"), 0.25)
        self.assertEqual(parse_duration_ms("2.5ms"), 2.5)
        self.assertEqual(parse_duration_ms("1.2s"), 1200.0)

    def test_parse_wrk_histogram_throughput_and_errors(self) -> None:
        text = """
  1500 requests in 30.00s, 1.00MB read
  Non-2xx or 3xx responses: 3
  Socket errors: connect 1, read 2, write 0, timeout 4
Requests/sec:     50.00
  50.000%    2.50ms
  90.000%   10.00ms
  99.000%  250.00ms
"""
        parsed = parse_wrk(text)
        self.assertEqual(parsed["requests"], 1500)
        self.assertEqual(parsed["requests_per_second"], 50.0)
        self.assertEqual(parsed["total_errors"], 10)
        self.assertEqual(parsed["latency"]["p99_ms"], 250.0)

    def test_parse_probe_outage(self) -> None:
        parsed = parse_probe("OK\nFAIL\nFAIL\nOK\n")
        self.assertEqual(parsed["samples"], 4)
        self.assertEqual(parsed["failures"], 2)
        self.assertEqual(parsed["longest_outage_seconds"], 0.4)

    def test_job_commands_are_wall_clock_bounded(self) -> None:
        manifest = job_manifest("timeout-regression", duration=30, rate=50)
        spec = manifest["spec"]
        containers = spec["template"]["spec"]["containers"]
        wrk_command = containers[0]["command"][-1]
        probe_command = containers[1]["command"][-1]

        self.assertEqual(spec["activeDeadlineSeconds"], 210)
        self.assertIn("-T 2s", wrk_command)
        self.assertIn("end=$(( $(date +%s) + 30 ))", probe_command)
        self.assertIn("timeout 0.25 wget", probe_command)
        self.assertNotIn("i -lt", probe_command)

    @patch("run_v03_r7.kubectl_json")
    def test_deployment_health_rejects_zero_replicas(self, mocked) -> None:
        mocked.side_effect = [
            {"items": [{"metadata": {"name": "db"}, "spec": {"replicas": 0}, "status": {"readyReplicas": 0}}]},
            {"items": []},
        ]
        health = deployment_health()
        self.assertFalse(health["accepted"])
        self.assertEqual(health["zero_replica_deployments"], ["db"])


if __name__ == "__main__":
    unittest.main()
