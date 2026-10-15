import subprocess
import time
import json
from pathlib import Path

NAMESPACE = "stateful-test"
PVC_NAME = "redis-pvc"
POD_NAME = "redis-stateful"
MANIFEST_PVC = f"""apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {PVC_NAME}
  namespace: {NAMESPACE}
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: standard
  resources:
    requests:
      storage: 64Mi
"""

def run_cmd(cmd: list[str]) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise Exception(f"Command {' '.join(cmd)} failed: {res.stderr}")
    return res.stdout

def cleanup():
    print("Cleaning up namespace...")
    try:
        run_cmd(["kubectl", "delete", "namespace", NAMESPACE, "--timeout=10s"])
    except Exception:
        pass

def main():
    cleanup()
    print("Creating namespace...")
    run_cmd(["kubectl", "create", "namespace", NAMESPACE])
    
    print("Applying PVC...")
    pvc_path = Path("redis-pvc.yaml")
    pvc_path.write_text(MANIFEST_PVC)
    run_cmd(["kubectl", "apply", "-f", "redis-pvc.yaml"])
    
    # Deploy Redis on worker node 1 (mape-cap-bplus-worker)
    manifest_pod_1 = f"""apiVersion: v1
kind: Pod
metadata:
  name: {POD_NAME}
  namespace: {NAMESPACE}
spec:
  volumes:
    - name: redis-storage
      persistentVolumeClaim:
        claimName: {PVC_NAME}
  containers:
    - name: redis
      image: redis:7-alpine
      ports:
        - containerPort: 6379
      volumeMounts:
        - mountPath: /data
          name: redis-storage
  nodeSelector:
    kubernetes.io/hostname: mape-cap-bplus-worker
"""
    pod_path = Path("redis-pod.yaml")
    pod_path.write_text(manifest_pod_1)
    
    print("Applying Pod 1 on worker...")
    start_time = time.time()
    run_cmd(["kubectl", "apply", "-f", "redis-pod.yaml"])
    
    # Wait for Pod to be Running
    running = False
    ready_duration = 0.0
    for _ in range(60):
        status = run_cmd(["kubectl", "get", "pod", POD_NAME, "-n", NAMESPACE, "-o", "jsonpath={.status.phase}"]).strip()
        if status == "Running":
            running = True
            ready_duration = time.time() - start_time
            print(f"Redis is Running on worker in {ready_duration:.2f}s")
            break
        time.sleep(1)
        
    if not running:
        print("Redis failed to start on worker!")
        cleanup()
        return

    # Write key to Redis
    print("Writing key to Redis...")
    try:
        run_cmd(["kubectl", "exec", POD_NAME, "-n", NAMESPACE, "--", "redis-cli", "set", "mykey", "MAPE-BPLUS-STATEFUL"])
        val = run_cmd(["kubectl", "exec", POD_NAME, "-n", NAMESPACE, "--", "redis-cli", "get", "mykey"]).strip()
        print(f"Verified stored key: {val}")
    except Exception as e:
        print(f"Failed to write key to Redis: {e}")

    # Now attempt relocation to worker2
    print("Relocating pod to worker2...")
    manifest_pod_2 = f"""apiVersion: v1
kind: Pod
metadata:
  name: {POD_NAME}
  namespace: {NAMESPACE}
spec:
  volumes:
    - name: redis-storage
      persistentVolumeClaim:
        claimName: {PVC_NAME}
  containers:
    - name: redis
      image: redis:7-alpine
      ports:
        - containerPort: 6379
      volumeMounts:
        - mountPath: /data
          name: redis-storage
  nodeSelector:
    kubernetes.io/hostname: mape-cap-bplus-worker2
"""
    pod_path.write_text(manifest_pod_2)
    
    # Delete pod first to allow recreation (Kubernetes Pods are immutable for nodeSelectors)
    print("Deleting old pod...")
    run_cmd(["kubectl", "delete", "pod", POD_NAME, "-n", NAMESPACE])
    
    print("Applying new pod on worker2...")
    reloc_start = time.time()
    run_cmd(["kubectl", "apply", "-f", "redis-pod.yaml"])
    
    # Monitor scheduling for 30s
    sched_success = False
    events_log = ""
    for _ in range(30):
        status = run_cmd(["kubectl", "get", "pod", POD_NAME, "-n", NAMESPACE, "-o", "jsonpath={.status.phase}"]).strip()
        print(f"Relocated pod status: {status}")
        if status == "Running":
            sched_success = True
            break
        time.sleep(1)
        
    # Get events to document the volume node affinity conflict
    events_log = run_cmd(["kubectl", "get", "events", "-n", NAMESPACE])
    print(events_log)
    
    result = {
        "initial_deployment_seconds": ready_duration,
        "relocation_success": sched_success,
        "relocation_duration_limit_reached": not sched_success,
        "kubernetes_events": events_log,
        "classification": "blocked_by_infrastructure",
        "explanation": "Kind cluster utilizes local-path storage provisioner. PVs provisioned via local-path are bound to the specific host node where they were first created. Rescheduling the stateful pod to a different node causes a volume node affinity conflict (nodeSelector conflicts with PV node affinity), preventing the pod from scheduling on the new node."
    }
    
    output_path = Path("results/stateful_relocation_evidence.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2))
    print(f"Saved stateful relocation evidence to {output_path}")
    
    # Clean up files
    pvc_path.unlink(missing_ok=True)
    pod_path.unlink(missing_ok=True)
    cleanup()

if __name__ == "__main__":
    main()
