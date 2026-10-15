# Three new experiments: frozen run instructions

Target environment: Ubuntu VM (tested design target: 4 vCPU, 16 GB RAM). This folder is **self-contained for the planner-side code and dependencies**. E1 additionally builds ns-3/WiGig in Docker from the external source declared in its Dockerfile.

All three experiments are to be run and reported **regardless of outcome direction**. Do not tune thresholds, seeds, graph sizes, move budgets, or analysis rules after a science outcome is observed.

| | E1: packet-level persistent degradation | E2: larger-instance admission | E3: published scoring-rule replay |
|---|---|---|---|
| Main question | Do planner-over-budget placements show packet-delivery degradation in an independent ns-3/WiGig execution across all 150 controlled graphs? | Does avoidable inadmissibility persist at 12, 16 and 24 replicas with multiple nodes per rack? | Can a published network-aware node-scoring rule without shared-airtime admission also leave the declared admissible region? |
| Evidence type | packet-level construct/mechanism evidence | scale/generalization within the planning model | external-comparator / mechanism evidence |
| Needs | Docker; Python environment from `deps/requirements-lock.txt` | Python environment from `deps/requirements-lock.txt` | Python environment from `deps/requirements-lock.txt` |
| Science scope | 18 calibration + 2,061 science cells | 150 science graphs | 150 controlled graphs × declared loads and replay variants |
| Protocol | `E1_ns3_persistent_degradation/protocol/PD_ADMISSION_PROTOCOL.md` | `E2_scale_admission/PROTOCOL.md` | `E3_published_score_replay/PROTOCOL.md` |
| Important boundary | ns-3 construct evidence, not physical 60-GHz hardware calibration | a zero result at n=24 is conditional on the declared 3-move neighborhood | replay of the published node-scoring rule, not the authors' complete Kubernetes implementation |

E3's algorithm-level verification has now been completed against an author-uploaded full text **before execution**. See `E3_published_score_replay/FULLTEXT_RULE_VERIFICATION.md`. The replay adaptations remain prespecified and explicit.

## 0. Validate and freeze before any science run

Read all three protocols first. If a scientific design change is genuinely required, make it **before** creating the freeze manifest and before any science run.

Run:

```bash
python3 VERIFY_PACKAGE.py
bash FREEZE_PREEXECUTION.sh
```

`VERIFY_PACKAGE.py` checks script syntax, required files, bundled dependency hashes and the absence of pre-existing science results. `FREEZE_PREEXECUTION.sh` creates `PREEXECUTION_SHA256SUMS.txt` and refuses to overwrite an existing freeze file.

After `PREEXECUTION_SHA256SUMS.txt` exists, treat protocol/code/configuration files as frozen. Any unavoidable change must be documented explicitly and requires creation of a new package/freeze manifest before science execution.

## 1. Environment

```bash
sudo apt-get update
sudo apt-get install -y docker.io python3-venv tmux
sudo usermod -aG docker $USER
# log out and back in after changing the docker group
python3 -m venv ~/venv
source ~/venv/bin/activate
pip install -r deps/requirements-lock.txt
```

Use `tmux` so the runs survive an SSH interruption.

## 2. Recommended single-command execution

```bash
tmux new -s mape-newexp
bash RUN_ALL.sh 2>&1 | tee RUN_ALL.log
```

`RUN_ALL.sh` uses the 4-vCPU VM as follows:

1. validate the frozen package;
2. prepare/build/gate E1 in the background while E2 runs with three workers;
3. run E1 science with four workers after E2 finishes;
4. run E3 after E1;
5. run the post-run inventory checker.

The E1 and E2 science phases do not overlap.

## 3. Individual execution commands

### E1

```bash
cd E1_ns3_persistent_degradation
python3 tests/test_pipeline.py
bash scripts/run_all.sh --workers 4
```

- resumable: rerunning reuses accepted cells;
- do not alter a gate threshold after a failure;
- the offline synthetic pipeline test is plumbing only and is **not evidence**;
- science outputs live under `results/run-<timestamp>/` and operator records under `operator_logs/`.

### E2

```bash
cd E2_scale_admission
python3 run_scale.py run --workers 4
```

- resumable: solved graphs are skipped;
- non-science smoke seeds, if used, are timing/plumbing evidence only;
- science outputs are written under `results/`.

### E3

```bash
cd E3_published_score_replay
python3 run_score_replay.py run
```

- `FULLTEXT_RULE_VERIFICATION.md` records the pre-run full-text verification;
- `RULE_CHECK.md` maps the published rule to the implementation;
- the authors' complete Kubernetes scheduler/controller system is **not** being reproduced;
- primary and sensitivity variants are prespecified in `PROTOCOL.md`.

## 4. Interpretation rules

### E1

- **H1** concerns the admission contrast over all 150 graphs. Use exactly the prespecified bootstrap and one-sided Wilcoxon rules.
- **H2** compares packet delivery with planner utilization. If the declared `U=1` boundary does not align with packet behavior, narrow the manuscript accordingly; do not retune the threshold after seeing outcomes.
- E1 does not establish physical hardware/RF calibration.

### E2

- A zero avoidable-violation count means the mechanism did not appear at that size **under the declared search/move neighborhood**.
- For n=24, absence of a violation cannot be generalized beyond the fixed 3-move neighborhood.
- Record whether violations occur in ordinary rack-pair groups versus the multi-pair group.

### E3

- If the primary replay produces avoidable shared-airtime violations and the prespecified sensitivity variants agree qualitatively, the planning-model mechanism is not specific to Affinity-Bytes.
- If the replay produces none, report that result and keep the claim limited accordingly.
- E3 is planning-model evidence; it makes no application-performance or physical-RF claim about the published system.

## 5. What to return after the campaign

Upload the **whole experiment folder** after execution. At minimum it must contain:

- `PREEXECUTION_SHA256SUMS.txt`
- `RUN_ALL.log`
- `POSTRUN_INVENTORY.txt`
- `E1_ns3_persistent_degradation/results/`
- `E1_ns3_persistent_degradation/operator_logs/`
- `E2_scale_admission/results/`
- `E3_published_score_replay/results/`
- a short `DEVIATIONS.md` if anything departed from the frozen protocol (otherwise write `No deviations.`)

Do not delete null, mixed, unfavorable, failed-gate, or partial-run records before returning the package. They are part of the provenance trail.
