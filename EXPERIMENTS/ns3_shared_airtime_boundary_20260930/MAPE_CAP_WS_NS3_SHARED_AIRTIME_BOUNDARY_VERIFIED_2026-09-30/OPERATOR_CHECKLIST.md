# Operator checklist

- [ ] Docker Desktop is running.
- [ ] WSL integration is enabled for the distribution used by `wsl.exe`.
- [ ] At least 6 GiB is free on the package/results filesystem.
- [ ] You have read the frozen protocol.
- [ ] Do not edit `config/experiment.json` or `config/case_shapes.json` after science starts.
- [ ] Run only the top-level PowerShell or WSL launcher.
- [ ] If interrupted, rerun the same launcher; do not delete failed/accepted cells.
- [ ] After completion, preserve the whole run directory and `SHA256SUMS.txt`.

## Automatic pre-execution gates

The runner must report a passing low-rate smoke test and a passing saturated single-stream duty-effect check. Do not bypass these gates. The science run must not be interpreted if the 25% shared CBAP does not materially reduce throughput relative to full-DTI access.

## Frozen runtime guard

- [ ] Do not alter the 2.0 s traffic start or 250 ms minimum all-associated lead.
- [ ] If the simulator aborts before traffic start because the association/resource guard fails, treat that as an engineering failure; do not bypass the guard.
- [ ] A deassociation after traffic has begun is part of the packet-level outcome and must not be filtered out.
