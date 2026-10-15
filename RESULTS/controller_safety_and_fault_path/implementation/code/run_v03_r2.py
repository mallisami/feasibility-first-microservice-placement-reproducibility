"""Run the matched R2 live-telemetry overhead campaign on Online Boutique."""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mape_cap_bplus.v03_evidence import atomic_write_json, atomic_write_text, utc_now

NS = "online-boutique"
WORKERS = ["mape-cap-bplus-worker", "mape-cap-bplus-worker2", "mape-cap-bplus-worker3"]
TRACED = [
    "checkoutservice", "currencyservice", "emailservice", "frontend",
    "paymentservice", "productcatalogservice", "recommendationservice",
]
SOURCE_RESTARTS = ["frontend", "checkoutservice", "recommendationservice", "cartservice"]
MODES = ["telemetry_off", "telemetry_on_controller_off", "telemetry_on_controller_on"]
CONN_RE = re.compile(
    r"src=(?P<src>\S+) dst=(?P<dst>\S+) sport=(?P<sport>\d+) dport=(?P<dport>\d+) "
    r"packets=(?P<req_packets>\d+) bytes=(?P<req_bytes>\d+) .*?"
    r"src=(?P<reply_src>\S+) dst=(?P<reply_dst>\S+) sport=(?P<reply_sport>\d+) "
    r"dport=(?P<reply_dport>\d+) packets=(?P<resp_packets>\d+) bytes=(?P<resp_bytes>\d+)"
)


def cmd(args: list[str], *, input_text: str | None = None, check: bool = True, timeout: int = 180) -> str:
    if args and args[0] == "kubectl" and os.environ.get("KUBE_CONTEXT"):
        args = ["kubectl", "--context", os.environ["KUBE_CONTEXT"], *args[1:]]
    result = subprocess.run(args, input=input_text, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(args)}\n{result.stderr[-2000:]}")
    return result.stdout


def kubectl(*args: str, timeout: int = 180) -> str:
    return cmd(["kubectl", *args], timeout=timeout)


def kubectl_json(*args: str) -> dict[str, Any]:
    return json.loads(kubectl(*args, "-o", "json"))


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def wait_deployment(name: str) -> None:
    kubectl("rollout", "status", f"deployment/{name}", "-n", NS, "--timeout=180s", timeout=200)


def restart(name: str) -> None:
    kubectl("rollout", "restart", f"deployment/{name}", "-n", NS)
    wait_deployment(name)


def set_tracing(enabled: bool) -> None:
    # If opentelemetrycollector is not deployed, tracing toggle is a no-op
    try:
        res = subprocess.run(["kubectl", "get", "deployment", "opentelemetrycollector", "-n", NS], capture_output=True)
        if res.returncode != 0:
            return
    except Exception:
        return
    replicas = "1" if enabled else "0"
    try:
        kubectl("scale", "deployment/opentelemetrycollector", "-n", NS, f"--replicas={replicas}")
        if enabled:
            wait_deployment("opentelemetrycollector")
            restart("opentelemetrycollector")
    except Exception:
        pass
    value = "1" if enabled else "0"
    for deployment in TRACED:
        try:
            kubectl(
                "set", "env", f"deployment/{deployment}", "-n", NS,
                f"ENABLE_TRACING={value}",
                "COLLECTOR_SERVICE_ADDR=opentelemetrycollector:4317",
                f"OTEL_SERVICE_NAME={deployment}",
                "ENABLE_PROFILER=0", "DISABLE_PROFILER=1",
            )
            wait_deployment(deployment)
        except Exception:
            pass
    if enabled:
        for deployment in SOURCE_RESTARTS:
            try:
                restart(deployment)
            except Exception:
                pass


def set_controller(enabled: bool) -> None:
    kubectl(
        "scale", "deployment/bplus-controller-v03", "-n", NS,
        f"--replicas={1 if enabled else 0}",
    )
    if enabled:
        wait_deployment("bplus-controller-v03")


