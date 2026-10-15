# Results index

This directory contains the raw and derived result families for the MAPE-CAP-WS reproducibility package. Historical experiment results are retained, and post-manuscript studies are additive.

## Completed post-manuscript evidence

### Shared-airtime packet-level construct validation — 30 September 2026

`post-manuscript/shared-airtime-boundary-20260930/run-20260930T163137Z/`

- 18/18 calibration cells accepted;
- 108/108 science cells accepted;
- all accepted on attempt 1;
- mean delivered fractions 0.943939 / 0.885492 / 0.751413 for U=0.8 / 1.0 / 1.2;
- paired 1.2 - 0.8 mean difference -0.192527, 95% CI [-0.215877, -0.173116];
- 12/12 traffic shapes lower at U=1.2.

### Three-host Kubernetes N5 replication — 1 October 2026

`post-manuscript/multihost-k3s-n5-20261001/run-20261001T151036Z/`

- six-cell engineering pilot passed;
- 60/60 science cells accepted on first attempt;
- every cell used at least two Kubernetes/VM hosts; 41/60 used all three;
- Affinity-Bytes mean TA-P95 2379.56 ms, completion 0.901425;
- Affinity-Bytes+Admission mean TA-P95 258.61 ms, completion 1.000000;
- MAPE-CAP-WS mean TA-P95 279.28 ms, completion 1.000000;
- admission effect -2120.95 ms, 95% CI [-2521.07, -1625.25];
- MAPE-CAP-WS vs admission +20.66 ms, 95% CI [3.33, 42.21].

The multi-host run supports persistence of the binding-state admission effect under host separation; it is not physical 60-GHz validation.

## Canonical RQ1 extension & validation campaigns

Use `../EXTENSION_STUDIES/N2N3_admission_vs_ranking/` and `../EXTENSION_STUDIES/N2c_capacity_comparators/` for the canonical admission/ranking/mechanism analyses, and `../EXPERIMENTS/E1_E2_E3_validation_campaigns/` for the completed E1, E2, and E3 validation campaigns.
