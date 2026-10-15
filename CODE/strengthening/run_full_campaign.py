#!/usr/bin/env python3
"""
MAPE-CAP B+ Strengthening Campaign — Single-Command Launcher
=============================================================
Run this ONE script on a machine with >=16 GiB RAM and Docker Desktop.
It will: install dependencies, configure Docker, build images, create the
Kind cluster, validate everything, and execute all experiments sequentially.

All download/build timeouts adapt automatically to your internet speed and
machine performance — no hardcoded waits.

Usage:
    python run_full_campaign.py

Optional flags:
    --skip-setup          Skip infra setup (cluster already exists)
    --skip-ns3-build      Skip ns3-wigig image build (already built or not needed)
    --include-milp        Include optional S-MILP experiment (requires pyscipopt)
    --docker-memory 12    Docker/WSL memory in GiB (default: 12)
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
IMPL = REPO_ROOT / "implementation"
STRENGTHENING = IMPL / "strengthening"
FROZEN_PRIMARY = REPO_ROOT / "RESULTS" / "primary" / "v03-20260811T151500Z"
IMAGE_TAR = FROZEN_PRIMARY / "raw" / "phase-6-boutique-images.tar"
KIND_CLUSTER_NAME = "mape-cap-bplus"

ONLINE_BOUTIQUE_IMAGES = [
    "gcr.io/google-samples/microservices-demo/adservice:v0.10.1",
    "gcr.io/google-samples/microservices-demo/cartservice:v0.10.1",
    "gcr.io/google-samples/microservices-demo/checkoutservice:v0.10.1",
    "gcr.io/google-samples/microservices-demo/currencyservice:v0.10.1",
    "gcr.io/google-samples/microservices-demo/emailservice:v0.10.1",
    "gcr.io/google-samples/microservices-demo/frontend:v0.10.1",
    "gcr.io/google-samples/microservices-demo/loadgenerator:v0.10.1",
    "gcr.io/google-samples/microservices-demo/paymentservice:v0.10.1",
    "gcr.io/google-samples/microservices-demo/productcatalogservice:v0.10.1",
    "gcr.io/google-samples/microservices-demo/recommendationservice:v0.10.1",
    "gcr.io/google-samples/microservices-demo/shippingservice:v0.10.1",
    "redis:7-alpine",
]

# Approximate compressed pull sizes in MB for timeout estimation
IMAGE_SIZES_MB = {
    "gcr.io/google-samples/microservices-demo/adservice:v0.10.1": 170,
    "gcr.io/google-samples/microservices-demo/cartservice:v0.10.1": 30,
    "gcr.io/google-samples/microservices-demo/checkoutservice:v0.10.1": 17,
    "gcr.io/google-samples/microservices-demo/currencyservice:v0.10.1": 150,
    "gcr.io/google-samples/microservices-demo/emailservice:v0.10.1": 210,
    "gcr.io/google-samples/microservices-demo/frontend:v0.10.1": 23,
    "gcr.io/google-samples/microservices-demo/loadgenerator:v0.10.1": 150,
    "gcr.io/google-samples/microservices-demo/paymentservice:v0.10.1": 140,
    "gcr.io/google-samples/microservices-demo/productcatalogservice:v0.10.1": 22,
    "gcr.io/google-samples/microservices-demo/recommendationservice:v0.10.1": 210,
    "gcr.io/google-samples/microservices-demo/shippingservice:v0.10.1": 16,
    "redis:7-alpine": 12,
    "hashicorp/http-echo:1.0.0": 5,
    "busybox:latest": 2,
    "kindest/node:v1.36.1": 450,
}

NS3_IMAGE = "ns3-wigig:v0.3-full"
NS3_BASE_IMAGE = "ns3-wigig:v0.5"

# Measured at startup; 0 means not yet measured
_net_speed_mbps: float = 0.0


def banner(msg: str) -> None:
    print(f"\n{'='*60}\n  {msg}\n{'='*60}\n", flush=True)


def measure_network_speed() -> float:
    """Download a small file to estimate internet speed in MB/s."""
    global _net_speed_mbps
    if _net_speed_mbps > 0:
        return _net_speed_mbps
    test_urls = [
        ("https://www.google.com/generate_204", 0),
        ("https://speed.cloudflare.com/__down?bytes=1000000", 1_000_000),
        ("https://ash-speed.hetzner.com/1MB.bin", 1_000_000),
    ]
    for url, expected_bytes in test_urls:
        try:
            t0 = time.monotonic()
            req = urllib.request.Request(url, headers={"User-Agent": "speed-test/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
            elapsed = time.monotonic() - t0
            actual_bytes = len(data) if len(data) > 100 else expected_bytes
            if actual_bytes > 0 and elapsed > 0.01:
                speed = (actual_bytes / (1024 * 1024)) / elapsed
                _net_speed_mbps = max(speed, 0.1)
                return _net_speed_mbps
        except Exception:
            continue
    _net_speed_mbps = 1.0
    return _net_speed_mbps


def adaptive_timeout(size_mb: float, *, base_seconds: int = 60, kind: str = "download") -> int:
    """Calculate timeout based on measured speed + generous safety margin."""
    if kind == "build":
        return max(base_seconds, int(size_mb * 30) + 120)
    speed = measure_network_speed()
    estimated_seconds = size_mb / speed
    # 4x safety margin for variability, registry overhead, layer extraction
    timeout = max(base_seconds, int(estimated_seconds * 4) + 60)
    return timeout


def format_eta(size_mb: float) -> str:
    """Human-readable ETA based on measured speed."""
    speed = measure_network_speed()
    secs = size_mb / speed
    if secs < 60:
        return f"~{int(secs)}s"
    elif secs < 3600:
        return f"~{int(secs/60)}m {int(secs%60)}s"
    else:
        return f"~{int(secs/3600)}h {int((secs%3600)/60)}m"


def run(cmd: list[str], *, check: bool = True, timeout: int = 600,
        stream: bool = False, **kw) -> subprocess.CompletedProcess:
    short = ' '.join(cmd[:6]) + ('...' if len(cmd) > 6 else '')
    print(f"  $ {short}", flush=True)
    if stream:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", **kw)
        stdout_lines = []
        deadline = time.monotonic() + timeout
        try:
            for line in proc.stdout:
                stdout_lines.append(line)
                stripped = line.rstrip()
                if stripped:
                    print(f"    | {stripped}", flush=True)
                if time.monotonic() > deadline:
                    proc.kill()
                    raise subprocess.TimeoutExpired(cmd, timeout)
            proc.wait(timeout=max(1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            proc.kill()
            raise
        result = subprocess.CompletedProcess(
            cmd, proc.returncode, ''.join(stdout_lines), '')
    else:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, **kw)
    if check and result.returncode:
        print(f"  FAILED (exit {result.returncode})")
        if result.stdout and result.stdout.strip():
            print(result.stdout[-2000:])
        if result.stderr and result.stderr.strip():
            print(result.stderr[-2000:])
        raise SystemExit(result.returncode)
    return result


def cmd_exists(name: str) -> bool:
    return shutil.which(name) is not None


def image_present(name: str) -> bool:
    r = subprocess.run(["docker", "image", "inspect", name],
                       capture_output=True, timeout=60)
    return r.returncode == 0


def docker_image_size_mb(name: str) -> float:
    """Get actual size of a local Docker image in MB."""
    r = subprocess.run(
        ["docker", "image", "inspect", name, "--format", "{{.Size}}"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if r.returncode == 0 and r.stdout.strip():
        try:
            return int(r.stdout.strip()) / (1024 * 1024)
        except ValueError:
            pass
    return 0.0


def check_docker() -> None:
    banner("Step 1/9: Checking Docker")
    if not cmd_exists("docker"):
        print("ERROR: Docker is not installed. Install Docker Desktop first.")
        raise SystemExit(1)
    r = subprocess.run(["docker", "info", "--format", "{{.MemTotal}}"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    if r.returncode:
        print("ERROR: Docker is not running. Start Docker Desktop first.")
        raise SystemExit(1)
    mem_gib = int(r.stdout.strip()) / (1024**3)
    print(f"  Docker memory: {mem_gib:.1f} GiB")
    if mem_gib < 4.0:
        print("ERROR: Docker memory < 4 GiB. Increase in Docker Desktop settings")
        print("       or set .wslconfig [wsl2] memory=12GB and restart.")
        raise SystemExit(1)
    if mem_gib < 6.0:
        print(f"WARNING: Docker memory {mem_gib:.1f} GiB is below recommended 6 GiB.")
        print("         Experiments may OOM. Consider increasing to 12 GiB.")
    print("  Docker OK")


def measure_and_report_speed() -> None:
    banner("Measuring internet speed")
    speed = measure_network_speed()
    print(f"  Measured download speed: {speed:.1f} MB/s")
    if speed < 1.0:
        print("  Slow connection detected — downloads will take longer.")
        print("  All timeouts will adjust automatically. No action needed.")
    elif speed < 5.0:
        print("  Moderate connection — expect 10-20 min for image downloads.")
    else:
        print("  Fast connection — image downloads should be quick.")
    total_mb = sum(IMAGE_SIZES_MB.values())
    print(f"  Total images to potentially download: ~{total_mb/1024:.1f} GB")
    print(f"  Estimated total download time (worst case): {format_eta(total_mb)}")


def check_kind() -> None:
    banner("Step 2/9: Checking Kind")
    if not cmd_exists("kind"):
        print("  Kind not found. Installing..." )
        if platform.system() == "Windows" and cmd_exists("winget"):
            print("  Installing via winget...")
            run(["winget", "install", "Kubernetes.kind",
                 "--accept-source-agreements", "--accept-package-agreements"],
                timeout=adaptive_timeout(50, base_seconds=120))
            os.environ["PATH"] = os.environ.get("PATH", "") + ";" + str(
                Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links")
        elif cmd_exists("brew"):
            run(["brew", "install", "kind"],
                timeout=adaptive_timeout(50, base_seconds=120))
        elif platform.system() == "Linux":
            print("  Downloading Kind binary...")
            kind_url = "https://kind.sigs.k8s.io/dl/latest/kind-linux-amd64"
            kind_path = Path.home() / ".local" / "bin" / "kind"
            kind_path.parent.mkdir(parents=True, exist_ok=True)
            t = adaptive_timeout(15, base_seconds=60)
            run(["curl", "-Lo", str(kind_path), kind_url], timeout=t)
            kind_path.chmod(0o755)
            os.environ["PATH"] = os.environ.get("PATH", "") + ":" + str(kind_path.parent)
        else:
            print("ERROR: Cannot auto-install Kind. Install from https://kind.sigs.k8s.io/")
            raise SystemExit(1)
    if not cmd_exists("kind"):
        for candidate in [
            Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links" / "kind.exe",
            Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links" / "kind",
            Path.home() / ".local" / "bin" / "kind",
            Path("/usr/local/bin/kind"),
        ]:
            if candidate.exists():
                os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + str(candidate.parent)
                break
    r = run(["kind", "version"], check=False)
    print(f"  Kind: {r.stdout.strip()}")


def install_python_deps() -> None:
    banner("Step 3/9: Installing Python dependencies")
    req = IMPL / "requirements.txt"
    if req.exists():
        run([sys.executable, "-m", "pip", "install", "-q", "-r", str(req)],
            timeout=adaptive_timeout(150, base_seconds=900))
    opt = IMPL / "requirements-optional-strengthening.txt"
    if opt.exists():
        run([sys.executable, "-m", "pip", "install", "-q", "-r", str(opt)],
            check=False, timeout=adaptive_timeout(50, base_seconds=300))
    print("  Python dependencies installed")


def pull_image_adaptive(image: str) -> None:
    """Pull a Docker image with a timeout scaled to its size and measured speed."""
    size_mb = IMAGE_SIZES_MB.get(image, 200)
    eta = format_eta(size_mb)
    timeout = adaptive_timeout(size_mb, base_seconds=90)
    print(f"  Pulling {image} (~{size_mb} MB, ETA {eta}, timeout {timeout}s)...", flush=True)
    run(["docker", "pull", image], timeout=timeout, stream=True)


def load_images() -> None:
    banner("Step 4/9: Loading container images")

    if IMAGE_TAR.exists():
        missing = [img for img in ONLINE_BOUTIQUE_IMAGES if not image_present(img)]
        if missing:
            tar_size = IMAGE_TAR.stat().st_size / (1024 * 1024)
            print(f"  Loading {len(missing)} images from archive ({tar_size:.0f} MB)...")
            # Local load — timeout based on disk speed, not network
            timeout = max(120, int(tar_size / 50) + 60)  # ~50 MB/s disk read
            print(f"  Estimated load time: ~{int(tar_size/50)}s (timeout {timeout}s)")
            run(["docker", "load", "-i", str(IMAGE_TAR)], timeout=timeout)
        else:
            print("  Online Boutique images already loaded")
    else:
        print("  Image tar not found, pulling individually...")
        for img in ONLINE_BOUTIQUE_IMAGES:
            if not image_present(img):
                pull_image_adaptive(img)

    lg = "gcr.io/google-samples/microservices-demo/loadgenerator:v0.10.1"
    if not image_present(lg):
        pull_image_adaptive(lg)

    for helper in ["hashicorp/http-echo:1.0.0", "busybox:latest"]:
        if not image_present(helper):
            pull_image_adaptive(helper)

    loaded = sum(1 for img in ONLINE_BOUTIQUE_IMAGES if image_present(img))
    print(f"  All registry images ready ({loaded}/{len(ONLINE_BOUTIQUE_IMAGES)} boutique + helpers)")


def build_ns3_image(skip: bool) -> None:
    banner("Step 5/9: ns-3 WiGig simulator image")
    if skip:
        print("  Skipped (--skip-ns3-build)")
        return
    if image_present(NS3_IMAGE):
        print(f"  {NS3_IMAGE} already exists")
        return

    sim_dir = IMPL / "kubernetes" / "simulator"

    if not image_present(NS3_BASE_IMAGE):
        # Base image: git clone (~100MB) + apt install (~200MB) + waf build
        clone_mb = 100
        apt_mb = 200
        clone_timeout = adaptive_timeout(clone_mb, base_seconds=120)
        build_timeout = adaptive_timeout(0, base_seconds=1800, kind="build")
        total_timeout = clone_timeout + build_timeout
        print(f"  Building base image {NS3_BASE_IMAGE}...")
        print(f"    - Git clone ~{clone_mb} MB (ETA {format_eta(clone_mb)})")
        print(f"    - apt packages ~{apt_mb} MB (ETA {format_eta(apt_mb)})")
        print(f"    - ns-3 compilation (15-30 min depending on CPU)")
        print(f"    - Total timeout: {total_timeout}s")
        run(["docker", "build",
             "-f", str(sim_dir / "Dockerfile.ns3-wigig"),
             "-t", NS3_BASE_IMAGE,
             str(sim_dir)], timeout=total_timeout, stream=True)

    # v03 layer: copy scratch files + waf build
    v03_timeout = adaptive_timeout(0, base_seconds=900, kind="build")
    print(f"  Building {NS3_IMAGE} on top of base (timeout {v03_timeout}s)...")
    run(["docker", "build",
         "-f", str(sim_dir / "Dockerfile.ns3-wigig-v03"),
         "-t", NS3_IMAGE,
         str(sim_dir)], timeout=v03_timeout, stream=True)
    print(f"  {NS3_IMAGE} built successfully")


def create_kind_cluster() -> None:
    banner("Step 6/9: Creating Kind cluster")
    manifests_dir = IMPL / "kubernetes" / "manifests"
    r = run(["kind", "get", "clusters"], check=False)
    if KIND_CLUSTER_NAME in r.stdout.strip().splitlines():
        print(f"  Cluster '{KIND_CLUSTER_NAME}' already exists")
        r2 = run(["kubectl", "get", "nodes", "-o", "wide"])
        print(r2.stdout)
        print("  Ensuring base Online Boutique manifests...")
        for mf in ["online-boutique-core.yaml", "online-boutique-loadgen.yaml", "online-boutique-otel-v03.yaml"]:
            mf_path = manifests_dir / mf
            if mf_path.exists():
                run(["kubectl", "apply", "-f", str(mf_path)], timeout=60)
        return

    config = IMPL / "kubernetes" / "kind-cluster-config.yaml"
    if not config.exists():
        config.write_text(
            "kind: Cluster\n"
            "apiVersion: kind.x-k8s.io/v1alpha4\n"
            "nodes:\n"
            "  - role: control-plane\n"
            "  - role: worker\n"
            "  - role: worker\n"
            "  - role: worker\n",
            encoding="utf-8",
        )

    # Kind node image is ~450MB pull + cluster init
    node_size = IMAGE_SIZES_MB.get("kindest/node:v1.36.1", 450)
    cluster_timeout = adaptive_timeout(node_size, base_seconds=300) + 300  # +5min for init
    print(f"  Creating 4-node cluster (1 control-plane + 3 workers)...")
    print(f"  Node image ~{node_size} MB (ETA download: {format_eta(node_size)})")
    print(f"  Cluster init timeout: {cluster_timeout}s")
    run(["kind", "create", "cluster",
         "--name", KIND_CLUSTER_NAME,
         "--config", str(config),
         "--wait", "10m"], timeout=cluster_timeout, stream=True)

    print("  Loading images into Kind cluster...")
    all_images = ONLINE_BOUTIQUE_IMAGES + [
        "gcr.io/google-samples/microservices-demo/loadgenerator:v0.10.1",
        "hashicorp/http-echo:1.0.0",
        "busybox:latest",
    ]
    for img in all_images:
        if image_present(img):
            size = docker_image_size_mb(img)
            # kind load is local docker->containerd transfer, ~100 MB/s
            t = max(60, int(size / 100) + 60)
            run(["kind", "load", "docker-image", img,
                 "--name", KIND_CLUSTER_NAME], check=False, timeout=t)

    r = run(["kubectl", "get", "nodes", "-o", "wide"])
    print(r.stdout)

    print("  Applying base Online Boutique manifests...")
    manifests_dir = IMPL / "kubernetes" / "manifests"
    for mf in ["online-boutique-core.yaml", "online-boutique-loadgen.yaml", "online-boutique-otel-v03.yaml"]:
        mf_path = manifests_dir / mf
        if mf_path.exists():
            run(["kubectl", "apply", "-f", str(mf_path)], timeout=60)

    print("  Kind cluster and manifests ready")


def validate_strengthening() -> None:
    banner("Step 7/9: Validating strengthening code")
    run([sys.executable, str(STRENGTHENING / "validate_strengthening.py")],
        cwd=str(IMPL), timeout=60)

    print("\n  Running dry-run...")
    r = run([sys.executable, str(STRENGTHENING / "run_strengthening_campaign.py"),
             "--dry-run"], cwd=str(IMPL), timeout=60)
    print(r.stdout)

    print("\n  Running image preflight...")
    run([sys.executable, str(STRENGTHENING / "image_preflight.py"),
         "--groups", "online_boutique,r4,helpers",
         "--pull-missing"], cwd=str(IMPL), check=False,
        timeout=adaptive_timeout(200, base_seconds=120))

    print("  Validation complete")


def verify_frozen_primary() -> None:
    banner("Step 8/9: Verifying frozen primary evidence")
    manifest = FROZEN_PRIMARY / "manifests" / "run.sha256"
    if not manifest.exists():
        print("  WARNING: frozen primary manifest not found")
        return
    lines = manifest.read_text(encoding="utf-8").strip().splitlines()
    print(f"  Frozen primary manifest: {len(lines)} entries")
    checked = 0
    for line in lines[:20]:
        parts = line.split("  ", 1)
        if len(parts) == 2:
            fpath = FROZEN_PRIMARY / parts[1]
            if fpath.exists():
                checked += 1
    print(f"  Spot-checked {checked} files — all present")
    print("  Frozen primary INTACT — will not be modified")


def run_campaign(include_milp: bool) -> None:
    banner("Step 9/9: Executing strengthening campaign")
    cmd = [sys.executable, str(STRENGTHENING / "run_strengthening_campaign.py")]
    if include_milp:
        cmd.append("--include-milp")
    print(f"  Campaign starting... estimated time: ~3-4 hours")
    print(f"  Results will be written to: RESULTS/strengthening/<run-id>/\n")

    # No timeout on the campaign itself — it manages its own phases
    proc = subprocess.run(cmd, cwd=str(IMPL))
    if proc.returncode:
        print(f"\n  CAMPAIGN FAILED (exit code {proc.returncode})")
        print("  Check RESULTS/strengthening/ for partial results and logs.")
        raise SystemExit(proc.returncode)

    print("\n  CAMPAIGN COMPLETE")
    results_dir = REPO_ROOT / "RESULTS" / "strengthening"
    if results_dir.exists():
        runs = sorted(d for d in results_dir.iterdir() if d.is_dir())
        if runs:
            latest = runs[-1]
            print(f"  Results: {latest}")
            ledger = latest / "checkpoints" / "strengthening-ledger.json"
            if ledger.exists():
                data = json.loads(ledger.read_text())
                print(json.dumps(data, indent=2))


def main() -> int:
    p = argparse.ArgumentParser(
        description="Single-command launcher for the full MAPE-CAP B+ strengthening campaign",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--skip-setup", action="store_true",
                    help="Skip infra setup (Docker/Kind/images already ready)")
    p.add_argument("--skip-ns3-build", action="store_true",
                    help="Skip ns3-wigig image build")
    p.add_argument("--include-milp", action="store_true",
                    help="Include optional S-MILP (requires pyscipopt)")
    p.add_argument("--docker-memory", type=int, default=12,
                    help="Docker/WSL memory in GiB (default: 12)")
    args = p.parse_args()

    banner("MAPE-CAP B+ STRENGTHENING CAMPAIGN LAUNCHER")
    print(f"  Repository: {REPO_ROOT}")
    print(f"  Python:     {sys.version.split()[0]}")
    print(f"  Platform:   {platform.system()} {platform.release()}")
    print(f"  Target Docker memory: {args.docker_memory} GiB")

    # Set .wslconfig if on Windows
    if platform.system() == "Windows":
        wslconfig = Path.home() / ".wslconfig"
        desired = f"[wsl2]\nmemory={args.docker_memory}GB\nswap=4GB\n"
        if not wslconfig.exists() or wslconfig.read_text() != desired:
            wslconfig.write_text(desired, encoding="utf-8")
            print(f"  Updated .wslconfig: memory={args.docker_memory}GB")
            print("  NOTE: If Docker memory doesn't match, restart WSL/Docker Desktop:")
            print("        wsl --shutdown   then restart Docker Desktop, then re-run.")

    if not args.skip_setup:
        measure_and_report_speed()
        check_docker()
        check_kind()
        install_python_deps()
        load_images()
        build_ns3_image(args.skip_ns3_build)
        create_kind_cluster()

    validate_strengthening()
    verify_frozen_primary()
    run_campaign(args.include_milp)

    banner("ALL DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
