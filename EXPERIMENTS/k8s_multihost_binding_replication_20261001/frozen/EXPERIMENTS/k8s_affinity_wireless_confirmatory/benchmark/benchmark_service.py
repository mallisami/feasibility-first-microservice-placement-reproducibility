#!/usr/bin/env python3
"""Minimal standard-library HTTP microservice + deterministic flow generator.

The process exposes:
  GET  /healthz
  GET  /metrics
  POST /data        (benchmark payload receiver)
  POST /configure   (replace outgoing flow config and schedule synchronized run)
  POST /stop        (stop current generation)

No third-party Python packages are required inside the benchmark image.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

PORT = int(os.environ.get("PORT", "8080"))
SERVICE_ID = os.environ.get("SERVICE_ID", "unknown")
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "3.0"))
MAX_LATENCY_SAMPLES = 10000

_lock = threading.RLock()
_generation = 0
_config: dict[str, Any] = {"run_id": None, "start_epoch": None, "stop_epoch": None, "flows": []}
_metrics: dict[str, Any] = {}
_received = {"requests": 0, "bytes": 0}


def _fresh_flow_metrics(flow: dict[str, Any]) -> dict[str, Any]:
    return {
        "flow_id": str(flow["flow_id"]),
        "destination": str(flow["destination"]),
        "attempted": 0,
        "success": 0,
        "errors": 0,
        "bytes_attempted": 0,
        "bytes_success": 0,
        "latencies_ms": [],
        "last_error": None,
    }


def _reset_metrics_locked(flows: list[dict[str, Any]]) -> None:
    global _metrics, _received
    _metrics = {str(f["flow_id"]): _fresh_flow_metrics(f) for f in flows}
    _received = {"requests": 0, "bytes": 0}


def _sender(flow: dict[str, Any], generation: int) -> None:
    flow_id = str(flow["flow_id"])
    destination = str(flow["destination"])
    rate = float(flow["rate_rps"])
    payload_bytes = int(flow["payload_bytes"])
    if not math.isfinite(rate) or rate <= 0 or payload_bytes < 1:
        return
    payload = b"x" * payload_bytes
    with _lock:
        start_epoch = float(_config["start_epoch"])
        stop_epoch = float(_config["stop_epoch"])
    while time.time() < start_epoch:
        with _lock:
            if generation != _generation:
                return
        time.sleep(min(0.05, max(0.0, start_epoch - time.time())))
    period = 1.0 / rate
    next_send = start_epoch
    while time.time() < stop_epoch:
        with _lock:
            if generation != _generation:
                return
        now = time.time()
        if now < next_send:
            time.sleep(min(0.05, next_send - now))
            continue
        started = time.perf_counter()
        ok = False
        err = None
        try:
            req = urllib.request.Request(
                destination,
                data=payload,
                method="POST",
                headers={"Content-Type": "application/octet-stream", "Connection": "close"},
            )
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                resp.read(32)
                ok = 200 <= int(resp.status) < 300
        except Exception as exc:  # network outcome, retained in metrics
            err = f"{type(exc).__name__}: {exc}"
        latency_ms = (time.perf_counter() - started) * 1000.0
        with _lock:
            row = _metrics.get(flow_id)
            if row is None or generation != _generation:
                return
            row["attempted"] += 1
            row["bytes_attempted"] += payload_bytes
            if ok:
                row["success"] += 1
                row["bytes_success"] += payload_bytes
            else:
                row["errors"] += 1
                row["last_error"] = err
            samples = row["latencies_ms"]
            if len(samples) < MAX_LATENCY_SAMPLES:
                samples.append(latency_ms)
        next_send += period
        # Avoid an unbounded catch-up burst after a long timeout.
        if next_send < time.time() - period:
            next_send = time.time()


def configure(payload: dict[str, Any]) -> dict[str, Any]:
    global _generation, _config
    flows = list(payload.get("flows") or [])
    start_epoch = float(payload["start_epoch"])
    stop_epoch = float(payload["stop_epoch"])
    if stop_epoch <= start_epoch:
        raise ValueError("stop_epoch must be greater than start_epoch")
    with _lock:
        _generation += 1
        generation = _generation
        _config = {
            "run_id": str(payload.get("run_id")),
            "start_epoch": start_epoch,
            "stop_epoch": stop_epoch,
            "flows": flows,
        }
        _reset_metrics_locked(flows)
    for flow in flows:
        threading.Thread(target=_sender, args=(flow, generation), daemon=True).start()
    return {"configured": True, "service_id": SERVICE_ID, "generation": generation, "flow_count": len(flows)}


def stop() -> dict[str, Any]:
    global _generation
    with _lock:
        _generation += 1
        return {"stopped": True, "service_id": SERVICE_ID, "generation": _generation}


def snapshot() -> dict[str, Any]:
    with _lock:
        flows = json.loads(json.dumps(_metrics))
        received = dict(_received)
        cfg = dict(_config)
    return {
        "service_id": SERVICE_ID,
        "time_epoch": time.time(),
        "config": cfg,
        "flows": flows,
        "received": received,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "mape-cap-confirm-bench/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _json(self, code: int, payload: Any) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._json(200, {"ok": True, "service_id": SERVICE_ID})
        elif self.path == "/metrics":
            self._json(200, snapshot())
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if self.path == "/data":
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
            with _lock:
                _received["requests"] += 1
                _received["bytes"] += length - remaining
            self._json(200, {"ok": True})
            return
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode() or "{}")
            if self.path == "/configure":
                self._json(200, configure(payload))
            elif self.path == "/stop":
                self._json(200, stop())
            else:
                self._json(404, {"error": "not found"})
        except Exception as exc:
            self._json(400, {"error": f"{type(exc).__name__}: {exc}"})


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(json.dumps({"event": "started", "service_id": SERVICE_ID, "port": PORT}), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
