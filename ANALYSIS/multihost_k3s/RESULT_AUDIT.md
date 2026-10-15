# MAPE-CAP-WS Multi-host Kubernetes Result Audit

**Run:** `run-20261001T151036Z`  
**Protocol:** `mape-cap-ws-multihost-k3s-n5-s1-v1.1`

## Audit verdict

**PASS — the completed run provides genuine three-host Kubernetes replication of the original N5 S1 admission/ranking result.**

This result addresses the earlier single-VM Kubernetes limitation. It does **not** constitute physical 60-GHz validation and should not be described as such.

## Execution integrity

- Frozen science matrix: 20 original N5 S1 graphs × 3 methods = **60 science cells**
- Pilot cells: **6**
- Accepted science cells: **60/60**
- Failed/retried science attempts: **0**
- Result archive SHA-256 manifest: **82/82 entries verified**
- All raw `result.json` records reproduce the released analysis CSVs to floating-point precision
- All requested rack-level placements exactly matched observed pod-node placement
- Every science cell used at least **2 distinct Kubernetes/VM hosts**; 41/60 used all 3
- No MemoryPressure, DiskPressure, or PIDPressure events were recorded
- Maximum observed node CPU utilization: rack-a 5%, rack-b 56%, rack-c 3%
- Maximum observed node memory utilization: rack-a 9%, rack-b 60%, rack-c 6%
- Full science log contains no `ERROR`, `FATAL`, `Traceback`, or exception records

## Three-host identity

The run recorded three distinct Kubernetes nodes and three distinct host `/etc/machine-id` SHA-256 digests:

- `rack-a`: 172.16.0.4
- `rack-b`: 172.16.0.7
- `rack-c`: 172.16.0.8

All were Ready, Linux/amd64, kubelet `v1.33.1+k3s1`.

Executed node resources:

- rack-a: **4 vCPU, 15.9 GiB**
- rack-b: **4 vCPU, 16.0 GiB**
- rack-c: **2 vCPU, 7.9 GiB**

The run therefore supports **three distinct VM/OS-backed Kubernetes hosts**, not a claim that Azure placed the VMs on three different underlying physical servers.

## Method-level results

| Method | Mean TA-P95 | Mean scheduled completion | Mean queue wait |
|---|---:|---:|---:|
| Affinity-Bytes | 2379.56 ms | 0.901425 | 420.54 ms |
| Affinity-Bytes+Admission | 258.61 ms | 1.000000 | 40.66 ms |
| MAPE-CAP-WS | 279.28 ms | 1.000000 | 50.21 ms |

## Prespecified primary contrasts

### Admission effect

Affinity-Bytes+Admission minus Affinity-Bytes:

- Mean TA-P95 difference: **−2120.95 ms**
- 95% bootstrap CI: **[−2521.07, −1625.25] ms**
- Lower TA-P95 on **20/20** graphs
- Holm-adjusted Wilcoxon p: **3.81×10⁻⁶**
- Scheduled-completion difference: **+0.098575**
- 95% bootstrap CI: **[+0.067516, +0.131451]**
- Completion improved on **20/20** graphs

### Ranking effect after admission

MAPE-CAP-WS minus Affinity-Bytes+Admission:

- Mean TA-P95 difference: **+20.66 ms**
- 95% bootstrap CI: **[+3.33, +42.21] ms**
- MAPE-CAP-WS higher on **14/20** graphs
- Holm-adjusted Wilcoxon p: **0.0296**
- Both methods achieved **1.000 scheduled completion**

This confirms the paper's mechanism interpretation: the large application-level effect is due to **shared-airtime admission**, while risk-aware ranking changes the within-admitted-region trade-off and is not a universal latency improvement.

## Replication against original single-host N5 S1

The multi-host estimates are extremely close to the original single-host results:

| Quantity | Original N5 | Multi-host | Change |
|---|---:|---:|---:|
| Affinity-Bytes mean TA-P95 | 2379.60 ms | 2379.56 ms | −0.04 ms |
| Admission mean TA-P95 | 256.96 ms | 258.61 ms | +1.65 ms |
| MAPE-CAP-WS mean TA-P95 | 276.75 ms | 279.28 ms | +2.53 ms |
| Admission effect | −2122.64 ms | −2120.95 ms | +1.69 ms |
| MAPE vs admission | +19.79 ms | +20.66 ms | +0.87 ms |
| Affinity completion | 0.900858 | 0.901425 | +0.000567 |
| Admission completion | 1.000000 | 1.000000 | 0 |
| MAPE-CAP-WS completion | 1.000000 | 1.000000 | 0 |

The core application result therefore persists under genuine host separation.

## Claim boundary

Supported:

> The binding-state N5 admission/ranking result was replicated on a Kubernetes deployment spanning three distinct VM/OS-backed hosts, with one Kubernetes node mapped to each logical rack.

Not supported:

> Three independent physical 60-GHz racks were validated.

> The shared-airtime abstraction is a measured physical RF capacity law.

> MAPE-CAP-WS universally improves latency over admission-matched affinity.

