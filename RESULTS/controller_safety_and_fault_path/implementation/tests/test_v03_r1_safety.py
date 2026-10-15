from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from run_v03_r1 import CampaignLock, SERVICES, apply_placement, progress, validate_placement_target


class R1SafetyTests(unittest.TestCase):
    @staticmethod
    def _nodes(*names: str) -> dict:
        return {"items": [
            {"metadata": {"name": name}, "spec": {},
             "status": {"conditions": [{"type": "Ready", "status": "True"}]}}
            for name in names
        ]}

    @staticmethod
    def _deployments() -> dict:
        return {"items": [{"metadata": {"name": service}} for service in SERVICES]}

    def test_pre_execution_validation_accepts_complete_ready_target(self):
        target = {service: "worker-a" for service in SERVICES}
        result = validate_placement_target(
            target, self._nodes("worker-a", "worker-b"), self._deployments()
        )
        self.assertEqual(result["eligible_nodes"], ["worker-a", "worker-b"])
        self.assertEqual(result["validated_services"], sorted(SERVICES))

    def test_pre_execution_validation_rejects_nonexistent_target(self):
        target = {service: "worker-a" for service in SERVICES}
        target["frontend"] = "does-not-exist"
        with self.assertRaisesRegex(ValueError, "node not found"):
            validate_placement_target(target, self._nodes("worker-a"), self._deployments())

    def test_pre_execution_validation_rejects_unready_or_unschedulable_node(self):
        nodes = self._nodes("worker-a")
        nodes["items"].append({
            "metadata": {"name": "worker-b"}, "spec": {"unschedulable": True},
            "status": {"conditions": [{"type": "Ready", "status": "True"}]},
        })
        target = {service: "worker-a" for service in SERVICES}
        target["frontend"] = "worker-b"
        with self.assertRaisesRegex(ValueError, "unschedulable"):
            validate_placement_target(target, nodes, self._deployments())

    def test_invalid_target_never_reaches_patch(self):
        target = {service: "missing" for service in SERVICES}
        with patch("run_v03_r1.kubectl_json", side_effect=[
            {"items": []}, self._nodes("worker-a"), self._deployments()
        ]), patch("run_v03_r1._patch_service_node") as mutate:
            with self.assertRaises(ValueError):
                apply_placement(target, "unit-test")
            mutate.assert_not_called()

    def test_partial_patch_failure_submits_rollback(self):
        target = {service: "worker-b" for service in SERVICES}
        pods = {"items": [{"metadata": {"labels": {"app": service}},
                           "spec": {"nodeName": "worker-a"}} for service in SERVICES]}
        with patch("run_v03_r1.kubectl_json", side_effect=[
            pods, self._nodes("worker-a", "worker-b"), self._deployments()
        ]), patch("run_v03_r1._patch_service_node", side_effect=[None, RuntimeError("injected"), None]) as mutate:
            with self.assertRaisesRegex(RuntimeError, "rollback submitted"):
                apply_placement(target, "unit-test")
            self.assertEqual(mutate.call_count, 3)
            self.assertEqual(mutate.call_args.args, (SERVICES[0], "worker-a", "unit-test:rollback"))

    def test_campaign_lock_rejects_second_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            with CampaignLock(run_root):
                with self.assertRaisesRegex(RuntimeError, "already owns"):
                    with CampaignLock(run_root):
                        pass

    def test_progress_excludes_registered_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            valid = run_root / "raw" / "r1" / "stable" / "replicate-01" / "Current" / "attempt-01" / "result.json"
            invalid = run_root / "raw" / "r1" / "stable" / "replicate-02" / "Current" / "attempt-01" / "result.json"
            for path in (valid, invalid):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({
                    "accepted": True,
                    "acceptance_gate_version": 2,
                    "duration_seconds": 20,
                    "application": {"successes": 100},
                }), encoding="utf-8")
            registry = run_root / "checkpoints" / "r1-invalidated-attempts.json"
            registry.parent.mkdir(parents=True, exist_ok=True)
            registry.write_text(json.dumps({
                "invalidated_result_paths": [invalid.relative_to(run_root).as_posix()],
            }), encoding="utf-8")

            report = progress(run_root, desired_total=2, duration=20, min_completed_requests=10)

            self.assertEqual(report["accepted_full_cells"], 1)
            self.assertEqual(report["preserved_concurrency_invalidated_attempts"], 1)
            self.assertEqual(report["remaining_cells"], 1)

    def test_capture_placement_snapshot_schema(self):
        from run_v03_r1 import capture_placement_snapshot
        pods = {"items": [{"metadata": {"name": f"{s}-pod-1", "labels": {"app": s}, "resourceVersion": "123"},
                           "spec": {"nodeName": "worker-a"},
                           "status": {"phase": "Running", "containerStatuses": [{"ready": True}]}}
                          for s in SERVICES]}
        nodes = self._nodes("worker-a", "worker-b")
        deployments = self._deployments()
        snapshot = capture_placement_snapshot(pods, nodes, deployments)
        self.assertIn("timestamp_utc", snapshot)
        self.assertIn("assignments", snapshot)
        self.assertIn("deployments", snapshot)
        self.assertIn("pods", snapshot)
        self.assertIn("nodes", snapshot)
        self.assertEqual(snapshot["assignments"]["frontend"], "worker-a")
        self.assertTrue(snapshot["pods"]["frontend"][0]["ready"])

    def test_fault_hook_triggers_rollback(self):
        target = {service: "worker-b" for service in SERVICES}
        pods = {"items": [{"metadata": {"labels": {"app": service}},
                           "spec": {"nodeName": "worker-a"}} for service in SERVICES]}
        hook_called = []
        def hook(stage, service, patched, target):
            hook_called.append((stage, service))
            if len(patched) == 1:
                raise RuntimeError("ControlledHookFailure")

        with patch("run_v03_r1.kubectl_json", side_effect=[
            pods, self._nodes("worker-a", "worker-b"), self._deployments()
        ]), patch("run_v03_r1._patch_service_node") as mutate, \
             patch("run_v03_r1.assert_healthy", return_value={"healthy": True}):
            with self.assertRaisesRegex(RuntimeError, "ControlledHookFailure"):
                apply_placement(target, "unit-test", fault_hook=hook)
            # Forward patch for service 0, hook raised, rollback patch for service 0
            self.assertEqual(mutate.call_count, 2)
            self.assertEqual(mutate.call_args.args, (SERVICES[0], "worker-a", "unit-test:rollback"))
            self.assertEqual(len(hook_called), 1)


if __name__ == "__main__":
    unittest.main()