def enable_conntrack_accounting() -> None:
    for node in WORKERS:
        cmd(["docker", "exec", node, "sysctl", "-w", "net.netfilter.nf_conntrack_acct=1"])


def live_maps() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    pods = kubectl_json("get", "pods", "-n", NS)
    services = kubectl_json("get", "services", "-n", NS)
    ip_to_app: dict[str, str] = {}
    app_to_node: dict[str, str] = {}
    for pod in pods["items"]:
        ip = pod.get("status", {}).get("podIP")
        app = pod.get("metadata", {}).get("labels", {}).get("app")
        node = pod.get("spec", {}).get("nodeName")
        if ip and app:
            ip_to_app[ip] = app
            if node:
                app_to_node[app] = node
    service_ip: dict[str, str] = {}
    for service in services["items"]:
        ip = service.get("spec", {}).get("clusterIP")
        if ip and ip != "None":
            service_ip[ip] = service["metadata"]["name"]
    return ip_to_app, service_ip, app_to_node


def conntrack_snapshot() -> dict[tuple[str, str, str, str], dict[str, Any]]:
    ip_to_app, service_ip, _ = live_maps()
    flows: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for node in WORKERS:
        text = cmd(["docker", "exec", node, "conntrack", "-L", "-o", "extended"], check=False)
        for line in text.splitlines():
            match = CONN_RE.search(line)
            if not match:
                continue
            item = match.groupdict()
            source = ip_to_app.get(item["src"])
            destination = service_ip.get(item["dst"])
            if not source or not destination or destination in {"kube-dns", "opentelemetrycollector"}:
                continue
            key = (item["src"], item["dst"], item["sport"], item["dport"])
            flows[key] = {
                "source": source,
                "destination": destination,
                "source_ip": item["src"],
                "service_ip": item["dst"],
                "source_port": int(item["sport"]),
                "destination_port": int(item["dport"]),
                "request_packets": int(item["req_packets"]),
                "request_bytes": int(item["req_bytes"]),
                "response_packets": int(item["resp_packets"]),
                "response_bytes": int(item["resp_bytes"]),
            }
    return flows


def flow_delta(previous: dict, current: dict, seconds: float, window: int) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, float]] = {}
    for key, item in current.items():
        old = previous.get(key, {})
        pair = (item["source"], item["destination"])
        row = grouped.setdefault(pair, {"request_packets": 0, "request_bytes": 0, "response_packets": 0, "response_bytes": 0})
        for field in row:
            delta = item[field] - int(old.get(field, 0))
            row[field] += item[field] if delta < 0 else delta
    output = []
    for (source, destination), row in sorted(grouped.items()):
        if not any(row.values()):
            continue
        output.append({
            "window": window,
            "timestamp_utc": utc_now(),
            "source": source,
            "destination": destination,
            **{field: int(value) for field, value in row.items()},
            "request_packets_per_second": row["request_packets"] / seconds,
            "request_bytes_per_second": row["request_bytes"] / seconds,
            "response_bytes_per_second": row["response_bytes"] / seconds,
            "total_bytes_per_second": (row["request_bytes"] + row["response_bytes"]) / seconds,
            "evidence_type": "kernel-conntrack-accounting",
        })
    return output


def publish_flows(flows: list[dict[str, Any]], pod_nodes: dict[str, str]) -> None:
    payload = json.dumps({"timestamp_utc": utc_now(), "flows": flows, "pod_nodes": pod_nodes}, separators=(",", ":"))
    manifest = {
        "apiVersion": "v1", "kind": "ConfigMap",
        "metadata": {"name": "bplus-live-telemetry", "namespace": NS},
        "data": {"flows.json": payload},
    }
    exists = subprocess.run(
        ["kubectl", "get", "configmap", "bplus-live-telemetry", "-n", NS],
        capture_output=True, text=True, timeout=30,
    ).returncode == 0
    if exists:
        patch = json.dumps({"data": {"flows.json": payload}}, separators=(",", ":"))
        cmd([
            "kubectl", "patch", "configmap", "bplus-live-telemetry", "-n", NS,
            "--type=merge", "-p", patch,
        ])
    else:
        cmd(["kubectl", "create", "-f", "-"], input_text=json.dumps(manifest))


