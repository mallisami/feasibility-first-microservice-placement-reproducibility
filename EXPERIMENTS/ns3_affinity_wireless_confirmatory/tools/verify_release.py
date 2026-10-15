#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path

EXP = Path(__file__).resolve().parents[1]
REPO = EXP.parents[1]


def main() -> int:
    required = [
        EXP/'protocol'/'PACKET_LEVEL_PROTOCOL_FROZEN.md', EXP/'config'/'experiment.json',
        EXP/'src'/'ns3_confirmatory.py', EXP/'simulator'/'evaluate_bplus_affinity_dense.cc',
        EXP/'simulator'/'Dockerfile', REPO/'implementation'/'code'/'mape_cap_bplus',
        REPO/'EXPERIMENTS'/'k8s_affinity_wireless_confirmatory'/'src'/'live_confirmatory.py',
        REPO/'EXPERIMENTS'/'k8s_affinity_wireless_confirmatory'/'config'/'experiment.json',
        REPO/'implementation'/'kubernetes'/'simulator'/'Dockerfile.ns3-wigig',
        REPO/'RESULTS'/'calibration'/'external'/'ns3_simulation_backed_traces.csv',
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise SystemExit('missing required paths: '+repr(missing))
    cfg = json.loads((EXP/'config'/'experiment.json').read_text())
    assert cfg['protocol_id'] == 'wireless-beyond-affinity-ns3-v1.1'
    assert cfg['held_out_seeds'] == list(range(44001, 44031))
    assert cfg['methods'] == ['Current','Affinity-Bytes','BPlus-Exact']
    assert cfg['load_targets'] == [0.5,1.25]
    assert cfg['ns3_rng_runs'] == [201,202,203]
    assert cfg['reference_dense_sta_rate_mbps'] == 300.0
    assert cfg['reference_dense_num_stas'] == 6
    assert cfg['reference_dense_aggregate_mbps'] == 1800.0
    assert cfg['max_rate_mbps_per_stream'] == 1500.0
    assert cfg['cell_timeout_seconds'] == 300
    assert cfg['smoke_rng_run'] == 991001
    assert cfg['smoke_rate_mbps_per_stream'] == 5.0
    assert cfg['min_results_free_gib'] == 8.0
    assert cfg['wigig_commit'] == 'f3404236d05eb1da1cab80eec06c56ea8ab43f7d'
    assert len(cfg['rack_pair_to_sta']) == 6 and sorted(cfg['rack_pair_to_sta'].values()) == list(range(6))
    # No planner or trace copies are allowed inside the packet experiment.
    if list(EXP.rglob('mape_cap_bplus')):
        raise SystemExit('duplicate planner tree inside ns3 experiment')
    if list(EXP.rglob('ns3_simulation_backed_traces.csv')):
        raise SystemExit('duplicate wireless trace inside ns3 experiment')
    protocol = (EXP/'protocol'/'PACKET_LEVEL_PROTOCOL_FROZEN.md').read_text(encoding='utf-8')
    if 'Version 1.1 is a **pre-execution amendment**' not in protocol:
        raise SystemExit('v1.1 pre-execution amendment boundary is missing')
    src = (EXP/'src'/'ns3_confirmatory.py').read_text(encoding='utf-8')
    for token in ['aggregate_offered_bits_active_intervals','packet-smoke-','resume identity mismatch','interrupted.json','write_manifest(run_root)']:
        if token not in src:
            raise SystemExit(f'missing v1.1 execution safeguard: {token}')
    print('ns-3 confirmatory v1.1 release verification PASSED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
