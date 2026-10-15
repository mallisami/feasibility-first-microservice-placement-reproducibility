# Operator checklist

Before science:

- [ ] All three machines are separate VMs/hosts.
- [ ] All three are in the same private Azure VNet/subnet or otherwise have direct private connectivity.
- [ ] `rack-a`, `rack-b`, `rack-c` have three distinct InternalIP values.
- [ ] All three nodes are x86-64 Linux.
- [ ] rack-a/server has at least ~4 GiB RAM; each 1-vCPU worker has at least ~2 GiB RAM.
- [ ] K3s/kubelet build is v1.33.1+k3s1 on all three nodes (upstream Kubernetes v1.33.1).
- [ ] TCP 6443, UDP 8472 and TCP 10250 are allowed only as needed over the private network.
- [ ] `kubectl get nodes` reports exactly three Ready nodes.
- [ ] Docker is available on the server for image build.
- [ ] Outbound HTTPS is available for K3s/PyPI/base-image retrieval, or those dependencies are already cached.
- [ ] `cluster/03_BUILD_AND_DISTRIBUTE_IMAGE.sh` completes on all nodes.
- [ ] No unrelated production workload is running on these machines.
- [ ] System clocks are synchronized (Azure/Ubuntu default NTP is acceptable; verify with `timedatectl`).

Manual image distribution if SSH helper cannot be used:

On server:

```bash
docker build --pull=false --build-arg BASE_IMAGE=python:3.12-slim \
  -t mape-cap-multihost-bench:2026-10-01 \
  frozen/EXPERIMENTS/k8s_affinity_wireless_confirmatory/benchmark
docker save mape-cap-multihost-bench:2026-10-01 -o benchmark-image.tar
sudo k3s ctr images import benchmark-image.tar
```

Copy `benchmark-image.tar` to each worker and run on each worker:

```bash
sudo k3s ctr images import benchmark-image.tar
```

Then return to the server and execute `bash RUN_MULTIHOST_VALIDATION.sh`.

After completion, return the generated `results/run-*.zip` for audit. Do not send `operator_private/node-token`.
