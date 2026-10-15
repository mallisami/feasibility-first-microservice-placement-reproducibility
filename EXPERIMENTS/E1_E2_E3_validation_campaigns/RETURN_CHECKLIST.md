# Return checklist after execution

Return the entire folder after `RUN_ALL.sh` completes or stops.

Minimum records expected:

- [ ] `PREEXECUTION_SHA256SUMS.txt`
- [ ] `RUN_ALL.log`
- [ ] `POSTRUN_INVENTORY.txt` (if the campaign reached the final inventory step)
- [ ] E1 `results/`
- [ ] E1 `operator_logs/`
- [ ] E2 `results/`
- [ ] E3 `results/`
- [ ] any failed-gate or partial-run logs
- [ ] `DEVIATIONS.md` stating either `No deviations.` or every departure from the frozen protocol

Do not clean, overwrite, recompute selectively, or delete unfavorable outcomes before returning the package.
