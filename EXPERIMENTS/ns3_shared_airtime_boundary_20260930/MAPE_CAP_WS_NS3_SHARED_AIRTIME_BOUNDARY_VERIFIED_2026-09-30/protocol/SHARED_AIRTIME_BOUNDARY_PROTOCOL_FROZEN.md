# Frozen protocol: independent packet-level shared-airtime boundary validation

**Protocol ID:** `mape-cap-ws-ns3-shared-airtime-boundary-v1.1`  
**Frozen:** 2026-09-30, before any outcome from this new experiment.

## Scientific question

Does a planner-style aggregate airtime quantity predict packet-level service degradation when several directional traffic aggregates independently contend for a common IEEE 802.11ad resource?

This is a **construct-validation experiment**, not a physical 60-GHz deployment and not an RF-calibration claim.

## Independence rule

The ns-3 program is never given `planned_feasible`, the planner's previously computed utilization, or an instruction to drop traffic when a planner threshold is exceeded. It receives only:

1. six offered traffic rates;
2. the frozen DenseScenario wireless environment; and
3. the environmental shared-resource fraction (25% of the DTI).

Packet delivery is determined by the pinned WiGig MAC/PHY simulator.


## Planner-to-simulator resource alignment

The 25% shared-resource fraction is taken directly from the frozen planner inputs rather than chosen for this extension. In `ns3_simulation_backed_traces.csv`, the `conflict-dense` scenario assigns all six directed rack-pair links to the single conflict group `cg-shared` with a **15 s** airtime budget. The planner decision window is **60 s**, so the normalized group budget is **15/60 = 0.25**. The experiment therefore maps the same six directional traffic aggregates to one shared ns-3 CBAP occupying 25% of the DTI. The exact trace file and a machine-readable derivation are bundled under `canonical_inputs/model/`.

Operationally, the six directed demand components are mapped one-to-one to six calibrated WiGig STA-to-AP streams. This preserves the six-member shared-resource structure, traffic-shape heterogeneity, and independently measured per-stream service rates, but it does **not** reproduce the literal three-rack endpoint geometry or bidirectional transmitter/receiver identities. The experiment therefore validates the aggregate-airtime construct, not a complete rack-level RF topology.

This is a construct-level mapping of an aggregate scheduler resource to an independently executed WiGig MAC/PHY resource. It is not a claim that a real 60-GHz deployment has a universal 25% duty cycle.

## Pre-execution engineering gates

Before any scientific cell is accepted, the runner verifies the pinned image/commit, builds the custom simulator, checks the output schema, and performs two packet-level engineering checks. First, a low-rate six-stream smoke run must complete under the 25% shared CBAP. Second, a saturated single stream is run with full-DTI access and with the 25% CBAP using RNG run **991102**. The limited/full achieved-throughput ratio must lie in the frozen interval **[0.05, 0.60]**. This is not a scientific endpoint; it only verifies that the explicit CBAP allocation materially limits transmission time rather than silently leaving the remainder of the DTI usable.

The pinned WiGig implementation determines `CBAP_Only` from whether an allocation list is empty. With an explicit CBAP allocation, `StartDataTransmissionInterval()` schedules the listed allocation periods rather than opening the complete DTI as a default CBAP. The runtime duty-effect gate independently checks that this behavior is effective in the built image.

Traffic sources have a frozen absolute start time of **2.0 s**. Immediately before that start, the simulator aborts unless all six stations are associated, the shared resource has been configured, and the most recent all-associated state has persisted for at least **250 ms**. Sources then remain offered through the fixed measurement interval; later deassociation is retained as service loss rather than used to shorten the offered-load denominator.

## Phase A: solo-link calibration

For each of the six frozen DenseScenario STA positions, run that stream alone at **6000 Mbps** with the original full-DTI behavior (`dutyFraction=1.0`). Use RNG runs **301, 302, 303**. The median achieved application throughput is the independently measured solo goodput `g_i` for that position.

This contributes 6 x 3 = **18 calibration cells**. Calibration is accepted only if every position has positive throughput and the offered rate is demonstrably saturating (median delivered fraction < 0.98).

## Phase B: frozen traffic-shape selection

The candidate shapes are the 30 previously frozen held-out **Affinity-Bytes** placements from the completed packet experiment at target 1.25. Selection is based only on the six-direction traffic shape, never on any new packet result.

For each candidate, normalize the six `raw_pair_rates_mbps` values and compute the Herfindahl-Hirschman concentration index (HHI). Sort by `(HHI, seed)` and select 12 evenly spaced order-statistic positions. The selected seeds are:

44002, 44029, 44007, 44027, 44023, 44003, 44014, 44028, 44012, 44020, 44021, 44019.

This spans diffuse 5-6-direction shapes and concentrated 2-direction shapes. The exact source plan files and SHA-256 hashes are bundled under `canonical_inputs/source_plans/`.

## Phase C: shared-resource boundary sweep

The simulator exposes one static shared CBAP equal to **25% of the DTI**. All six stream positions contend within that common resource.

For each frozen traffic shape and each target normalized utilization ratio `rho` in **0.8, 1.0, 1.2**, rates are scaled after calibration so that:

`(sum_i rate_i / g_i) / 0.25 = rho`.

The three science RNG runs are **401, 402, 403**.

Total science cells: 12 shapes x 3 utilization levels x 3 RNG runs = **108 cells**.

The runner randomizes science-cell execution order using the frozen seed `20261001`.

## Endpoints and independent unit

Primary packet endpoint: aggregate delivered offered-traffic fraction

`D = sum_i achieved_mbps_i / sum_i offered_mbps_i`, clipped to [0,1].

The independent statistical unit is the **traffic shape**. The three ns-3 RNG runs are averaged within each shape/utilization cell before inference.

### Primary contrast

Paired shape-level difference:

`mean(D at rho=1.20) - mean(D at rho=0.80)`.

Report the mean paired difference and a 95% percentile bootstrap interval over the 12 traffic shapes.

### Supporting summaries

- shape-level mean D and bootstrap 95% interval at rho = 0.8, 1.0, 1.2;
- number of shapes with D(1.2) < D(0.8);
- continuous delivery deficit `1-D`;
- secondary descriptive classification using the pre-frozen observed-feasible threshold D >= 0.95.

## Interpretation/falsification

Evidence supports the aggregate-airtime construct only if packet-level service degrades as normalized aggregate utilization moves above the boundary. Perfect classification is **not** required.

If delivery does not deteriorate, deteriorates in the opposite direction, or only does so after post-hoc threshold/parameter changes, the experiment does **not** validate the admission boundary. Do not retune the protocol to force agreement.

## No post-hoc changes

After scientific execution begins, do not change selected shapes, duty fraction, utilization levels, RNG runs, primary endpoint, statistical unit, or primary contrast. Engineering repairs are permitted only when they correct a demonstrable implementation failure without looking at scientific outcomes; any such repair must be documented and the affected campaign restarted or handled according to a written amendment.
