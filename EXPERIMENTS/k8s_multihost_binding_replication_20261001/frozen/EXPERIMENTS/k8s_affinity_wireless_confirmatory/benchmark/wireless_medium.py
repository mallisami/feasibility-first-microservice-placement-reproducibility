#!/usr/bin/env python3
"""Deterministic shared-medium emulator for the Kubernetes confirmation.

Cross-rack benchmark requests are proxied through this service. Requests that
belong to the same frozen conflict group serialize on one in-process medium
for that group. The service time is payload_bits / directed_goodput divided
by the declared conflict-budget duty fraction. This maps an airtime budget in
a 60 s window to saturation at utilization 1.0 while preserving directed
link goodput.

Amendment 2026-09-20 (multi-scenario extension): generalized from a single
global shared medium (correct only for conflict-dense's single "cg-shared"
conflict group) to one medium per conflict group, so partial-blockage and
persistent-degradation -- which the frozen wireless trace defines with
directed per-rack-pair conflict groups cg-ab/cg-ac/cg-bc rather than one
shared group -- can be emulated with the same serialization semantics
without changing conflict-dense's behavior at all. The single-group scalar
API (`duty_fraction`, no `group` on /transmit) is preserved unchanged for
backward compatibility: it is treated as one group named "default".

This is an in-cluster emulator of the manuscript's shared-airtime constraint,
not a physical RF or MAC implementation.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

PORT = int(os.environ.get("PORT", "8080"))
FORWARD_TIMEOUT = float(os.environ.get("FORWARD_TIMEOUT_SECONDS", "5.0"))
MAX_SAMPLES = 20000
DEFAULT_GROUP = "default"

_state_lock = threading.RLock()
_medium_locks: dict[str, threading.Lock] = {}
_generation = 0
_config: dict[str, Any] = {
    "run_id": None,
    "duty_fractions": {DEFAULT_GROUP: 0.25},
    "configured_utc": None,
}
_metrics: dict[str, Any] = {}
_group_metrics: dict[str, dict[str, Any]] = {}


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fresh_metrics() -> dict[str, Any]:
    return {
        "requests": 0,
        "success": 0,
        "errors": 0,
        "bytes": 0,
        "modeled_airtime_seconds": 0.0,
        "serialized_service_seconds": 0.0,
        "queue_wait_ms": [],
        "service_ms": [],
        "end_to_end_ms": [],
        "last_error": None,
    }


def _lock_for(group: str) -> threading.Lock:
    with _state_lock:
        lock = _medium_locks.get(group)
        if lock is None:
            lock = threading.Lock()
            _medium_locks[group] = lock
        return lock


def configure(payload: dict[str, Any]) -> dict[str, Any]:
    global _generation, _config, _metrics, _group_metrics
    if "duty_fractions" in payload:
        duty_fractions = {str(k): float(v) for k, v in dict(payload["duty_fractions"]).items()}
    else:
        # Backward-compatible single-group scalar form.
        duty_fractions = {DEFAULT_GROUP: float(payload["duty_fraction"])}
    if not duty_fractions:
        raise ValueError("at least one duty_fraction is required")
    for group, duty in duty_fractions.items():
        if not math.isfinite(duty) or duty <= 0.0 or duty > 1.0:
            raise ValueError(f"duty_fraction for group {group!r} must be in (0, 1]")
    # Invalidate queued requests first. Queued old-generation requests abort as
    # soon as they acquire their group's medium. Then acquire/release every
    # known medium once so no old in-service transmission can overlap the new
    # cell.
    with _state_lock:
        _generation += 1
        generation = _generation
        known_groups = set(_medium_locks) | set(duty_fractions)
    for group in known_groups:
        with _lock_for(group):
            pass
    with _state_lock:
        _config = {
            "run_id": str(payload.get("run_id")),
            "duty_fractions": duty_fractions,
            "configured_utc": _now_iso(),
        }
        _metrics = _fresh_metrics()
        _group_metrics = {group: _fresh_metrics() for group in duty_fractions}
    return {"configured": True, "generation": generation, **_config}


def snapshot() -> dict[str, Any]:
    with _state_lock:
        return {
            "time_epoch": time.time(),
            "generation": _generation,
            "config": json.loads(json.dumps(_config)),
            "metrics": json.loads(json.dumps(_metrics)),
            "group_metrics": json.loads(json.dumps(_group_metrics)),
        }


def _append_sample(store: dict[str, Any], key: str, value: float) -> None:
    arr = store[key]
    if len(arr) < MAX_SAMPLES:
        arr.append(float(value))


def transmit(*, dst: str, goodput_bps: float, latency_ms: float, payload: bytes, group: str = DEFAULT_GROUP) -> tuple[int, dict[str, Any]]:
    if not dst or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-." for c in dst):
        raise ValueError("invalid destination service name")
    if not math.isfinite(goodput_bps) or goodput_bps <= 0:
        raise ValueError("goodput_bps must be positive")
    if not math.isfinite(latency_ms) or latency_ms < 0:
        raise ValueError("latency_ms must be nonnegative")
    if not group or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in group):
        raise ValueError("invalid conflict group name")
    with _state_lock:
        generation = _generation
        duty = _config["duty_fractions"].get(group)
        if duty is None:
            raise ValueError(f"unconfigured conflict group: {group!r}")
    modeled_airtime = len(payload) * 8.0 / goodput_bps
    serialized_service = modeled_airtime / duty
    started = time.perf_counter()
    queue_started = started
    ok = False
    err = None
    status = 502
    queue_wait = service_elapsed = 0.0
    medium_lock = _lock_for(group)
    try:
        with medium_lock:
            acquired = time.perf_counter()
            queue_wait = acquired - queue_started
            # Do not let a reconfiguration mix two cells while a request was queued.
            with _state_lock:
                if generation != _generation:
                    raise RuntimeError("medium reconfigured while request was queued")
            time.sleep(serialized_service)
            service_elapsed = time.perf_counter() - acquired
        with _state_lock:
            if generation != _generation:
                raise RuntimeError("medium reconfigured during request service")
        # Propagation does not occupy the shared medium.
        if latency_ms > 0:
            time.sleep(latency_ms / 1000.0)
        req = urllib.request.Request(
            f"http://{dst}:8080/data",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/octet-stream", "Connection": "close"},
        )
        with urllib.request.urlopen(req, timeout=FORWARD_TIMEOUT) as resp:
            resp.read(32)
            status = int(resp.status)
            ok = 200 <= status < 300
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
    total = time.perf_counter() - started
    with _state_lock:
        if generation == _generation:
            for store in (_metrics, _group_metrics.get(group)):
                if store is None:
                    continue
                store["requests"] += 1
                store["bytes"] += len(payload)
                store["modeled_airtime_seconds"] += modeled_airtime
                store["serialized_service_seconds"] += serialized_service
                if ok:
                    store["success"] += 1
                else:
                    store["errors"] += 1
                    store["last_error"] = err
                _append_sample(store, "queue_wait_ms", queue_wait * 1000.0)
                _append_sample(store, "service_ms", service_elapsed * 1000.0)
                _append_sample(store, "end_to_end_ms", total * 1000.0)
    return (200 if ok else 502), {
        "ok": ok,
        "upstream_status": status,
        "group": group,
        "queue_wait_ms": queue_wait * 1000.0,
        "modeled_airtime_ms": modeled_airtime * 1000.0,
        "serialized_service_ms": serialized_service * 1000.0,
        "error": err,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "mape-cap-wireless-medium/1.2"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _json(self, code: int, payload: Any) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._json(200, {"ok": True})
        elif self.path == "/metrics":
            self._json(200, snapshot())
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        length = int(self.headers.get("Content-Length", "0") or 0)
        if parsed.path == "/configure":
            raw = self.rfile.read(length) if length else b"{}"
            try:
                self._json(200, configure(json.loads(raw.decode() or "{}")))
            except Exception as exc:
                self._json(400, {"error": f"{type(exc).__name__}: {exc}"})
            return
        if parsed.path != "/transmit":
            self._json(404, {"error": "not found"})
            return
        payload = self.rfile.read(length) if length else b""
        query = urllib.parse.parse_qs(parsed.query)
        try:
            dst = query["dst"][0]
            goodput = float(query["goodput_bps"][0])
            latency = float(query["latency_ms"][0])
            group = query.get("group", [DEFAULT_GROUP])[0]
            code, body = transmit(dst=dst, goodput_bps=goodput, latency_ms=latency, payload=payload, group=group)
            self._json(code, body)
        except Exception as exc:
            self._json(400, {"error": f"{type(exc).__name__}: {exc}"})


def main() -> None:
    global _metrics, _group_metrics
    _metrics = _fresh_metrics()
    _group_metrics = {DEFAULT_GROUP: _fresh_metrics()}
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(json.dumps({"event": "started", "component": "wireless-medium", "port": PORT}), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
