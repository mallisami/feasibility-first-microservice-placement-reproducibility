from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mape_cap_bplus.v03_evidence import atomic_write_json, create_run_root, sha256, write_manifest


class V03EvidenceTests(unittest.TestCase):
    def test_run_identity_is_never_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = create_run_root(base, "fixed")
            self.assertTrue((root / "raw").is_dir())
            with self.assertRaises(FileExistsError):
                create_run_root(base, "fixed")

    def test_manifest_is_stable_and_excludes_itself(self):
        with tempfile.TemporaryDirectory() as directory:
            root = create_run_root(Path(directory), "fixed")
            atomic_write_json(root / "raw" / "a.json", {"a": 1})
            manifest = root / "manifests" / "run.sha256"
            write_manifest(root, manifest)
            first = sha256(manifest)
            write_manifest(root, manifest)
            self.assertEqual(first, sha256(manifest))
            self.assertNotIn("manifests/run.sha256", manifest.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
