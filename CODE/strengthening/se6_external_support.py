#!/usr/bin/env python3
"""Pinned dependency/bootstrap helpers for the S-E6-only experiment."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

HELM_VERSION = "v3.21.3"
SCHEDULER_PLUGINS_VERSION = "0.33.5"
SCHEDULER_IMAGE = f"registry.k8s.io/scheduler-plugins/kube-scheduler:v{SCHEDULER_PLUGINS_VERSION}"
CONTROLLER_IMAGE = f"registry.k8s.io/scheduler-plugins/controller:v{SCHEDULER_PLUGINS_VERSION}"
CHART_REPO = "https://scheduler-plugins.sigs.k8s.io"
CHART_NAME = "scheduler-plugins"
HELM_RELEASE = "bplus-se6-networkaware"
HELM_NAMESPACE = "scheduler-plugins"
DEFAULT_SCHEDULER_NAME = "network-aware-scheduler"
APPGROUP_NAME = "bplus-se6-online-boutique"
NETWORK_TOPOLOGY_NAME = "bplus-se6-topology"
APPGROUP_LABEL = "appgroup.diktyo.x-k8s.io"
APPGROUP_SELECTOR_LABEL = "appgroup.diktyo.x-k8s.io.workload"
CRD_APPGROUP = "appgroups.appgroup.diktyo.x-k8s.io"
CRD_NETWORK_TOPOLOGY = "networktopologies.networktopology.diktyo.x-k8s.io"
CRD_APPGROUP_URL = f"https://raw.githubusercontent.com/kubernetes-sigs/scheduler-plugins/v{SCHEDULER_PLUGINS_VERSION}/manifests/appgroup/crd.yaml"
CRD_NETWORK_TOPOLOGY_URL = f"https://raw.githubusercontent.com/kubernetes-sigs/scheduler-plugins/v{SCHEDULER_PLUGINS_VERSION}/manifests/networktopology/crd.yaml"
HELM_SHA256 = {
    ("windows", "amd64"): "ff490897e07e976c65a9bd7690cfc139b35ba5e8f25d00eaf1e53a30f1ad3f62",
    ("windows", "arm64"): "1d409b98f99a38704ccb3f0917cbad2417ed53f75751902b6bd84447803b69a9",
    ("linux", "amd64"): "15e041a93a590dce8100f39385cd98c84a765c9e36aeeb9e2dc6ff9e4769e2e0",
    ("linux", "arm64"): "67f58155079ff9ffab98ba5c88daff0ed9b542f3a4732f5dd426dde7dd0f5244",
}


def _run(cmd: list[str], *, timeout: int = 180, check: bool = True, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    if cmd and cmd[0] == "kubectl" and os.environ.get("KUBE_CONTEXT"):
        cmd = ["kubectl", "--context", os.environ["KUBE_CONTEXT"], *cmd[1:]]
    elif cmd and Path(cmd[0]).stem.lower() == "helm" and os.environ.get("KUBE_CONTEXT"):
        cmd = [cmd[0], "--kube-context", os.environ["KUBE_CONTEXT"], *cmd[1:]]
    result = subprocess.run(cmd, input=input_text, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(cmd)}\nstdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-3000:]}")
    return result


def _machine() -> tuple[str, str]:
    system = platform.system().lower()
    if system.startswith("win"):
        os_name = "windows"
    elif system == "linux":
        os_name = "linux"
    elif system == "darwin":
        os_name = "darwin"
    else:
        raise RuntimeError(f"unsupported host OS for automatic Helm bootstrap: {platform.system()}")
    raw = platform.machine().lower()
    if raw in {"x86_64", "amd64"}:
        arch = "amd64"
    elif raw in {"aarch64", "arm64"}:
        arch = "arm64"
    else:
        raise RuntimeError(f"unsupported architecture for automatic Helm bootstrap: {raw}")
    return os_name, arch


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "MAPE-CAP-BPlus-SE6/1.0"})
    with urllib.request.urlopen(req, timeout=120) as response, destination.open("wb") as out:
        shutil.copyfileobj(response, out)


def helm_version(helm: str | Path) -> str:
    return _run([str(helm), "version", "--short"], timeout=30).stdout.strip()


def ensure_pinned_helm(tool_root: Path, evidence_dir: Path) -> tuple[Path, dict[str, Any]]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    os_name, arch = _machine()
    exe_name = "helm.exe" if os_name == "windows" else "helm"
    system_helm = shutil.which("helm")
    if system_helm:
        try:
            version = helm_version(system_helm)
            if version.startswith(HELM_VERSION):
                info = {"source":"system-path","path":system_helm,"requested_version":HELM_VERSION,"observed_version":version,"downloaded":False}
                (evidence_dir/"helm-bootstrap.json").write_text(json.dumps(info,indent=2)+"\n",encoding="utf-8")
                return Path(system_helm), info
        except Exception:
            pass
    install_dir = tool_root / "helm" / HELM_VERSION
    binary = install_dir / exe_name
    if binary.exists():
        version = helm_version(binary)
        if version.startswith(HELM_VERSION):
            info = {"source":"local-pinned-cache","path":str(binary),"requested_version":HELM_VERSION,"observed_version":version,"downloaded":False}
            (evidence_dir/"helm-bootstrap.json").write_text(json.dumps(info,indent=2)+"\n",encoding="utf-8")
            return binary, info
    suffix = ".zip" if os_name == "windows" else ".tar.gz"
    archive_name = f"helm-{HELM_VERSION}-{os_name}-{arch}{suffix}"
    url = f"https://get.helm.sh/{archive_name}"
    archive = install_dir / archive_name
    install_dir.mkdir(parents=True, exist_ok=True)
    _download(url, archive)
    observed_sha = _sha256(archive)
    expected_sha = HELM_SHA256.get((os_name,arch))
    if expected_sha is None:
        checksum_file = install_dir / f"{archive_name}.sha256"
        _download(url+".sha256", checksum_file)
        expected_sha = checksum_file.read_text(encoding="utf-8").strip().split()[0]
    if observed_sha.lower() != expected_sha.lower():
        raise RuntimeError(f"Helm archive SHA-256 mismatch: expected {expected_sha}, observed {observed_sha}")
    extract_dir = install_dir / "extract"
    if extract_dir.exists(): shutil.rmtree(extract_dir)
    extract_dir.mkdir()
    if suffix == ".zip":
        with zipfile.ZipFile(archive) as zf: zf.extractall(extract_dir)
    else:
        with tarfile.open(archive,"r:gz") as tf: tf.extractall(extract_dir)
    candidates = list(extract_dir.rglob(exe_name))
    if not candidates: raise RuntimeError(f"downloaded Helm archive did not contain {exe_name}")
    shutil.copy2(candidates[0], binary)
    if os_name != "windows": binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    version = helm_version(binary)
    if not version.startswith(HELM_VERSION): raise RuntimeError(f"unexpected Helm version after bootstrap: {version}")
    info = {"source":"downloaded-pinned-binary","path":str(binary),"download_url":url,"requested_version":HELM_VERSION,"observed_version":version,"sha256":observed_sha,"expected_sha256":expected_sha,"downloaded":True,"host_os":os_name,"host_arch":arch}
    (evidence_dir/"helm-bootstrap.json").write_text(json.dumps(info,indent=2)+"\n",encoding="utf-8")
    return binary, info


def _kubectl_json(*args: str) -> dict[str, Any]:
    return json.loads(_run(["kubectl",*args,"-o","json"],timeout=60).stdout)


def label_nodes_for_networkaware(workers: list[str], racks: dict[str,str], evidence_dir: Path) -> dict[str,Any]:
    originals = {}
    for node in workers:
        obj = _kubectl_json("get","node",node)
        labels = obj.get("metadata",{}).get("labels",{}) or {}
        originals[node] = {"topology.kubernetes.io/zone":labels.get("topology.kubernetes.io/zone"),"topology.kubernetes.io/region":labels.get("topology.kubernetes.io/region")}
        _run(["kubectl","label","node",node,f"topology.kubernetes.io/zone={racks[node]}","topology.kubernetes.io/region=bplus-se6","--overwrite"],timeout=60)
    payload={"original_labels":originals,"applied_zones":{n:racks[n] for n in workers}}
    (evidence_dir/"node-topology-labels.json").write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
    return originals


def restore_node_labels(originals: dict[str,Any]) -> None:
    for node, labels in originals.items():
        for key,value in labels.items():
            if value is None:
                _run(["kubectl","label","node",node,f"{key}-"],timeout=60,check=False)
            else:
                _run(["kubectl","label","node",node,f"{key}={value}","--overwrite"],timeout=60,check=False)


def _values_yaml(scheduler_name: str, workload_namespace: str) -> str:
    return (
        f"scheduler:\n  name: {scheduler_name}\n  image: {SCHEDULER_IMAGE}\n  replicaCount: 1\n  leaderElect: false\n"
        f"controller:\n  name: scheduler-plugins-controller\n  image: {CONTROLLER_IMAGE}\n  replicaCount: 1\n  leaderElect: false\n"
        "plugins:\n  enabled: [\"NetworkOverhead\"]\n  disabled: [\"NodeResourcesFit\"]\n"
        f"pluginConfig:\n  - name: NetworkOverhead\n    args:\n      namespaces:\n        - \"{workload_namespace}\"\n      weightsName: \"UserDefined\"\n      networkTopologyName: \"{NETWORK_TOPOLOGY_NAME}\"\n"
    )


def install_networkoverhead(helm: Path, evidence_dir: Path, *, scheduler_name: str=DEFAULT_SCHEDULER_NAME, workload_namespace: str) -> dict[str,Any]:
    evidence_dir.mkdir(parents=True,exist_ok=True)
    steps=[]
    for url in (CRD_APPGROUP_URL,CRD_NETWORK_TOPOLOGY_URL):
        r=_run(["kubectl","apply","-f",url],timeout=180); steps.append({"cmd":["kubectl","apply","-f",url],"stdout":r.stdout[-1000:]})
    for crd in (CRD_APPGROUP,CRD_NETWORK_TOPOLOGY):
        _run(["kubectl","wait","--for=condition=Established",f"crd/{crd}","--timeout=120s"],timeout=150)
    values=evidence_dir/"scheduler-plugins-values.yaml"; values.write_text(_values_yaml(scheduler_name,workload_namespace),encoding="utf-8")
    cmd=[str(helm),"upgrade","--install",HELM_RELEASE,CHART_NAME,"--repo",CHART_REPO,"--version",SCHEDULER_PLUGINS_VERSION,"--namespace",HELM_NAMESPACE,"--create-namespace","--wait","--timeout","10m0s","-f",str(values)]
    r=_run(cmd,timeout=720); steps.append({"cmd":cmd,"stdout":r.stdout[-3000:]})
    _run(["kubectl","rollout","status",f"deployment/{scheduler_name}","-n",HELM_NAMESPACE,"--timeout=300s"],timeout=330)
    _run(["kubectl","rollout","status","deployment/scheduler-plugins-controller","-n",HELM_NAMESPACE,"--timeout=300s"],timeout=330)
    dep=_kubectl_json("get","deployment",scheduler_name,"-n",HELM_NAMESPACE); image=dep["spec"]["template"]["spec"]["containers"][0]["image"]
    if image != SCHEDULER_IMAGE: raise RuntimeError(f"external scheduler image mismatch: expected {SCHEDULER_IMAGE}, observed {image}")
    config=_run(["kubectl","get","configmap","scheduler-config","-n",HELM_NAMESPACE,"-o","jsonpath={.data.scheduler-config\\.yaml}"],timeout=60).stdout
    if "NetworkOverhead" not in config or scheduler_name not in config: raise RuntimeError("scheduler config does not contain the pinned NetworkOverhead profile")
    info={"implementation":"Kubernetes SIG scheduler-plugins NetworkOverhead (Diktyo lineage)","scheduler_name":scheduler_name,"scheduler_plugins_version":SCHEDULER_PLUGINS_VERSION,"scheduler_image":image,"controller_image":CONTROLLER_IMAGE,"chart_repo":CHART_REPO,"chart_version":SCHEDULER_PLUGINS_VERSION,"helm_release":HELM_RELEASE,"helm_namespace":HELM_NAMESPACE,"networkoverhead_verified_in_config":True,"steps":steps}
    (evidence_dir/"external-scheduler-install.json").write_text(json.dumps(info,indent=2)+"\n",encoding="utf-8"); (evidence_dir/"scheduler-config.yaml").write_text(config,encoding="utf-8")
    return info


def uninstall_networkoverhead(helm: Path) -> None:
    _run([str(helm),"uninstall",HELM_RELEASE,"-n",HELM_NAMESPACE],timeout=180,check=False)


def apply_json_object(obj: dict[str,Any]) -> None:
    _run(["kubectl","apply","-f","-"],timeout=120,input_text=json.dumps(obj))


def delete_json_object(kind: str, name: str, namespace: str) -> None:
    _run(["kubectl","delete",kind,name,"-n",namespace,"--ignore-not-found=true"],timeout=120,check=False)
