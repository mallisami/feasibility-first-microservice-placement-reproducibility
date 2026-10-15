# Multi-host Kubernetes validation result

This report is generated only after all 60 frozen science cells are present.

## Run quality

- Accepted cells: **60/60**
- Failed attempts: **0**
- Every cell used at least two Kubernetes/VM hosts: **True**
- Kubernetes/VM hosts used per cell: **2–3**

## Method summaries

| method                   |   n |   p95_mean |   p95_median |   compl_mean |   compl_min |   p50_mean |   p99_mean |   qwait_mean |   exec_util_mean |   exec_util_max |   hosts_used_min |   hosts_used_max |   rollout_mean_s |
|:-------------------------|----:|-----------:|-------------:|-------------:|------------:|-----------:|-----------:|-------------:|-----------------:|----------------:|-----------------:|-----------------:|-----------------:|
| Affinity-Bytes           |  20 |   2379.56  |     3000     |     0.901425 |    0.748214 |   216.441  |   2635.34  |     420.539  |         1.2694   |        1.77412  |                2 |                3 |          35.3115 |
| Affinity-Bytes+Admission |  20 |    258.612 |      257.011 |     1        |    1        |    73.5972 |    327.616 |      40.6601 |         0.753343 |        0.993099 |                2 |                3 |          34.7647 |
| MAPE-CAP-WS              |  20 |    279.276 |      283.761 |     1        |    1        |    78.4689 |    356.636 |      50.2117 |         0.799156 |        0.993099 |                2 |                3 |          36.1189 |

## Frozen primary contrasts

| metric               | contrast                                  |   n |   mean_a |      mean_b |     mean_diff |   median_diff |         ci_lo |        ci_hi |   n_pos |   n_neg |   n_zero |   wilcoxon_p |     holm_p | role       |
|:---------------------|:------------------------------------------|----:|---------:|------------:|--------------:|--------------:|--------------:|-------------:|--------:|--------:|---------:|-------------:|-----------:|:-----------|
| sched_p95_ms         | Affinity-Bytes+Admission - Affinity-Bytes |  20 |  258.612 | 2379.56     | -2120.95      | -2720.97      | -2521.07      | -1625.25     |       0 |      20 |        0 |  1.90735e-06 | 3.8147e-06 | primary    |
| sched_p95_ms         | MAPE-CAP-WS - Affinity-Bytes+Admission    |  20 |  279.276 |  258.612    |    20.6638    |     5.7372    |     3.3257    |    42.2099   |      14 |       6 |        0 |  0.0295753   | 0.0295753  | primary    |
| scheduled_completion | Affinity-Bytes+Admission - Affinity-Bytes |  20 |    1     |    0.901425 |     0.0985748 |     0.0848779 |     0.0675158 |     0.131451 |      20 |       0 |        0 |  1.90735e-06 | 3.8147e-06 | co-primary |
| scheduled_completion | MAPE-CAP-WS - Affinity-Bytes+Admission    |  20 |    1     |    1        |     0         |     0         |     0         |     0        |       0 |       0 |       20 |  1           | 1          | co-primary |

## Interpretation boundary

This follow-up tests whether the original N5 S1 application-level admission/ranking behavior persists when the three logical racks are mapped to three distinct Kubernetes hosts. It is not physical 60-GHz validation and it does not re-estimate planner capacity from the smaller VMs.

## Original N5 primary CSV retained for comparison

```csv
stratum,metric,contrast,n,mean_a,mean_b,mean_diff,median_diff,ci_lo,ci_hi,n_pos,n_neg,n_zero,wilcoxon_p,holm_p,role
S1,sched_p95_ms,Affinity-Bytes+Admission - Affinity-Bytes,20,256.9579003999024,2379.5990136999535,-2122.641113300051,-2721.395193000262,-2522.8619417850564,-1627.2515573236672,0,20,0,1.9073486328125e-06,3.814697265625e-06,primary
S1,sched_p95_ms,MAPE-CAP-WS - Affinity-Bytes+Admission,20,276.74744359992474,256.9579003999024,19.789543200022308,3.0318844999328576,2.531153701135054,41.92036558987354,14,6,0,0.039989471435546875,0.039989471435546875,primary
S1,scheduled_completion,Affinity-Bytes+Admission - Affinity-Bytes,20,1.0,0.9008579412913373,0.09914205870866263,0.0848778686271815,0.06819758099295453,0.1319057654715856,20,0,0,1.9073486328125e-06,3.814697265625e-06,co-primary
S1,scheduled_completion,MAPE-CAP-WS - Affinity-Bytes+Admission,20,1.0,1.0,0.0,0.0,0.0,0.0,0,0,20,1.0,1.0,co-primary
```
