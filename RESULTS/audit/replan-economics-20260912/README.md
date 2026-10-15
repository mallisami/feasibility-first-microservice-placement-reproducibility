# Replan-economics audit

`replay.json` independently rebuilds all 12 saved S-E1 replan problems and
re-evaluates both saved placements using the current evaluator and unchanged
economic gate.  All recomputed gate values match the saved values to 1e-7.

For the representative persistent-degradation decision, the replay is:

```
current operating objective  10344.6000
candidate operating objective   903.9333
relocation cost               16248.0000
relocation uncertainty         2760.0000
net benefit                   -9567.3333
```

The repeated value is therefore not hard-coded arithmetic or a cached final
gate result.  It is structural: the old driver rebuilds a problem from a
fixed R2 traffic aggregate, maps each condition label to a fixed scenario,
uses a fixed 60-second objective window, fixed calibrated relocation terms,
and a fixed 300-second detector horizon.  Live shaping and application
measurements are recorded but are not supplied to `build_problem` before the
decision.  Thus, current/candidate placement and every objective/gate term
are recomputed, while telemetry, scenario severity, communication exposure,
CVaR exposure, and planning horizon are not fresh per replan.

This is a negative audit finding.  It rules out a hard-coded `-9567.33`, but
does not validate the old loop as a live-telemetry replan experiment.
