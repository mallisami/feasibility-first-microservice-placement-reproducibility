# Start here — three-machine multi-host Kubernetes validation

This package is only for the new multi-host follow-up. You do **not** need the full reproducibility package to execute it.

## Intended machines

- Machine 1 / server -> `rack-a` (k3s server + schedulable worker)
- Machine 2 -> `rack-b` (k3s agent)
- Machine 3 -> `rack-c` (k3s agent)

All three should be x86-64 Ubuntu/Linux machines in the same private network/VNet. For this package, use at least ~4 GiB RAM on rack-a/server and ~2 GiB RAM on each 1-vCPU agent.

## Azure network prerequisites

Restrict these rules to the private VNet/subnet, not the public Internet:

- TCP 6443: workers -> server
- UDP 8472: all three nodes <-> all three nodes (Flannel VXLAN)
- TCP 10250: all three nodes <-> all three nodes
- TCP 22: server -> workers if using the automated image-distribution helper

Do not expose UDP 8472 publicly. The install/build steps also require outbound HTTPS to fetch pinned K3s/Python dependencies and the Python base image unless you pre-cache them.

## A. On the server

```bash
cp cluster/cluster.env.example cluster/cluster.env
nano cluster/cluster.env
bash cluster/01_INSTALL_SERVER.sh
```

The server script saves the k3s node token under `operator_private/node-token`. Keep that file private; it is excluded from result packaging.

## B. On worker rack-b

Copy this package (or at least `cluster/02_INSTALL_WORKER.sh`) to worker B, then run:

```bash
export RACK_ID=rack-b
export SERVER_PRIVATE_IP=<server-private-ip>
export THIS_PRIVATE_IP=<rack-b-private-ip>
export K3S_VERSION='v1.33.1+k3s1'
bash cluster/02_INSTALL_WORKER.sh
```

The script securely prompts for the server node token.

## C. On worker rack-c

```bash
export RACK_ID=rack-c
export SERVER_PRIVATE_IP=<server-private-ip>
export THIS_PRIVATE_IP=<rack-c-private-ip>
export K3S_VERSION='v1.33.1+k3s1'
bash cluster/02_INSTALL_WORKER.sh
```

## D. Back on the server

First verify:

```bash
kubectl get nodes -o wide --show-labels
```

You must see exactly `rack-a`, `rack-b`, `rack-c`, all Ready, with three distinct private/Internal IPs.

The server needs Docker only to build the frozen benchmark image. Then:

```bash
bash cluster/03_BUILD_AND_DISTRIBUTE_IMAGE.sh
```

This builds the benchmark once, saves it, imports it into server k3s, copies it by SSH to the two worker machines and imports it there.

If SSH/scp from the server to the workers is not configured, follow `OPERATOR_CHECKLIST.md` for the manual image-copy alternative.

## E. Run the validation from the server

```bash
bash RUN_MULTIHOST_VALIDATION.sh
```

The single command performs:

1. Python environment + self-tests;
2. three-VM Kubernetes preflight and frozen-case reconstruction;
3. local-image probes on all three hosts;
4. distinct host machine-ID hash probe on all three nodes;
5. shared-medium deployment;
6. six-cell engineering pilot (excluded from analysis);
7. 60 frozen science cells;
8. paired statistical analysis;
9. result archive + SHA-256 manifest.

The runner is resumable. Running the same command again reuses accepted cells.

## Important scientific boundary

This experiment addresses **single-host Kubernetes external validity** only. It does not become physical 60-GHz validation. The planner capacities are replayed from the original N5 source package; the small VMs use lightweight execution reservations so host size does not redefine the planning problem.
