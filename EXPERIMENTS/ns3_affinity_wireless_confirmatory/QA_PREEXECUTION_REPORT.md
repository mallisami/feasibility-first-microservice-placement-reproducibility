# ns-3/WiGig Packet-Level Confirmatory Experiment — Pre-Execution QA

**QA date:** 16 September 2026  
**Protocol:** `wireless-beyond-affinity-ns3-v1.1`  
**Outcome status:** no packet-level scientific outcome is pre-populated.

## Frozen-plan audit

- held-out graph seeds: **30** (`44001–44030`);
- methods: **3** (`Current`, `Affinity-Bytes`, `BPlus-Exact`);
- load targets: **2** (`0.50`, `1.25`);
- nested ns-3 RNG runs: **3** (`201–203`);
- total planned packet cells: **540**;
- B+ abstention graph-method-target rows: **2**, retained rather than excluded;
- independent packet-load anchor: **6 x 300 Mbps = 1800 Mbps**;
- Current configured aggregate offered rate: **900 Mbps** at 0.50 and **2250 Mbps** at 1.25;
- maximum configured stream across the complete frozen plan: **1194.222986 Mbps**;
- frozen per-stream guard: **1500 Mbps**.

## Pre-execution safeguards added in v1.1

- real six-stream `5 Mbps` packet smoke simulation before scientific cells;
- smoke RNG run `991001` and requirement of positive payload reception on all six streams;
- pinned upstream WiGig commit verification: `f3404236d05eb1da1cab80eec06c56ea8ab43f7d`;
- minimum **8 GiB** free on the results filesystem;
- **300 s** wall-clock timeout per scientific cell;
- failed/interrupted attempts are preserved and count toward the frozen two-attempt limit;
- stale Docker-container cleanup after timeout/interruption;
- frozen resume identity includes protocol/config/simulator source, canonical wireless trace, Kubernetes planner configuration/source, canonical B+ planner tree, and Docker image identities;
- saved plans are recomputed/checked and accepted cells are revalidated on resume;
- aggregate delivered fraction is computed from received bytes divided by configured offered bits over each stream's actual post-association active interval;
- re-analysis refreshes the run SHA-256 manifest before checksum verification.

## Offline QA completed in the packaging environment

- packet release structural verifier: **PASS**;
- packet automated tests: **18/18 passed**;
- packet scientific self-test: **PASS**;
- complete 540-cell offline planning/rate audit: **PASS**;
- Python source parsing and Bash syntax checking: **PASS** as part of final SSOT QA.

## Target-machine boundary

The packaging environment does not expose a Docker engine, so the custom WiGig C++ scratch program cannot be compiled or executed here. The target-machine `prepare` gate therefore compiles the program and executes the real six-stream packet smoke test **before** the first scientific cell. A compile, commit-identity, disk-space, Docker, or smoke failure stops before packet outcomes are generated.

No physical WiGig/60-GHz hardware is required or claimed.
