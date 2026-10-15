# Gate-3 Statistical Qualification — Multi-Scenario Weighted Composite

**Date:** 2026-09-23  
**Applies to:** `MULTISCENARIO_WEIGHTED_COMPOSITE_PROTOCOL_FROZEN.md`  
**Status:** append-only interpretation qualification; the frozen protocol is not modified.

The historical protocol remains part of the provenance record and correctly records the endpoint, pilot gate, execution sequence, and originally stated interpretation rule. Subsequent Gate-3 review identified two inference boundaries that must accompany publication-facing interpretation:

1. The full 30-graph campaign was executed only after a favorable six-graph pilot gate, and those six pilot graphs recur in the final 30-graph sample. Consequently, the reported full-sample one-sided Wilcoxon `p=0.0196` is retained as the historical calculation but is not treated as a conventional fixed-design confirmatory p-value.
2. The three source weights (`0.10`, `0.15`, `0.10`; normalized to approximately `0.286`, `0.429`, `0.286`) are frozen design/model weights from the effective-state library. They are not empirically estimated occurrence probabilities from a physical wireless data center.

A read-only sensitivity on the 24 graphs not used in the pilot gate (seeds 44007--44030) gives mean MAPE-CAP-WS minus Affinity composite completion `+0.0038686`, 7 wins / 14 ties / 3 losses, bootstrap 95% CI `[-0.0062477,+0.0137924]`, and one-sided Wilcoxon `p=0.069707`. The favorable mean direction persists, but this fresh post-pilot subset does not independently meet the conventional 0.05 signed-rank threshold.

Scenario-specific mean paired differences over all 30 graphs are:

- conflict dense: `-0.0111135`
- partial blockage: `+0.0030555`
- persistent degradation: `+0.0259964`

Thus the weighted effect is heterogeneous across states and is strongest under persistent degradation. Fixed scenario order (conflict dense -> partial blockage -> persistent degradation) also means scenario-specific differences can contain temporal/carryover effects.

Publication-facing wording should therefore describe the multi-scenario campaign as **exploratory, directionally supportive evidence over the evaluated weighted state set**, not as independent confirmation of universal or population-level application superiority.

Reanalysis script and machine-readable outputs: `ANALYSIS/gate3_multiscenario_sensitivity.py` and `ANALYSIS/derived/gate3_multiscenario/`.
