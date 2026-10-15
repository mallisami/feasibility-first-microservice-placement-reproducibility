#!/usr/bin/env python3
"""Generate reviewer-driven provenance, environment, and statistical-sensitivity tables.

These assets expose evidence already frozen in the v0.3 repository; they do not alter
or reanalyse the primary experiment outcomes.
"""
from __future__ import annotations
import csv, json
from pathlib import Path

SYSTEM=Path(__file__).resolve().parents[1]
ROOT=SYSTEM.parent
RUN=ROOT/'RESULTS'/'primary'/'v03-20260811T151500Z'
OUT=ROOT/'PAPER'/'tables'/'v03'
ENV=SYSTEM/'environment'/'V03_ENVIRONMENT_AUDIT_20260811.json'


def write(name:str,text:str)->None:
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/name).write_text(text.strip()+"\n",encoding='utf-8')


def holm(ps:list[float])->list[float]:
    m=len(ps); order=sorted(range(m),key=lambda i:ps[i]); out=[0.0]*m; running=0.0
    for rank,i in enumerate(order):
        running=max(running,min(1.0,(m-rank)*ps[i])); out[i]=running
    return out


def main()->int:
    env=json.loads(ENV.read_text(encoding='utf-8'))
    node=env['kubectl']['nodes']['items'][0]['status']['nodeInfo']
    docker_server=env['docker']['version']['Server']
    mem_gib=env['docker']['info']['MemTotal']/2**30
    parameter=r'''% Auto-generated from frozen v0.3 implementation/audit evidence.
\begin{table}[htbp]
\centering
\caption{Principal parameter provenance. ``Design constant'' means frozen before the corresponding primary result and not fitted to that result.}
\label{tab:parameter-provenance}
\scriptsize
\resizebox{\linewidth}{!}{%
\begin{tabular}{llll}
\toprule
Parameter & Frozen value / range & Provenance & Interpretation / sensitivity status \\
\midrule
R1 CVaR quantile $q$ & 0.80 & v0.3 runner & Design constant; R6 separately sweeps 0.50/0.80/0.90/0.95 \\
CVaR weight $\lambda$ & 1.5 & v0.3 freeze & Design weight; ablation and 144-configuration sensitivity show nonzero risk weighting changes the score \\
Relocation weight $\mu$ & 1.0 & v0.3 freeze & Conversion/importance coefficient on measured relocation operational cost \\
Threshold weight $\xi$ & 1000 & correctness gate + freeze & Converts threshold-slack ms to a deliberately high-priority planning penalty \\
Base relocation $\rho$ & 4062 cost units (4.062 s) & 4-run relocation pilot & Mean create--ready--remove calibration; stateful Redis uses a frozen 4$\times$ conservative multiplier \\
R1 move cap $M_{\max}$ & 4 replicas & R1 problem construction & Author-specified disruption cap; not learned from outcome data \\
R1 flow threshold $\bar L_{ij}$ & 500 ms & R1 problem construction & Network-latency threshold, not an end-to-end application SLO \\
R3 persistence & 3 windows & v0.3 freeze & Requires persistent degradation before a move is considered \\
R3 horizon $H$ & 300 s & R3 runner & Frozen forecast/regime horizon \\
R3 uncertainty reserve & 5\% of forecast gain & R3 runner & Author-specified conservative design constant; no empirical fit claimed \\
R3 floor & 4096 bytes & R3 runner & Imposes a nonzero minimum move/uncertainty penalty near zero estimated traffic \\
Generic controller $\epsilon_0,\gamma$ & 10, 1.25 & v0.3 freeze & Used by generic/supporting gate; live R3 uses the byte-equivalent gate instead \\
\bottomrule
\end{tabular}%
}
\end{table}'''
    write('parameter_provenance.tex',parameter)

    testbed=rf'''% Auto-generated from V03_ENVIRONMENT_AUDIT_20260811.json and frozen runners.
\begin{{table}}[htbp]
\centering
\caption{{Frozen live-experiment environment and measurement protocol from the v0.3 environment capture and runners.}}
\label{{tab:testbed-environment}}
\scriptsize
\resizebox{{\linewidth}}{{!}}{{%
\begin{{tabular}}{{ll}}
\toprule
Item & Frozen setting \\
\midrule
Host OS / CPU & Windows 11 build {env['os']['version'].split('.')[-1]}; {env['cpu']['processor'].split(',')[0]}; {env['cpu']['cores_logical']} logical CPUs \\
Docker & Docker Desktop {docker_server['Platform']['Name'].split()[2]}; Engine {docker_server['Version']}; Linux VM memory {mem_gib:.2f} GiB \\
Kind / Kubernetes & kind v0.29.0; node Kubernetes {node['kubeletVersion']}; kubectl client {env['kubectl']['version']['clientVersion']['gitVersion']} \\
Node runtime / OS & {node['containerRuntimeVersion'].replace('://',' ')}; {node['osImage']}; WSL2 kernel {node['kernelVersion'].replace('-microsoft-standard-WSL2','')} \\
Topology & one control plane + three workers labelled rack-a/rack-b/rack-c \\
Network shaping & Linux \texttt{{tc/netem}} on worker \texttt{{eth0}}; cleared after each cell \\
R1 protocol & 30 paired replicates; rotated method order; 10-s post-placement stabilization; 20-s measured interval \\
R2 protocol & three modes; three independent 60-s replicates per mode \\
R3 protocol & five independent sequences; 11 windows/sequence; 15 s/window \\
R4 protocol & 72 factorial cells; Redis availability sampled every 0.2 s \\
R7 protocol & dedicated third-worker load generator; \texttt{{wrk2}} 30 s at 50 target RPS; 0.2-s availability probe \\
Physical 60-GHz hardware & Not used; wireless mechanisms are ns-3/WiGig and live effective states are netem-emulated \\
\bottomrule
\end{{tabular}}%
}}
\end{{table}}'''
    write('testbed_environment.tex',testbed)

    with (RUN/'derived'/'statistics'/'paired-statistics.csv').open(newline='',encoding='utf-8') as f:
        rows=list(csv.DictReader(f))
    lines=[r'''% Auto-generated post-hoc sensitivity from frozen paired-statistics.csv.
\begin{table}[htbp]
\centering
\caption{Post-hoc multiplicity sensitivity. The primary analysis remains the single 142-test global Holm family; this table only shows what changes when Holm is applied separately within each experiment.}
\label{tab:statistical-sensitivity}
\scriptsize
\resizebox{\linewidth}{!}{%
\begin{tabular}{lrrl}
\toprule
Experiment & Tests & Within-experiment Holm significant & Significant metrics/conditions \\
\midrule''']
    for exp in ['R1','R7','R8']:
        sub=[r for r in rows if r['experiment']==exp]
        adjusted=holm([float(r['raw_p_value_paired_t']) for r in sub])
        sig=[r for r,a in zip(sub,adjusted) if a<0.05]
        desc='None' if not sig else '; '.join(f"{r['group']} {r['metric'].replace('_',' ')}" for r in sig)
        desc=desc.replace('%',r'\%').replace('_',r'\_')
        lines.append(f"{exp} & {len(sub)} & {len(sig)} & {desc} \\\\")
    lines.extend([r'''\bottomrule
\end{tabular}%
}
\end{table}'''])
    write('statistical_sensitivity.tex','\n'.join(lines))
    print(f'Generated reviewer-revision assets in {OUT}')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