def stats_snapshot() -> dict[str, dict[str, int]]:
    by_pod: dict[str, dict[str, int]] = {}
    nodes = kubectl_json("get", "nodes")
    for node in nodes["items"]:
        name = node["metadata"]["name"]
        summary = json.loads(kubectl("get", "--raw", f"/api/v1/nodes/{name}/proxy/stats/summary"))
        for pod in summary.get("pods", []):
            ref = pod.get("podRef", {})
            if ref.get("namespace") != NS:
                continue
            cpu = sum(int(c.get("cpu", {}).get("usageNanoCores") or 0) for c in pod.get("containers", []))
            memory = sum(int(c.get("memory", {}).get("workingSetBytes") or 0) for c in pod.get("containers", []))
            network = pod.get("network", {})
            by_pod[ref["name"]] = {
                "cpu_nano_cores": cpu,
                "memory_working_set_bytes": memory,
                "rx_bytes": int(network.get("rxBytes") or 0),
                "tx_bytes": int(network.get("txBytes") or 0),
            }
    return by_pod


def frontend_metrics(since_time: str, duration: float) -> tuple[dict[str, Any], str]:
    text = kubectl("logs", "-n", NS, "deployment/frontend", f"--since-time={since_time}", "--timestamps")
    latencies: list[float] = []
    responses = 0
    failures = 0
    response_bytes = 0
    operations: dict[str, int] = {}
    for line in text.splitlines():
        body = line.split(" ", 1)[-1]
        try:
            event = json.loads(body)
        except json.JSONDecodeError:
            continue
        if event.get("message") != "request complete" or event.get("http.req.path") == "/_healthz":
            continue
        responses += 1
        status = int(event.get("http.resp.status", 0))
        failures += int(status >= 400)
        response_bytes += int(event.get("http.resp.bytes", 0))
        latency = event.get("http.resp.took_ms")
        if latency is not None:
            latencies.append(float(latency))
        key = f"{event.get('http.req.method', '?')} {event.get('http.req.path', '?')}"
        operations[key] = operations.get(key, 0) + 1
    return ({
        "requests": responses,
        "errors": failures,
        "error_rate": failures / responses if responses else None,
        "throughput_requests_per_second": responses / duration,
        "response_bytes": response_bytes,
        "p50_ms": percentile(latencies, 0.50),
        "p95_ms": percentile(latencies, 0.95),
        "p99_ms": percentile(latencies, 0.99),
        "mean_ms": statistics.fmean(latencies) if latencies else None,
        "operations": operations,
        "evidence_type": "frontend-structured-request-log",
    }, text)


def retrieve_traces() -> str:
    return kubectl(
        "exec", "-n", NS, "deployment/opentelemetrycollector", "-c", "trace-reader",
        "--", "cat", "/data/traces.json", timeout=120,
    )


def value(attribute: dict[str, Any]) -> Any:
    raw = attribute.get("value", {})
    for key in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if key in raw:
            return raw[key]
    return None


