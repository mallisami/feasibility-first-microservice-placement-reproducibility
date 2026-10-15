#!/usr/bin/env python3
"""Launch all post-review strengthening experiments from one command, sequentially.

Parallel live experiments are intentionally unsupported because they share the
Kind nodes, tc/netem state, image cache, load generator, and control plane.
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path

HERE=Path(__file__).resolve().parent; IMPL=HERE.parent
sys.path.insert(0,str(HERE))
from common import atomic_json, create_run_root, docker_available, load_config, resource_snapshot, run, utc_now, write_manifest

PHASES={
 "S-E7-isolated-overhead":"run_se7_isolated_overhead.py",
 "S-E4-topology-spread-baseline":"run_se4_scheduler_baseline.py",
 "S-E6-external-scheduler":"run_se6_external_scheduler.py",
 "S-E1-live-full-planner":"run_se1_live_full_planner.py",
 "S-E5-live-multi-replica":"run_se5_multi_replica.py",
 "S-GRACE-recovery-guard":"run_sgrace_recovery_guard.py",
 "S-E8-failure-robustness":"run_se8_failure_robustness.py",
 "S-E2-r4-replicated-subset":"run_se2_r4_replicated_subset.py",
 "S-E3-independent-wireless-traces":"run_se3_independent_wireless_traces.py",
 "S-MILP-matched-heuristics":"run_smilp_matched_heuristics.py"
}

CELL_COUNTS={
 "S-E7-isolated-overhead":25,
 "S-E4-topology-spread-baseline":90,
 "S-E6-external-scheduler":135,
 "S-E1-live-full-planner":55,
 "S-E5-live-multi-replica":20,
 "S-GRACE-recovery-guard":30,
 "S-E8-failure-robustness":25,
 "S-E2-r4-replicated-subset":36,
 "S-E3-independent-wireless-traces":24,
 "S-MILP-matched-heuristics":72,
}


def kind_containers()->list[str]:
    if not docker_available(): return []
    r=run(["docker","ps","--filter","label=io.x-k8s.kind.cluster","--format","{{.Names}}"],check=False,timeout=30)
    return [x.strip() for x in r.stdout.splitlines() if x.strip()]


def stop_kind()->list[str]:
    names=kind_containers()
    if names:
        print("Stopping Kind containers before ns-3/offline phases to release RAM:",", ".join(names),flush=True)
        run(["docker","stop",*names],timeout=180)
    return names


def start_kind(names:list[str])->None:
    if names:
        print("Restoring Kind containers:",", ".join(names),flush=True)
        run(["docker","start",*names],timeout=180)


def verify_cluster_baseline()->None:
    snap=resource_snapshot()
    if not snap.get("kubernetes_available"):
        print("WARNING: Kubernetes cluster not reachable for baseline check",flush=True)
        return
    try:
        from run_v03_r1 import wait_healthy
        health=wait_healthy()
        if not health["healthy"]:
            print("WARNING: Online Boutique not healthy at baseline check",flush=True)
    except Exception as exc:
        print(f"WARNING: baseline check failed: {exc}",flush=True)


def main()->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-id")
    p.add_argument("--only",help="comma-separated phase IDs")
    p.add_argument("--include-milp",action="store_true",help="include optional SCIP MILP-heuristic comparison")
    p.add_argument("--keep-kind-running-for-ns3",action="store_true",help="not recommended on low-memory hosts")
    p.add_argument("--dry-run",action="store_true")
    args=p.parse_args(); cfg=load_config(); order=list(cfg["execution_order"])
    if not args.include_milp: order=[x for x in order if x!="S-MILP-matched-heuristics"]
    if args.only:
        requested=[x for x in args.only.split(",") if x]
        unknown=set(requested)-set(PHASES)
        if unknown: p.error(f"unknown phases: {sorted(unknown)}")
        order=[x for x in order if x in requested]
        for x in requested:
            if x not in order: order.append(x)
    if args.dry_run:
        total=sum(CELL_COUNTS.get(x,0) for x in order)
        print("=== Strengthening Campaign Dry Run ===\n")
        for x in order:
            label="OPTIONAL" if x=="S-MILP-matched-heuristics" else ""
            note=""
            if x=="S-E6-external-scheduler": note=" (135 if external scheduler available, 90 if fallback)"
            print(f"  {x:<45s} {CELL_COUNTS.get(x,'?'):>4} cells{note}  {label}")
        if "S-MILP-matched-heuristics" not in order:
            print(f"\n  S-MILP-matched-heuristics                    {CELL_COUNTS['S-MILP-matched-heuristics']:>4} cells  OPTIONAL (--include-milp)")
        print(f"\n  Total: {total} cells (excluding optional S-MILP)" if "S-MILP-matched-heuristics" not in order else f"\n  Total: {total} cells")
        print(f"\n  Commands:")
        for x in order:
            print(f"    {sys.executable} {HERE/PHASES[x]} <RUN_ROOT>")
        return 0
    root=create_run_root(args.run_id)
    ledger={"created_utc":utc_now(),"run_root":str(root),"order":order,"phases":{x:"pending" for x in order},"parallel_execution":False,"experiment_matrix_frozen":True}
    atomic_json(root/"checkpoints"/"strengthening-ledger.json",ledger)
    stopped=[]
    try:
        for phase in order:
            snap=resource_snapshot()
            atomic_json(root/"logs"/f"{phase}-pre-resource-snapshot.json",snap)
            docker_mem=snap.get("docker_mem_total_gib",0)
            if docker_mem>0 and docker_mem<3.5:
                print(f"ABORT: Docker memory too low ({docker_mem:.1f} GiB) — risk of OOM",flush=True)
                ledger["phases"][phase]="aborted-low-memory"; atomic_json(root/"checkpoints"/"strengthening-ledger.json",ledger); return 1
            if phase=="S-E3-independent-wireless-traces" and not args.keep_kind_running_for_ns3 and not stopped:
                stopped=stop_kind()
            if phase not in ("S-E3-independent-wireless-traces","S-MILP-matched-heuristics") and not stopped:
                verify_cluster_baseline()
            cmd=[sys.executable,str(HERE/PHASES[phase]),str(root)]
            print(f"\n=== {phase} ({CELL_COUNTS.get(phase,'?')} cells) ===",flush=True)
            ledger["phases"][phase]="running"; ledger["current_phase"]=phase; atomic_json(root/"checkpoints"/"strengthening-ledger.json",ledger)
            proc=subprocess.run(cmd,cwd=str(IMPL),text=True)
            if proc.returncode:
                ledger["phases"][phase]="failed"; ledger["failed_returncode"]=proc.returncode; atomic_json(root/"checkpoints"/"strengthening-ledger.json",ledger); write_manifest(root); raise SystemExit(proc.returncode)
            ledger["phases"][phase]="completed"; atomic_json(root/"checkpoints"/"strengthening-ledger.json",ledger); write_manifest(root)
        post=[sys.executable,str(HERE/"postprocess_strengthening.py"),str(root)]
        post_proc=subprocess.run(post,cwd=str(IMPL),text=True)
        if post_proc.returncode: raise SystemExit(post_proc.returncode)
        ledger["status"]="completed"; ledger["completed_utc"]=utc_now(); ledger.pop("current_phase",None); atomic_json(root/"checkpoints"/"strengthening-ledger.json",ledger); write_manifest(root); print(f"\nStrengthening campaign complete: {root}")
    finally:
        if stopped: start_kind(stopped)
    return 0

if __name__=="__main__": raise SystemExit(main())
