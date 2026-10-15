# Pre-execution QA report — verified release

**Protocol:** `mape-cap-ws-ns3-shared-airtime-boundary-v1.1`  
**Status:** static + orchestration QA passed; real Docker/WiGig compilation remains a mandatory on-machine gate before any scientific cell.

## Defects found and corrected during adversarial release audit

1. **Protected ns-3 application lifecycle calls** — the initial candidate directly called `StartApplication()` / `StopApplication()`, which are protected in the pinned ns-3 `Application` API. The verified release uses preregistered `ApplicationContainer::Start/Stop` times instead.
2. **End-of-run association filter** — the initial parser required all six STAs to remain associated at run end, which could discard genuine service failures. The verified release gates association only before traffic begins; later deassociation remains part of packet delivery.

## Frozen traffic-start guard

- Source start: **2.0 s** simulation time.
- Required lead: all six stations associated for at least **250 ms** before source start.
- Shared CBAP/full-DTI resource must already be configured.
- If any condition fails, the simulator aborts before the scientific measurement.
- After source start, offered traffic continues to the fixed stop time; later deassociation is not used to shorten the denominator.

## Model alignment verified

The bundled frozen planner trace shows `conflict-dense` assigns all six directed rack-pair links to `cg-shared` with a 15 s budget in a 60 s decision window. Therefore `shared_dti_fraction = 15/60 = 0.25`. Exact trace/config/planner-source snapshots and hashes are bundled under `canonical_inputs/model/`.

The six directed demand components are mapped one-to-one to six calibrated STA-to-AP WiGig streams sharing one CBAP. This preserves the six-member aggregate conflict group and per-stream heterogeneity; it does not reproduce literal three-rack/bidirectional RF geometry.

## Static QA passed

- 12 frozen traffic shapes; source-plan hashes verified.
- 18 calibration cells and 108 science cells by construction.
- Python syntax and release self-test pass.
- Bash syntax passes.
- Simulator source contains no `planned_feasible` or `worst_conflict_utilization` term.
- Simulator source contains no direct `StartApplication()` / `StopApplication()` invocation.
- Explicit `AllocateCbapPeriod` and pre-traffic `TrafficStartGuard` are present.
- Planner-model alignment snapshots/hashes verified.
- Randomized science plan is deterministic from the frozen run-order seed.
- Resume behavior is idempotent for accepted cells.

## End-to-end mock orchestration QA

The actual runner was executed against a deterministic mock Docker/ns-3 backend implementing the same CSV interfaces. It completed:

- prepare/smoke/duty gate;
- 18/18 calibration cells;
- 108/108 randomized science cells;
- analysis, bootstrap output, report generation, and SHA manifest;
- a second `run` invocation with accepted-cell reuse.

This validates orchestration, file paths, schemas, analysis, and resume semantics. It does **not** substitute for compilation/execution of the real WiGig simulator.

## Mandatory real-runtime gate

This environment has no Docker daemon, so the actual pinned WiGig C++ program cannot be compiled/run here. On the execution machine, `prepare()` therefore remains mandatory and refuses to begin science unless all of the following pass:

1. Docker available;
2. base image resolves to pinned commit `f3404236d05eb1da1cab80eec06c56ea8ab43f7d`;
3. custom simulator Docker build succeeds;
4. simulator help exposes `dutyFraction`, `trafficStartSeconds`, and `minimumAssociationLeadMs`;
5. six-stream packet smoke succeeds;
6. 25%-DTI duty-effect gate produces limited/full throughput ratio in frozen interval `[0.05, 0.60]`.

No scientific result should be used unless this real-runtime gate passes.
