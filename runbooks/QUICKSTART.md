# Quick verification

Run from the package root. These commands verify the archive, the code, and all experimental campaign outputs without re-running any experiment.

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -r CODE/requirements-lock.txt

python tools/verify_package.py          # SHA-256 of every file against SHA256SUMS.txt + campaign checks
python -m pytest -q CODE/tests
```

Then follow `../REVIEWER_WORKFLOW.md` to recompute tables and figures from raw records, and `FULL_RERUN.md` / `SUPPORTING_RERUN.md` / `../EXTENSION_STUDIES/README.md` to re-run experiments.
