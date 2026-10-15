# Packet-Level ns-3/WiGig Affinity-vs-Wireless Confirmation

This is the second, **separately frozen** confirmation for the "value beyond communication affinity under wireless contention" mechanism. Run it **after** the Kubernetes confirmatory campaign, not concurrently on the same machine.

## Evidence boundary

The Kubernetes experiment uses real Kubernetes deployments with a deterministic shared-airtime emulator. This experiment provides a packet-level IEEE 802.11ad/WiGig cross-check using the pinned upstream Q-D `DenseScenario`.

No physical wireless hardware is required. The evidence boundary is simulation only; results must not be described as physical RF measurements.

The authoritative packet protocol is **v1.1**. Version 1.1 was frozen before any packet-level scientific outcome and strengthens the packet-load anchor, real packet smoke gate, resume provenance, timeout/interruption handling, and active-interval endpoint definition.

## Canonical dependencies

This experiment does not duplicate the planner or frozen wireless trace. It imports:

- `../../implementation/code/mape_cap_bplus/`
- `../k8s_affinity_wireless_confirmatory/src/live_confirmatory.py`
- `../../RESULTS/calibration/external/ns3_simulation_backed_traces.csv`
- canonical WiGig base-image recipe at `../../implementation/kubernetes/simulator/Dockerfile.ns3-wigig`

The authoritative protocol is `protocol/PACKET_LEVEL_PROTOCOL_FROZEN.md`.

## Frozen design

- 30 held-out graphs (`44001–44030`)
- Current, Affinity-Bytes, BPlus-Exact
- packet-load targets 0.50 and 1.25
- ns-3 RNG runs 201, 202, 203 nested within each graph-method-target
- 540 planned simulator cells
- fixed directed rack-pair -> STA mapping
- six-STA DenseScenario offered-load anchor: `6 x 300 Mbps = 1800 Mbps`
- Current aggregate configured offered rate: 900 Mbps at target 0.50 and 2250 Mbps at target 1.25
- one graph-specific load multiplier shared by all three methods within a graph/target
- maximum per-stream guard: 1500 Mbps
- primary endpoint: graph-level byte-weighted delivered offered-traffic fraction at target 1.25

The complete pre-execution plan has a maximum configured stream of approximately **1194.223 Mbps**, below the frozen 1500-Mbps guard.

## Mandatory pre-science gate

The launcher will not start the 540 scientific cells until it has:

1. verified the SSOT and packet release;
2. run the automated tests and scientific self-test;
3. reconstructed all 540 planned cells;
4. confirmed at least 8 GiB free on the results filesystem;
5. built/inspected the pinned WiGig images and verified commit `f3404236d05eb1da1cab80eec06c56ea8ab43f7d`;
6. compiled the custom scratch program;
7. run a **real six-stream 5-Mbps packet smoke simulation** with RNG 991001 and verified positive payload delivery on all six streams.

If this gate fails, no scientific packet cell begins.

## One command

Windows PowerShell from this directory:

```powershell
powershell -ExecutionPolicy Bypass -File .\RUN_NS3_CONFIRMATORY.ps1
```

From WSL/Linux:

```bash
bash ./RUN_NS3_CONFIRMATORY_WSL.sh
```

The first run may take additional time because the pinned `ns3-wigig:v0.5` base image is built from source if it is not already present. Internet access is required for that initial build.

## Resume and failure preservation

`results/CURRENT_RUN.txt` identifies the active campaign. Re-run the same command after an interruption.

- accepted cells are revalidated before reuse;
- saved plans are recomputed and checked before reuse;
- failed and interrupted attempts are retained and count toward the frozen two-attempt limit;
- stale Docker containers are removed after timeouts/interruption;
- source/config/protocol/canonical-input hashes and Docker image IDs must match the run's frozen provenance.

Do not delete `CURRENT_RUN.txt` or failed attempt directories to force a fresh outcome.

## Results

After completion:

- `results/<run-id>/PRIMARY_RESULT.json`
- `results/<run-id>/FINAL_REPORT.md`
- `results/<run-id>/graph_level_results.csv`
- `results/<run-id>/analysis_cells.csv`
- `results/<run-id>/SHA256SUMS.txt`

Explicit re-analysis refreshes `SHA256SUMS.txt` before checksum verification.
