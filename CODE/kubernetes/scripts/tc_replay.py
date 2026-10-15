#!/usr/bin/env python3
"""Generate or apply one destination-specific netem rule.

Dry-run is the default. This script is an execution aid for external G2 testing;
it is not evidence that a Kubernetes or mmWave testbed has been run.
"""
from __future__ import annotations

import argparse
import ipaddress
import math
import os
import shlex
import subprocess


def build_commands(interface: str, destination: str, delay_ms: float, rate_mbit: float, loss_pct: float):
    return [
        ["tc", "qdisc", "replace", "dev", interface, "root", "handle", "1:", "prio", "bands", "3"],
        [
            "tc", "qdisc", "replace", "dev", interface, "parent", "1:3", "handle", "30:",
            "netem", "delay", f"{delay_ms}ms", "rate", f"{rate_mbit}mbit", "loss", f"{loss_pct}%",
        ],
        [
            "tc", "filter", "replace", "dev", interface, "protocol", "ip", "parent", "1:0",
            "prio", "3", "u32", "match", "ip", "dst", f"{destination}/32", "flowid", "1:3",
        ],
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interface", required=True)
    parser.add_argument("--destination", required=True, help="destination IPv4 address")
    parser.add_argument("--delay-ms", required=True, type=float)
    parser.add_argument("--rate-mbit", required=True, type=float)
    parser.add_argument("--loss-pct", default=0.0, type=float)
    parser.add_argument("--apply", action="store_true", help="execute commands; requires root")
    args = parser.parse_args()
    try:
        ipaddress.IPv4Address(args.destination)
    except ipaddress.AddressValueError as exc:
        parser.error(f"destination must be a valid IPv4 address: {exc}")
    if (
        not all(math.isfinite(value) for value in (args.delay_ms, args.rate_mbit, args.loss_pct))
        or args.delay_ms < 0
        or args.rate_mbit <= 0
        or not 0 <= args.loss_pct <= 100
    ):
        parser.error("delay, rate, and loss must be finite; delay non-negative, rate positive, and loss between 0 and 100")
    commands = build_commands(args.interface, args.destination, args.delay_ms, args.rate_mbit, args.loss_pct)
    for command in commands:
        print(shlex.join(command))
    if not args.apply:
        print("DRY RUN: no qdisc was changed")
        return 0
    if os.geteuid() != 0:
        raise SystemExit("--apply requires root")
    for command in commands:
        subprocess.run(command, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
