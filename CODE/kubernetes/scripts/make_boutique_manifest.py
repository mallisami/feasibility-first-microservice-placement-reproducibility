"""Transform the upstream Online Boutique v0.10.1 release manifest for the
mape-cap-bplus Kind cluster.

Deliberately minimal edits, so the deployed topology stays faithful to upstream:
  1. everything moves into the `online-boutique` namespace
  2. imagePullPolicy: IfNotPresent, so preloaded images are used and nodes do
     not re-pull from gcr.io
  3. the frontend Service is downgraded from LoadBalancer to ClusterIP (Kind
     has no cloud LB); external-facing frontend-external is dropped
  4. loadgenerator is split into its own file so the core topology can be
     brought up and verified before traffic is applied

Service call graph, container images, ports, env vars, probes and resource
requests/limits are left exactly as upstream ships them.
"""
import sys
import yaml

TMP = "C:/Users/user/AppData/Local/Temp"
SRC = f"{TMP}/ob-upstream.yaml"
OUT_CORE = f"{TMP}/boutique-core.yaml"
OUT_LOAD = f"{TMP}/boutique-loadgen.yaml"
NS = "online-boutique"

docs = [d for d in yaml.safe_load_all(open(SRC)) if d]

core, loadgen = [], []
changes = []

for d in docs:
    kind = d.get("kind")
    name = d.get("metadata", {}).get("name")

    # 4. external LB service is meaningless on Kind
    if kind == "Service" and name == "frontend-external":
        changes.append(f"DROP  Service/{name} (LoadBalancer, no cloud LB on Kind)")
        continue

    # 1. namespace
    d.setdefault("metadata", {})["namespace"] = NS

    # 3. LoadBalancer -> ClusterIP
    if kind == "Service" and d.get("spec", {}).get("type") == "LoadBalancer":
        d["spec"].pop("type")
        changes.append(f"EDIT  Service/{name}: LoadBalancer -> ClusterIP")

    # 2. imagePullPolicy on every container and initContainer
    spec = d.get("spec", {}).get("template", {}).get("spec") if kind == "Deployment" else None
    if spec:
        for key in ("initContainers", "containers"):
            for c in spec.get(key, []):
                c["imagePullPolicy"] = "IfNotPresent"

    (loadgen if name == "loadgenerator" else core).append(d)

ns_doc = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": NS}}

with open(OUT_CORE, "w") as f:
    yaml.safe_dump_all([ns_doc] + core, f, default_flow_style=False, sort_keys=False)
with open(OUT_LOAD, "w") as f:
    yaml.safe_dump_all(loadgen, f, default_flow_style=False, sort_keys=False)

for c in changes:
    print(c)
print()
print(f"core    : {len(core)} docs -> {OUT_CORE}")
print(f"loadgen : {len(loadgen)} docs -> {OUT_LOAD}")
print()
deps = [d["metadata"]["name"] for d in core if d.get("kind") == "Deployment"]
svcs = [d["metadata"]["name"] for d in core if d.get("kind") == "Service"]
print("Deployments:", ", ".join(sorted(deps)))
print("Services   :", ", ".join(sorted(svcs)))