def parse_traces(text: str, started_ns: int, duration: float, interval: float, mode: str) -> list[dict[str, Any]]:
    groups: dict[tuple[int, str, str, str], dict[str, Any]] = {}
    for line in text.splitlines():
        try:
            envelope = json.loads(line)
        except json.JSONDecodeError:
            continue
        for resource_span in envelope.get("resourceSpans", []):
            resources = {a["key"]: value(a) for a in resource_span.get("resource", {}).get("attributes", [])}
            source = str(resources.get("service.name", "unknown"))
            for scope in resource_span.get("scopeSpans", []):
                for span in scope.get("spans", []):
                    if int(span.get("kind", 0)) != 3:
                        continue
                    attrs = {a["key"]: value(a) for a in span.get("attributes", [])}
                    rpc_service = str(attrs.get("rpc.service") or attrs.get("server.address") or attrs.get("net.peer.name") or "unknown")
                    if "TraceService" in rpc_service or rpc_service == "opentelemetrycollector":
                        continue
                    destination = rpc_service.rsplit(".", 1)[-1].replace("Service", "service").lower()
                    known = {
                        "currencyservice": "currencyservice", "productcatalogservice": "productcatalogservice",
                        "cartservice": "cartservice", "recommendationservice": "recommendationservice",
                        "shippingservice": "shippingservice", "checkoutservice": "checkoutservice",
                        "adservice": "adservice", "paymentservice": "paymentservice", "emailservice": "emailservice",
                    }
                    destination = known.get(destination, rpc_service.split(":", 1)[0])
                    operation = str(attrs.get("rpc.method") or span.get("name") or "unknown")
                    start_ns = int(span.get("startTimeUnixNano", 0))
                    end_ns = int(span.get("endTimeUnixNano", start_ns))
                    if start_ns < started_ns or start_ns > started_ns + int(duration * 1e9):
                        continue
                    window = max(0, int(((start_ns - started_ns) / 1e9) // interval))
                    key = (window, source, destination, operation)
                    group = groups.setdefault(key, {"latencies": [], "errors": 0, "request_bytes": 0, "response_bytes": 0})
                    group["latencies"].append((end_ns - start_ns) / 1e6)
                    group["errors"] += int(span.get("status", {}).get("code", 0) == 2)
                    for attr_key, field in (("rpc.grpc.request.size", "request_bytes"), ("http.request.body.size", "request_bytes"), ("rpc.grpc.response.size", "response_bytes"), ("http.response.body.size", "response_bytes")):
                        if attrs.get(attr_key) is not None:
                            group[field] += int(attrs[attr_key])
    rows = []
    for (window, source, destination, operation), group in sorted(groups.items()):
        latencies = group.pop("latencies")
        rows.append({
            "window": window, "source": source, "destination": destination,
            "operation": operation, "workload_phase": mode,
            "requests": len(latencies), "request_rate": len(latencies) / interval,
            **group,
            "p50_ms": percentile(latencies, .50), "p95_ms": percentile(latencies, .95),
            "p99_ms": percentile(latencies, .99),
            "evidence_type": "native-opentelemetry-client-span",
        })
    return rows


def combine_telemetry(
    traces: list[dict[str, Any]], flows: list[dict[str, Any]], started: datetime,
    interval: float, mode: str,
) -> list[dict[str, Any]]:
    flow_index: dict[tuple[int, str, str], dict[str, Any]] = {}
    for flow in flows:
        key = (flow["window"], flow["source"], flow["destination"])
        target = flow_index.setdefault(key, {"request_bytes": 0, "response_bytes": 0, "request_packets": 0})
        target["request_bytes"] += flow["request_bytes"]
        target["response_bytes"] += flow["response_bytes"]
        target["request_packets"] += flow["request_packets"]
    request_totals: dict[tuple[int, str, str], int] = {}
    for trace in traces:
        key = (trace["window"], trace["source"], trace["destination"])
        request_totals[key] = request_totals.get(key, 0) + trace["requests"]
    records = []
    covered: set[tuple[int, str, str]] = set()
    for trace in traces:
        key = (trace["window"], trace["source"], trace["destination"])
        flow = flow_index.get(key, {})
        share = trace["requests"] / request_totals[key]
        record = dict(trace)
        record["timestamp_utc"] = datetime.fromtimestamp(
            started.timestamp() + trace["window"] * interval, timezone.utc,
        ).isoformat().replace("+00:00", "Z")
        if not record["request_bytes"]:
            record["request_bytes"] = round(float(flow.get("request_bytes", 0)) * share)
        if not record["response_bytes"]:
            record["response_bytes"] = round(float(flow.get("response_bytes", 0)) * share)
        record["request_rate_basis"] = "native client spans"
        records.append(record)
        covered.add(key)
    for key, flow in flow_index.items():
        if key in covered:
            continue
        window, source, destination = key
        records.append({
            "window": window,
            "timestamp_utc": datetime.fromtimestamp(
                started.timestamp() + window * interval, timezone.utc,
            ).isoformat().replace("+00:00", "Z"),
            "source": source, "destination": destination,
            "operation": "transport-uninstrumented", "workload_phase": mode,
            "requests": None, "request_rate": flow["request_packets"] / interval,
            "request_rate_basis": "transport packets (request count unavailable)",
            "request_bytes": flow["request_bytes"], "response_bytes": flow["response_bytes"],
            "p50_ms": None, "p95_ms": None, "p99_ms": None, "errors": None,
            "evidence_type": "kernel-conntrack-accounting",
        })
    return sorted(records, key=lambda row: (row["window"], row["source"], row["destination"], row["operation"]))


def summarize_resources(samples: list[dict[str, dict[str, int]]], duration: float) -> dict[str, Any]:
    cpu = [sum(p["cpu_nano_cores"] for p in sample.values()) for sample in samples]
    memory = [sum(p["memory_working_set_bytes"] for p in sample.values()) for sample in samples]
    first, last = samples[0], samples[-1]
    common = set(first) & set(last)
    rx = sum(max(0, last[p]["rx_bytes"] - first[p]["rx_bytes"]) for p in common)
    tx = sum(max(0, last[p]["tx_bytes"] - first[p]["tx_bytes"]) for p in common)
    return {
        "mean_cpu_cores": statistics.fmean(cpu) / 1e9,
        "max_cpu_cores": max(cpu) / 1e9,
        "mean_memory_mib": statistics.fmean(memory) / 1024**2,
        "max_memory_mib": max(memory) / 1024**2,
        "network_rx_bytes": rx, "network_tx_bytes": tx,
        "network_bytes_per_second": (rx + tx) / duration,
    }


def assert_healthy(include_telemetry: bool, include_controller: bool) -> dict[str, Any]:
    pods = kubectl_json("get", "pods", "-n", NS)
    relevant = []
    for pod in pods["items"]:
        app = pod.get("metadata", {}).get("labels", {}).get("app")
        if app == "opentelemetrycollector" and not include_telemetry:
            continue
        if app == "bplus-controller-v03" and not include_controller:
            continue
        statuses = pod.get("status", {}).get("containerStatuses", [])
        relevant.append({
            "pod": pod["metadata"]["name"], "app": app,
            "phase": pod.get("status", {}).get("phase"),
            "ready": bool(statuses) and all(c.get("ready", False) for c in statuses),
            "restarts": sum(c.get("restartCount", 0) for c in statuses),
        })
    healthy = all(p["phase"] == "Running" and p["ready"] for p in relevant)
    return {"healthy": healthy, "pods": relevant}


def run_cell(run_root: Path, replicate: int, mode: str, duration: int, interval: int) -> dict[str, Any]:
    telemetry = mode != "telemetry_off"
    controller = mode == "telemetry_on_controller_on"
    cell = run_root / "raw" / "r2" / f"replicate-{replicate:02d}-{mode}"
    cell.mkdir(parents=True, exist_ok=False)
    set_controller(False)
    set_tracing(telemetry)
    restart("loadgenerator")
    if controller:
        _, _, pod_nodes = live_maps()
        publish_flows([], pod_nodes)
    set_controller(controller)
    time.sleep(5)
    started = datetime.now(timezone.utc)
    started_utc = started.isoformat().replace("+00:00", "Z")
    started_ns = int(started.timestamp() * 1e9)
    samples: list[dict[str, dict[str, int]]] = []
    all_flows: list[dict[str, Any]] = []
    previous = conntrack_snapshot() if telemetry else {}
    deadline = time.monotonic() + duration
    window = 0
    while time.monotonic() < deadline:
        samples.append(stats_snapshot())
        if telemetry:
            current = conntrack_snapshot()
            rows = flow_delta(previous, current, interval, window)
            _, _, pod_nodes = live_maps()
            publish_flows(rows, pod_nodes)
            all_flows.extend(rows)
            previous = current
        window += 1
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(interval, remaining))
    samples.append(stats_snapshot())
    time.sleep(2 if telemetry else 0)
    metrics, frontend_log = frontend_metrics(started_utc, duration)
    locust_log = kubectl("logs", "-n", NS, "deployment/loadgenerator", "-c", "main", f"--since-time={started_utc}")
    trace_text = retrieve_traces() if telemetry else ""
    trace_rows = parse_traces(trace_text, started_ns, duration, interval, mode) if telemetry else []
    temporal = combine_telemetry(trace_rows, all_flows, started, interval, mode) if telemetry else []
    controller_log = kubectl("logs", "-n", NS, "deployment/bplus-controller-v03", f"--since-time={started_utc}") if controller else ""
    health = assert_healthy(telemetry, controller)
    accepted = health["healthy"] and metrics["requests"] > 0 and (not telemetry or len(trace_rows) > 0)
    result = {
        "replicate": replicate, "mode": mode, "started_utc": started_utc,
        "completed_utc": utc_now(), "duration_seconds": duration, "interval_seconds": interval,
        "accepted": accepted, "application": metrics,
        "resources": summarize_resources(samples, duration),
        "transport_flow_windows": all_flows,
        "native_trace_windows": trace_rows,
        "temporal_telemetry": temporal,
        "health": health,
        "controller_actions": sum('"action": "relocate"' in line for line in controller_log.splitlines()),
        "provenance": {
            "telemetry": "native Online Boutique OpenTelemetry spans plus kernel conntrack byte accounting" if telemetry else "disabled",
            "controller": "in-cluster persistent-window placement controller consuming live flow ConfigMap" if controller else "disabled",
        },
    }
    atomic_write_json(cell / "result.json", result)
    atomic_write_json(cell / "resource-samples.json", samples)
    atomic_write_text(cell / "frontend.log", frontend_log)
    atomic_write_text(cell / "loadgenerator.log", locust_log)
    if telemetry:
        atomic_write_text(cell / "otel-traces.jsonl", trace_text)
    if controller:
        atomic_write_text(cell / "controller.log", controller_log)
    if not accepted:
        raise RuntimeError(f"R2 cell failed acceptance: replicate={replicate}, mode={mode}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--replicates", type=int, default=3)
    parser.add_argument("--duration-seconds", type=int, default=60)
    parser.add_argument("--interval-seconds", type=int, default=5)
    args = parser.parse_args()
    if args.replicates < 1 or args.duration_seconds < 20 or args.interval_seconds < 2:
        parser.error("replicates >= 1, duration >= 20, and interval >= 2 are required")
    run_root = args.run_root.resolve()
    (run_root / "raw" / "r2").mkdir(parents=True, exist_ok=True)
    enable_conntrack_accounting()
    kubectl("apply", "-f", "kubernetes/manifests/online-boutique-otel-v03.yaml")
    results = []
    try:
        for replicate in range(1, args.replicates + 1):
            for mode in MODES:
                print(f"R2 replicate {replicate}/{args.replicates}: {mode}", flush=True)
                results.append(run_cell(run_root, replicate, mode, args.duration_seconds, args.interval_seconds))
    finally:
        set_controller(False)
    summary = {
        "completed_utc": utc_now(), "replicates": args.replicates,
        "cells": len(results), "accepted_cells": sum(r["accepted"] for r in results),
        "modes": {
            mode: {
                "mean_p95_ms": statistics.fmean(r["application"]["p95_ms"] for r in results if r["mode"] == mode),
                "mean_throughput_rps": statistics.fmean(r["application"]["throughput_requests_per_second"] for r in results if r["mode"] == mode),
                "mean_cpu_cores": statistics.fmean(r["resources"]["mean_cpu_cores"] for r in results if r["mode"] == mode),
                "mean_memory_mib": statistics.fmean(r["resources"]["mean_memory_mib"] for r in results if r["mode"] == mode),
            } for mode in MODES
        },
    }
    atomic_write_json(run_root / "derived" / "r2-summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
