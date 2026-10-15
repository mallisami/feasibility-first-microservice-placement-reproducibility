# Confirmatory Replicate Count Justification

**Date:** 2026-08-07
**Recommended replicates per cell:** 30

## Relocation pilot

- Pilot n = 4
- ready_seconds: mean = 4.062, SD = 0.690, CV = 0.170
- MDE (25% of mean): 1.016s
- Required replicates (relocation): 4

## Optimization effect sizes (from local campaign)

| Comparison | Relative improvement | Est. SD | MDE | Required n |
|---|---|---|---|---|
| BPlus vs Current | 46.8% | 5384.7 | 8394.3 | 4 |
| BPlus vs TrafficOnly-MAPE-CAP | 2.9% | 2951.8 | 284.6 | 845 |
| BPlus vs DeterministicNetworkAware | 24.8% | 3812.8 | 3154.4 | 12 |

## Decision

**30 replicates per cell** in a paired design.

Total confirmatory runs: 1200 (8 cells x 5 methods x 30 replicates).

## Power classification of comparisons

| Comparison | Status | Notes |
|---|---|---|
| BPlus vs Current | **Confirmatory** | Large effect (46.8%), powered at n=4 |
| BPlus vs DeterministicNetworkAware | **Confirmatory** | Moderate effect (24.8%), powered at n=12 |
| BPlus vs TrafficOnly-MAPE-CAP | **Exploratory** | Small effect (2.9%), requires n=845; underpowered at n=30 |

The BPlus vs TrafficOnly comparison must be reported as exploratory — the
observed effect size is too small relative to estimated variance to achieve
80% power at the chosen replicate count. The manuscript must not claim a
statistically significant BPlus advantage over TrafficOnly unless the
confirmatory data actually supports it.

## Assumptions and limitations

- Run-level SD estimated at 15% of baseline objective (conservative).
- MDE set at 50% of observed local-campaign effect size.
- Paired design (same workload/network trace across methods) reduces variance;
  actual required n may be lower if within-pair correlation is high.
- Pilot relocation variance is from a single image type (cached, stateless echo).
- alpha = 0.05, power = 0.80, two-sided paired t-test.
- The small BPlus-vs-TrafficOnly effect may increase under degraded/conflict
  conditions where B+ features are most relevant.
