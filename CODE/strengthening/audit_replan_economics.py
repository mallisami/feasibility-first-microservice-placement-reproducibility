"""Replay saved S-E1 decisions; this is an audit, not new live evidence."""
from pathlib import Path
import sys
import json
import math
import hashlib
from dataclasses import replace, asdict

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path[:0] = [str(HERE), str(HERE.parent / 'code')]
from run_se1_live_full_planner import RISK
from run_v03_r1 import build_problem
from mape_cap_bplus.objective import evaluate_placement
from mape_cap_bplus.controller import accept_relocation


def main():
    evidence = REPO / 'RESULTS/primary/v03-20260811T151500Z'
    rows = []
    for family in ('strengthening', 'gap-closure'):
        for path in sorted((REPO / 'RESULTS' / family).glob('*/raw/S-E1-live-full-planner/sequence-*/window-*/result.json')):
            saved = json.loads(path.read_text(encoding='utf-8'))
            if not saved.get('planner_executed'):
                continue
            condition = {'stable': 'stable', 'degradation': 'persistent-degradation', 'recovery': 'recovery'}[saved['truth_regime']]
            problem = build_problem(evidence, condition, saved['seed'], saved['placement_before'])
            risk = replace(RISK, relocation_weight=0.0)
            cur = evaluate_placement(problem, saved['placement_before'], risk)
            cand = evaluate_placement(problem, saved['candidate_placement'], risk)
            moved = [r for r, n in saved['candidate_placement'].items() if saved['placement_before'][r] != n]
            cost = sum(problem.relocation_costs[r].cost_units for r in moved)
            uncertainty = sum(problem.relocation_costs[r].uncertainty_units for r in moved)
            accepted, net, _ = accept_relocation(cur.total_objective, cand.total_objective, cost, uncertainty)
            communication = cur.expected_delay_cost - cand.expected_delay_cost
            cvar = risk.cvar_weight * (cur.cvar_delay_cost - cand.cvar_delay_cost)
            slack = risk.slo_slack_weight * (cur.slo_slack - cand.slo_slack)
            rows.append(dict(source=path.relative_to(REPO).as_posix(), source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                current=asdict(cur), candidate=asdict(cand), moved=moved,
                communication_benefit=communication, weighted_cvar_benefit=cvar, slo_benefit=slack,
                relocation_cost=cost, uncertainty=uncertainty, objective_horizon_seconds=problem.decision_window_seconds,
                detector_horizon_seconds=300.0, net_benefit=net, saved_net_benefit=saved['planning']['net_benefit'],
                arithmetic_matches=math.isclose(net, saved['planning']['net_benefit'], abs_tol=1e-7), accepted=accepted,
                live_shaping=saved['shaping']['applied']))
    out = REPO / 'RESULTS/audit/replan-economics-20260912'
    out.mkdir(parents=True, exist_ok=True)
    result = dict(evidence_type='historical-decision-replay-not-an-experiment', replans=len(rows),
        all_arithmetic_matches=bool(rows) and all(r['arithmetic_matches'] for r in rows), rows=rows)
    (out / 'replay.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k != 'rows'}, indent=2))


if __name__ == '__main__':
    main()

