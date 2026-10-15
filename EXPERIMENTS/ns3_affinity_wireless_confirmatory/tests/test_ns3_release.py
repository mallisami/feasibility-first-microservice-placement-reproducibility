from __future__ import annotations
import json, math, sys
from pathlib import Path
import pandas as pd
import pytest

EXP = Path(__file__).resolve().parents[1]
REPO = EXP.parents[1]
sys.path.insert(0, str(EXP/'src'))
sys.path.insert(0, str(REPO/'EXPERIMENTS'/'k8s_affinity_wireless_confirmatory'/'src'))
sys.path.insert(0, str(REPO/'implementation'/'code'))
import ns3_confirmatory as nc


def test_01_frozen_counts():
    c = nc.CFG
    assert len(c['held_out_seeds']) == 30
    assert len(c['methods']) == 3
    assert len(c['load_targets']) == 2
    assert len(c['ns3_rng_runs']) == 3
    assert 30*3*2*3 == 540


def test_02_no_seed_overlap_with_prior_generated_confirmation():
    prior = set(range(11001,11051)) | set(range(22001,22051)) | set(range(33001,33051))
    assert not prior.intersection(nc.CFG['held_out_seeds'])


def test_03_pair_mapping_is_bijective():
    assert set(nc.PAIR_TO_STA) == {'rack-a>rack-b','rack-b>rack-a','rack-a>rack-c','rack-c>rack-a','rack-b>rack-c','rack-c>rack-b'}
    assert sorted(nc.PAIR_TO_STA.values()) == list(range(6))


def test_04_self_test_and_rate_guard():
    r = nc.self_test()
    assert r['passed']
    assert r['protocol_id'] == 'wireless-beyond-affinity-ns3-v1.1'
    assert r['max_stream_mbps'] <= nc.CFG['max_rate_mbps_per_stream']
    assert r['min_active_stream_mbps'] > 0
    assert math.isclose(r['max_stream_mbps'], 1194.2229858799801, rel_tol=1e-10)
    # Corrected 2026-09-20: abstention fallback to resource_greedy on infeasible seeds yields 2835.59 Mbps max total
    assert math.isclose(r['max_total_offered_mbps'], 2835.5923000461985, rel_tol=1e-10)


def test_05_current_anchor_is_900_and_2250_mbps():
    for target, expected in [(0.5,900.0),(1.25,2250.0)]:
        for seed in (44001, 44007, 44030):
            p = nc.make_cell_plan(seed,target)
            assert math.isclose(p['methods']['Current']['total_offered_mbps'], expected, rel_tol=1e-10)


def test_06_same_graph_multiplier_applies_to_all_methods():
    p = nc.make_cell_plan(44001,1.25)
    mult = p['load_anchor']['common_graph_load_multiplier']
    for m in nc.CFG['methods']:
        raw = p['methods'][m]['raw_pair_rates_mbps']
        scaled = p['methods'][m]['rates_mbps']
        assert all(math.isclose(b, a*mult, rel_tol=1e-12, abs_tol=1e-10) for a,b in zip(raw,scaled))


def test_07_reference_anchor_is_independent_dense_load():
    c = nc.CFG
    assert c['reference_dense_sta_rate_mbps'] == 300.0
    assert c['reference_dense_num_stas'] == 6
    assert c['reference_dense_aggregate_mbps'] == 1800.0


def test_08_bplus_abstention_is_not_excluded():
    found=[]
    for seed in nc.CFG['held_out_seeds']:
        p=nc.make_cell_plan(seed,1.25)
        if p['methods']['BPlus-Exact']['planner_abstained']:
            found.append(seed)
            assert p['methods']['BPlus-Exact']['placement']
            assert len(p['methods']['BPlus-Exact']['rates_mbps'])==6
    assert len(found)==2


def test_09_custom_source_has_machine_summary_and_per_sta_rates():
    s=(EXP/'simulator'/'evaluate_bplus_affinity_dense.cc').read_text()
    assert 'ratesMbpsCsv' in s
    assert 'packet_summary.csv' in s
    assert 'GetTotalRx' in s


