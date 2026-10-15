#!/usr/bin/env python3
"""Pod-local control client used via kubectl exec -i."""
from __future__ import annotations
import json, sys, urllib.request

def call(path: str, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(f"http://127.0.0.1:8080{path}", data=data, method="GET" if data is None else "POST", headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        sys.stdout.write(resp.read().decode())

cmd = sys.argv[1]
if cmd == "metrics":
    call("/metrics")
elif cmd == "health":
    call("/healthz")
elif cmd == "stop":
    call("/stop", {})
elif cmd == "configure":
    call("/configure", json.load(sys.stdin))
else:
    raise SystemExit(f"unknown command: {cmd}")
