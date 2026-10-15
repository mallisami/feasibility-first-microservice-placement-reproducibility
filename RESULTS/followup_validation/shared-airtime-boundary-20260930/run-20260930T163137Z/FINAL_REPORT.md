# Final report — ns-3 shared-airtime boundary validation

Protocol: `mape-cap-ws-ns3-shared-airtime-boundary-v1.1`

## Primary result
Mean paired delivery difference (U=1.20 minus U=0.80): **-0.192527** (95% bootstrap CI -0.215877 to -0.173116; n=12 traffic shapes).

Shapes with lower delivery at U=1.20 than U=0.80: **12/12**.

## Delivery by target utilization
- U=0.8: mean D=0.943939, median=0.999988, 95% bootstrap CI [0.898714, 0.982026].
- U=1.0: mean D=0.885492, median=0.966693, 95% bootstrap CI [0.812700, 0.952845].
- U=1.2: mean D=0.751413, median=0.809467, 95% bootstrap CI [0.694886, 0.803339].

## Secondary threshold classification
Observed feasible is frozen descriptively as mean delivered fraction >= 0.95. Confusion counts: {'TP': 14, 'FP': 10, 'FN': 0, 'TN': 12}.

## Evidence boundary
This is packet-level construct validation in a pinned IEEE 802.11ad/WiGig simulator. It is not a physical RF deployment and does not independently calibrate a real data-center 60-GHz channel.

## Interpretation rule
A negative primary contrast with degradation concentrated above U=1 supports the aggregate shared-airtime admission construct. A null or positive contrast does not. No post-hoc parameter tuning is permitted.
