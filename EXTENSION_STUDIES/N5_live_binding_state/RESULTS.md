# N5 results (pre-registered analysis per PROTOCOL_FROZEN.md)

Run: Azure VM, 2026-09-26 00:56–03:30 UTC. 100/100 cells accepted on first attempt, 0 failures.
Executed state = persistent-degradation for all 30 graphs. Host load average (1 min) mean 1.5, max 3.9 on 4 vCPU.
Raw data: `../vm_results_2026-09-26/N5/` (hash-verified). Analysis: `analyze_n5.py` -> `analysis/`.

## S1 (τ = 1.25, 20 graphs) — primary
| Method | mean sched. P95 (ms) | P95 at 3-s timeout | completion | exec. util. |
|---|---|---|---|---|
| Affinity-Bytes | 2380 | 15/20 | 0.901 | 1.27 |
| Affinity+Admission | 257 | 0/20 | 1.000 | 0.75 |
| MAPE-CAP-WS | 277 | 0/20 | 1.000 | 0.80 |

- (a) Admission effect, P95: −2123 ms [−2523, −1627], 20/20, Holm p = 4e−6. Completion +0.099 [+0.068, +0.132], 20/20.
- (b) Ranking effect, P95: +19.8 ms [+2.5, +41.9], 14/20 worse, Holm p = 0.040. Completion tied (1.000).

## S2 (τ = 1.00, 10 graphs) — descriptive
- Affinity-Bytes − Current: P95 +1758 ms [+1018, +2486], completion −0.076, 10/10.
- Affinity+Admission − Current: P95 −62 ms [−87, −37]; MAPE-CAP-WS − Current: −31 ms [−64, −1].

## Reading
Admission is what the application feels when the violated state is executed. Ranking inside the
admission set costs ~20 ms P95, because MAPE-CAP-WS sits closer to the airtime budget in the executed
state (queue wait +10 ms) and the planning delay model does not charge for queueing.