def test_10_custom_source_tracks_actual_active_intervals():
    s=(EXP/'simulator'/'evaluate_bplus_affinity_dense.cc').read_text()
    assert 'activeStartByNode' in s
    assert 'activeSecondsByNode' in s
    assert 'firstStartSecondsByNode' in s


def test_11_validator_uses_byte_weighted_active_intervals(tmp_path):
    # Same configured Mbps, unequal active intervals: the aggregate must be bits/bits,
    # not the unweighted mean of per-stream delivered fractions.
    df=pd.DataFrame([
        {'sta_index':0,'configured_mbps':10.0,'start_time_seconds':0.5,'active_seconds':2.0,'rx_bytes':1250000,'achieved_mbps':5.0,'delivered_fraction':0.5},
        {'sta_index':1,'configured_mbps':10.0,'start_time_seconds':2.5,'active_seconds':0.5,'rx_bytes':562500,'achieved_mbps':9.0,'delivered_fraction':0.9},
    ])
    p=tmp_path/'packet_summary.csv'; df.to_csv(p,index=False)
    r=nc.validate_summary(p,[10.0,10.0,0,0,0,0])
    expected=(1250000*8+562500*8)/(10e6*2.0+10e6*0.5)
    assert math.isclose(r['aggregate_delivered_fraction'], expected, rel_tol=1e-12)
    assert not math.isclose(r['aggregate_delivered_fraction'], (0.5+0.9)/2)


def test_12_zero_goodput_is_valid_scientific_outcome(tmp_path):
    df=pd.DataFrame([{'sta_index':0,'configured_mbps':5.0,'start_time_seconds':0.5,'active_seconds':2.0,'rx_bytes':0,'achieved_mbps':0.0,'delivered_fraction':0.0}])
    p=tmp_path/'packet_summary.csv'; df.to_csv(p,index=False)
    r=nc.validate_summary(p,[5.0,0,0,0,0,0])
    assert r['aggregate_delivered_fraction']==0.0


def test_13_smoke_gate_requires_positive_rx(tmp_path):
    df=pd.DataFrame([{'sta_index':0,'configured_mbps':5.0,'start_time_seconds':0.5,'active_seconds':2.0,'rx_bytes':0,'achieved_mbps':0.0,'delivered_fraction':0.0}])
    p=tmp_path/'packet_summary.csv'; df.to_csv(p,index=False)
    with pytest.raises(RuntimeError, match='received zero'):
        nc.validate_summary(p,[5.0,0,0,0,0,0],require_positive_rx=True)


def test_14_no_physical_hardware_claim():
    text=(EXP/'protocol'/'PACKET_LEVEL_PROTOCOL_FROZEN.md').read_text().lower()
    assert 'no physical' in text
    assert 'does **not** establish' in text


def test_15_resume_identity_includes_canonical_sources():
    s=(EXP/'src'/'ns3_confirmatory.py').read_text()
    for token in ['wireless_trace_sha256','k8s_planner_config_sha256','canonical_planner_tree_sha256','experiment_image_id','base_image_id']:
        assert token in s


def test_16_attempt_directories_are_preserved():
    s=(EXP/'src'/'ns3_confirmatory.py').read_text()
    assert 'shutil.rmtree(adir)' not in s
    assert 'interrupted.json' in s
    assert 'attempt directory existed without accepted/failure marker' in s


def test_17_analysis_refreshes_manifest():
    s=(EXP/'src'/'ns3_confirmatory.py').read_text()
    tail=s[s.index('def analyze'):]
    assert 'write_manifest(run_root)' in tail


def test_18_execution_safety_constants_are_frozen():
    c=nc.CFG
    assert c['cell_timeout_seconds']==300
    assert c['min_results_free_gib']==8.0
    assert c['smoke_rng_run']==991001
    assert c['smoke_rate_mbps_per_stream']==5.0
    assert c['max_cell_attempts']==2
    assert c['max_rate_mbps_per_stream']==1500.0
    assert c['wigig_commit']=='f3404236d05eb1da1cab80eec06c56ea8ab43f7d'
