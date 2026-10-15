# Azure VM Preflight and Environment Protection Report

**Audit Date:** 2026-09-19  
**Target Host:** Azure Virtual Machine `mcb-k8s-v137` (`<public-ip-redacted-for-distribution>`)  
**Auditor:** Senior Kubernetes Systems Engineer and Scientific Reproducibility Specialist  

---

## 1. Host Infrastructure Specification

| Attribute | Observed Value | Verification Command | Assessment |
|---|---|---|---|
| **Hostname** | `mcb-k8s-v137` | `hostname` | Disposable test VM dedicated to MAPE-CAP B+ |
| **Operating System** | Ubuntu 24.04.4 LTS (noble) | `lsb_release -a` | Supported standard distribution |
| **Kernel** | `6.17.0-1022-azure` (x86_64) | `uname -r` | Azure-optimized Linux kernel |
| **CPU Hardware** | AMD EPYC 7763 64-Core Processor (4 vCPUs allocated) | `lscpu` | Ample compute for single-host Kind testbed |
| **Physical Memory** | 15.6 GiB total, 13.0 GiB available | `free -h` | Exceeds recommended minimum (6.0 GiB) |
| **Storage Subsystem** | 123 GiB root filesystem, 112 GiB free (10% used) | `df -h /` | Exceeds recommended minimum (20.0 GiB free) |
| **Docker Engine** | Version 29.1.3 (API 1.52, containerd 2.2.1) | `docker version` | Healthy; containerd runtime active |
| **Kind Version** | v0.33.0 (built with go1.26.7 linux/amd64) | `kind version` | Pinned experimental release |
| **Kubectl Version** | Client: v1.37.0 / Server: v1.37.0 | `kubectl version` | Pinned v1.37.0 release |
| **Python Runtime** | Python 3.12.3 in `/home/azureuser/mcb/implementation/.venv` | `python3 --version` | Virtualenv active with all pinned dependencies |

---

## 2. Kubernetes Cluster Topology & Isolation Boundary

- **Cluster Context:** `kind-mcb-k137`
- **Cluster Architecture:** 1 control-plane node + 3 worker nodes running as isolated Docker containers on a shared Linux VM host.
  - `mcb-k137-control-plane` (`172.18.0.3`, podCIDR `10.244.0.0/24`)
  - `mcb-k137-worker` (`172.18.0.4`, podCIDR `10.244.4.0/24`)
  - `mcb-k137-worker2` (`172.18.0.2`, podCIDR `10.244.1.0/24`)
  - `mcb-k137-worker3` (`172.18.0.5`, podCIDR `10.244.2.0/24`)
- **Isolation Scope:** The Kind cluster is an isolated, disposable test cluster. It contains no production workloads, credentials, or shared corporate services.
- **Worker-to-Host Topology Limitation:** All three worker nodes execute as containers on a single Azure VM kernel. They do not constitute independent physical hardware hosts or multi-rack network fabrics. Findings must not be represented as multi-host production validation.

---

## 3. Workload Readiness & Network Reconciliation

- **Application Namespace:** `online-boutique`
- **Services Deployed:** 11 core microservices (`adservice`, `cartservice`, `checkoutservice`, `currencyservice`, `emailservice`, `frontend`, `paymentservice`, `productcatalogservice`, `recommendationservice`, `redis-cart`, `shippingservice`) + `loadgenerator`.
- **Preflight Reconciliation:** Upon initial VM boot, pod CIDR assignments from pre-reboot state were misaligned with the active `kindnet` routing tables. All 12 deployments were rolled out (`kubectl rollout restart`), refreshing container network namespaces to match node `podCIDR` boundaries.
- **Health Verification:**
  - Node readiness: 4/4 nodes `Ready`.
  - Pod readiness: 12/12 pods `Running`, `1/1 Ready`, 0 unexpected restarts.
  - Internal HTTP health probe: `assert_healthy() -> True` and `frontend_probe() -> True`.

---

## 4. Preflight Assessment Verdict

**STATUS: PASS — EXECUTION READY**

The Azure VM environment provides sufficient resources, complete dependency isolation, verified cluster health, and clean network connectivity required to execute the S-E8 qualification smoke test and scientific campaign.
