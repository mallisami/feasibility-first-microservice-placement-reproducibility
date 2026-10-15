"""Shared safety, provenance, and environment helpers for strengthening experiments."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    import msvcrt  # type: ignore
except ImportError:  # pragma: no cover
    msvcrt = None
    import fcntl  # type: ignore

IMPLEMENTATION_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = IMPLEMENTATION_ROOT.parent
CODE_ROOT = IMPLEMENTATION_ROOT / "code"
CONFIG_PATH = IMPLEMENTATION_ROOT / "config" / "campaign" / "strengthening_sequential_campaign.json"
RESULTS_ROOT = REPO_ROOT / "RESULTS" / "strengthening"
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def run(cmd: list[str], *, check: bool = True, timeout: int | float = 180, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    if cmd and cmd[0] == "kubectl" and os.environ.get("KUBE_CONTEXT"):
        cmd = ["kubectl", "--context", os.environ["KUBE_CONTEXT"], *cmd[1:]]
    result = subprocess.run(cmd, input=input_text, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(cmd)}\n"
            f"stdout:\n{result.stdout[-2000:]}\nstderr:\n{result.stderr[-2000:]}"
        )
    return result


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def create_run_root(run_id: str | None = None) -> Path:
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    run_id = run_id or datetime.now(timezone.utc).strftime("strengthening-%Y%m%dT%H%M%SZ")
    root = RESULTS_ROOT / run_id
    root.mkdir(parents=True, exist_ok=True)
    for name in ("raw", "derived", "checkpoints", "logs", "manifests"):
        (root / name).mkdir(parents=True, exist_ok=True)
    meta_path = root / "run-metadata.json"
    if not meta_path.exists():
        atomic_json(meta_path, {
            "run_id": run_id,
            "created_utc": utc_now(),
            "campaign": load_config()["campaign_name"],
            "evidence_policy": load_config()["evidence_policy"],
        })
    return root


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def docker_available() -> bool:
    if not command_exists("docker"):
        return False
    try:
        return run(["docker", "info"], check=False, timeout=30).returncode == 0
    except Exception:
        return False


def kubernetes_available() -> bool:
    if not command_exists("kubectl"):
        return False
    try:
        return run(["kubectl", "get", "nodes", "-o", "name"], check=False, timeout=30).returncode == 0
    except Exception:
        return False


def image_present(image: str) -> bool:
    return run(["docker", "image", "inspect", image], check=False, timeout=60).returncode == 0


def image_report(images: Iterable[str]) -> list[dict[str, Any]]:
    rows = []
    for image in images:
        present = image_present(image) if docker_available() else False
        size = None
        image_id = None
        if present:
            res = run(["docker", "image", "inspect", image, "--format", "{{json .}}"], timeout=60)
            payload = json.loads(res.stdout)
            size = payload.get("Size")
            image_id = payload.get("Id")
        rows.append({"image": image, "present": present, "size_bytes": size, "id": image_id})
    return rows


def resource_snapshot() -> dict[str, Any]:
    disk = shutil.disk_usage(REPO_ROOT)
    snap: dict[str, Any] = {
        "captured_utc": utc_now(),
        "disk_free_gib": disk.free / 1024**3,
        "docker_available": docker_available(),
        "kubernetes_available": kubernetes_available(),
        "python": sys.version,
    }
    try:
        import psutil
        vm = psutil.virtual_memory()
        snap["host_available_gib"] = vm.available / 1024**3
        snap["host_total_gib"] = vm.total / 1024**3
    except Exception:
        pass
    if snap["docker_available"]:
        info = None
        for attempt in range(3):
            try:
                info = run(["docker", "info", "--format", "{{json .}}"], check=False, timeout=60)
            except (OSError, subprocess.SubprocessError) as exc:
                snap["docker_info_exception"] = f"{type(exc).__name__}: {exc}"
                info = None
                time.sleep(attempt + 1)
                continue
            if info.returncode == 0:
                break
            time.sleep(attempt + 1)
        if info is not None and info.returncode == 0:
            try:
                p = json.loads(info.stdout)
                snap["docker_mem_total_gib"] = float(p.get("MemTotal", 0)) / 1024**3
                snap["docker_driver"] = p.get("Driver")
                snap["docker_server_version"] = p.get("ServerVersion")
            except Exception:
                snap["docker_info_raw"] = info.stdout[-2000:]
        elif info is not None:
            snap["docker_info_error"] = {
                "returncode": info.returncode,
                "stdout": info.stdout[-2000:],
                "stderr": info.stderr[-2000:],
            }
    if snap["kubernetes_available"]:
        ver = run(["kubectl", "version", "-o", "json"], check=False, timeout=30)
        if ver.returncode == 0:
            try:
                snap["kubernetes_version"] = json.loads(ver.stdout)
            except Exception:
                pass
    return snap


def assert_live_preflight(*, require_kind: bool = True) -> dict[str, Any]:
    snap = resource_snapshot()
    cfg = load_config()["minimum_resources"]
    problems = []
    if snap["disk_free_gib"] < cfg["disk_free_gib"]:
        problems.append(f"need >= {cfg['disk_free_gib']} GiB free disk")
    if not snap["docker_available"]:
        problems.append("Docker is unavailable")
    if not snap["kubernetes_available"]:
        problems.append("kubectl cannot reach a cluster")
    if require_kind and snap.get("kubernetes_available"):
        nodes = run(["kubectl", "get", "nodes", "-o", "json"], check=False, timeout=30)
        if nodes.returncode == 0:
            payload = json.loads(nodes.stdout)
            workers = [x for x in payload.get("items", []) if "control-plane" not in x.get("metadata", {}).get("labels", {}).get("node-role.kubernetes.io/control-plane", "")]
            if len(payload.get("items", [])) < 3:
                problems.append("strengthening live experiments expect the existing three-worker/Kind-style cluster")
    if problems:
        raise RuntimeError("preflight failed: " + "; ".join(problems))
    return snap


@contextmanager
def campaign_lock(name: str = "strengthening-live"):
    """Cross-platform exclusive lock. Parallel live phases are intentionally prohibited."""
    path = RESULTS_ROOT / f".{name}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    if handle.seek(0, os.SEEK_END) == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    try:
        if msvcrt is not None:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise RuntimeError("another strengthening campaign is already running; parallel execution is blocked") from exc
    try:
        yield
    finally:
        try:
            handle.seek(0)
            if msvcrt is not None:
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def write_manifest(root: Path) -> Path:
    out = root / "manifests" / "run.sha256"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path == out or path.name.endswith(".lock"):
            continue
        rows.append(f"{sha256(path)}  {path.relative_to(root).as_posix()}")
    out.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return out


def clear_live_network() -> None:
    try:
        from run_v03_r1 import clear_network
        clear_network()
    except Exception:
        pass


def sleep_with_heartbeat(seconds: float, label: str = "cooldown") -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(min(1.0, deadline - time.monotonic()))
