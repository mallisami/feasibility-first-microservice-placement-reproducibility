# N4 results (descriptive analysis per PROTOCOL_FROZEN.md)

Run: Azure VM, 2026-09-26 03:30–05:31 UTC. 280/280 rows. One Exact row = failure (n=50, seed 105:
generated starting placement exceeds CPU capacity on node-1-0; rejected by input validation; LNS arms repaired it).
Raw data: `../vm_results_2026-09-26/N4/`. Analysis: `analyze_n4.py` -> `analysis/`.

- Exact (30 s): proves 10/10 up to n=16; 7/10 at 20; 2/10 at 24; 1/10 at 32; 0 from 40.
  Median MIP gap 11% (24), 31% (32), 77% (40), 76% (50), 98% (75, 100). No incumbent on 5/10 (75), 8/10 (100).
- LNS (published config) median certified gap: 0% (10, 12), 3.1% (16), 0.5% (20); max per instance 14–45%.
- LNS beats time-limited exact incumbent: 7/9 at 32, 10/10 at 40, 9/9 at 50 (uncertified).
- Q3 (did pre-search init cause the R8 stall?): **No.** LNS-noinit worse than LNS-R8config on 10/10 at
  n=40 and 10/10 at n=50 (median objective +15%, +28%; Wilcoxon p = 0.002 each). No difference at n ≤ 32.
  At 40–50 the R8 config accepts a median of 0 neighbourhood moves: the improvement comes from the initial local search.
- Paper claim updated: certified optimality up to ~16 replicas within 30 s (was ~12 under 10 s).
