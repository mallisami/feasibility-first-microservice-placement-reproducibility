#!/usr/bin/env python3
"""Audit R5 original failures and append-only repair selection.

This is a provenance audit only. It does not create new simulator observations.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import pandas as pd

REPAIR_DETAILS = {
    "service-period-1600us": ("service-period", "upstream trace-output directory failure", "successful process completion and expected output files"),
    "service-period-3200us": ("service-period", "upstream trace-output directory failure", "successful process completion and expected output files"),
    "service-period-6400us": ("service-period", "upstream trace-output directory failure", "successful process completion and expected output files"),
    "traffic-allocation-short": ("traffic-allocation", "upstream PHY-state assertion", "successful process plus both expected service-period streams with positive communication"),
    "traffic-allocation-long": ("traffic-allocation", "upstream PHY-state assertion", "successful process plus both expected service-period streams with positive communication"),
    "spatial-sharing-4-links": ("spatial-sharing-4", "invalid Q-D node mapping in original four-link program", "successful process plus all four expected link streams with positive communication"),
}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--run-root', type=Path, required=True)
    ap.add_argument('--output-dir', type=Path, required=True)
    args=ap.parse_args(); out=args.output_dir; out.mkdir(parents=True, exist_ok=True)
    raw=args.run_root/'raw'
    orig=pd.read_csv(raw/'phase-5-r5-index.csv', keep_default_na=False)
    eff=pd.read_csv(args.run_root/'derived/regenerated/r5-effective-status.csv', keep_default_na=False)
    rows=[]
    for _,r in orig.iterrows():
        e=eff[(eff.scenario==r.scenario)&(eff.seed.astype(int)==int(r.seed))].iloc[0]
        repaired=bool(e.get('recovered_by_retry', False))
        fam, reason, gate = REPAIR_DETAILS.get(r.scenario, ('none','none','original complete run retained'))
        rows.append({
            'scenario':r.scenario,'seed':int(r.seed),'original_status':r.status,
            'effective_status':e.status,'repaired':repaired,'repair_family':fam if repaired else 'none',
            'repair_reason':reason if repaired else '', 'acceptance_basis':gate if repaired else 'original complete run',
            'coverage':r.coverage,
        })
    cells=pd.DataFrame(rows)
    cells.to_csv(out/'r5_rerun_audit_cells.csv', index=False)
    scen=(cells.groupby('scenario',as_index=False)
          .agg(original_complete=('original_status',lambda x:int((x=='complete').sum())),
               original_failed=('original_status',lambda x:int((x!='complete').sum())),
               repaired=('repaired','sum'), coverage=('coverage','first')))
    scen.to_csv(out/'r5_rerun_audit_scenarios.csv', index=False)
    original_only=scen[scen.original_failed==0]
    toks=sorted({t.strip().lower() for x in original_only.coverage for t in str(x).split(',') if t.strip()})
    summary={
      'original_cells':int(len(cells)), 'original_complete_cells':int((cells.original_status=='complete').sum()),
      'original_failed_cells':int((cells.original_status!='complete').sum()),
      'final_complete_cells':int((cells.effective_status=='complete').sum()), 'repaired_cells':int(cells.repaired.sum()),
      'repair_scenarios':sorted(scen.loc[scen.repaired>0,'scenario'].tolist()),
      'original_only_scenarios':int(len(original_only)), 'original_only_complete_cells':int(original_only.original_complete.sum()),
      'original_only_coverage_tokens':toks,
      'publication_selection_rule':'For each predeclared scenario/seed, use the original run if complete; otherwise use an append-only successful retry/repair mapped to the same scenario and seed. Original failures remain retained. Repair acceptance is based on successful execution and expected output structure/positive communication streams, not on achieving a favorable throughput magnitude.',
      'selection_bias_boundary':'Unrepaired original cells independently cover LoS/distance, partial/full blockage and recovery, beam training/refinement, multi-service-period scheduling, dense interference, and spatial sharing. The service-period-duration quantitative trend, traffic-allocation scenarios, and four-link spatial-sharing cell rely on repaired executions and must be labeled accordingly.'
    }
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    md=f'''# R5 rerun/repair selection audit\n\nThis audit reconstructs the publication selection rule from the frozen original R5 index and the deterministic effective-R5 output. It creates no new ns-3 observations.\n\n- Original cells: **{summary['original_cells']}** (45 complete, 18 failed).\n- Append-only replacements: **{summary['repaired_cells']}**, mapped one-for-one to the same predeclared scenario/seed identities.\n- Final effective matrix: **{summary['final_complete_cells']}/63**.\n- Unaffected original-only scenarios: **{summary['original_only_scenarios']}** / 21 (**{summary['original_only_complete_cells']}** cells).\n\n## Selection rule\n\n{summary['publication_selection_rule']}\n\n## Inference boundary\n\n{summary['selection_bias_boundary']}\n\nThe repair families and acceptance gates are documented in `r5_rerun_audit_cells.csv`; original failure records remain in the primary raw archive.\n'''
    (out/'R5_RERUN_REPAIR_AUDIT.md').write_text(md)
    print(json.dumps(summary,indent=2))
if __name__=='__main__': main()
