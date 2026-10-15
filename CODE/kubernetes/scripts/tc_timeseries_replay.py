#!/usr/bin/env python3
"""Replay a destination-specific time series with Linux tc/HTB/netem.

Dry-run is the default. The input CSV columns are:
offset_seconds,destination_cidr,delay_ms,rate_mbit,loss_percent

This replays effective network states. It is not a mmWave PHY simulator.
"""
from __future__ import annotations

import argparse
import csv
import ipaddress
import json
import math
import os
from pathlib import Path
import shlex
import subprocess
import time


def load_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"offset_seconds", "destination_cidr", "delay_ms", "rate_mbit", "loss_percent"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"schedule is missing columns: {sorted(required - set(reader.fieldnames or []))}")
        for index, row in enumerate(reader):
            cidr = ipaddress.ip_network(row["destination_cidr"], strict=False)
            if cidr.version != 4:
                raise ValueError("only IPv4 schedules are supported")
            parsed = {
                "index": index,
                "offset_seconds": float(row["offset_seconds"]),
                "destination_cidr": str(cidr),
                "delay_ms": float(row["delay_ms"]),
                "rate_mbit": float(row["rate_mbit"]),
                "loss_percent": float(row["loss_percent"]),
            }
            numeric = (
                parsed["offset_seconds"], parsed["delay_ms"],
                parsed["rate_mbit"], parsed["loss_percent"],
            )
            if (
                not all(math.isfinite(value) for value in numeric)
                or parsed["offset_seconds"] < 0
                or parsed["delay_ms"] < 0
                or parsed["rate_mbit"] <= 0
                or not 0 <= parsed["loss_percent"] <= 100
            ):
                raise ValueError(f"invalid schedule row {index}: {parsed}")
            rows.append(parsed)
    rows.sort(key=lambda row: (row["offset_seconds"], row["destination_cidr"], row["index"]))
    seen: set[tuple[float, str]] = set()
    for row in rows:
        key = (row["offset_seconds"], row["destination_cidr"])
        if key in seen:
            raise ValueError(f"duplicate schedule time/destination: {key}")
        seen.add(key)
    destinations = sorted({row["destination_cidr"] for row in rows})
    for destination in destinations:
        first = min(row["offset_seconds"] for row in rows if row["destination_cidr"] == destination)
        if abs(first) > 1e-12:
            raise ValueError(f"the first row for {destination} must start at offset 0")
    return rows


def command_text(command: list[str]) -> str:
    return shlex.join(command)


def apply(command: list[str], execute: bool) -> None:
    print(command_text(command))
    if execute:
        subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interface", required=True)
    parser.add_argument("--schedule", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--log", type=Path, default=Path("tc_timeseries_replay_log.json"))
    parser.add_argument("--default-rate-mbit", type=float, default=10000.0)
    args = parser.parse_args()
    if args.apply and (not hasattr(os, "geteuid") or os.geteuid() != 0):
        raise SystemExit("--apply requires root on Linux")
    if not math.isfinite(args.default_rate_mbit) or args.default_rate_mbit <= 0:
        parser.error("default-rate-mbit must be positive and finite")
    rows = load_rows(args.schedule)
    destinations = sorted({row["destination_cidr"] for row in rows})
    class_ids = {destination: 10 + index for index, destination in enumerate(destinations)}

    setup = [
        ["tc", "qdisc", "replace", "dev", args.interface, "root", "handle", "1:", "htb", "default", "999"],
        ["tc", "class", "replace", "dev", args.interface, "parent", "1:", "classid", "1:999", "htb", "rate", f"{args.default_rate_mbit}mbit"],
    ]
    for command in setup:
        apply(command, args.apply)
    for destination, minor in class_ids.items():
        initial = next(row for row in rows if row["destination_cidr"] == destination)
        apply(["tc", "class", "replace", "dev", args.interface, "parent", "1:", "classid", f"1:{minor}", "htb", "rate", f"{initial['rate_mbit']}mbit"], args.apply)
        apply(["tc", "qdisc", "replace", "dev", args.interface, "parent", f"1:{minor}", "handle", f"{minor}0:", "netem", "delay", f"{initial['delay_ms']}ms", "loss", f"{initial['loss_percent']}%"], args.apply)
        apply(["tc", "filter", "replace", "dev", args.interface, "protocol", "ip", "parent", "1:0", "prio", str(minor), "u32", "match", "ip", "dst", destination, "flowid", f"1:{minor}"], args.apply)

    started = time.monotonic()
    applied_rows: list[dict] = []
    for row in rows:
        if args.apply:
            wait = row["offset_seconds"] - (time.monotonic() - started)
            if wait > 0:
                time.sleep(wait)
        minor = class_ids[row["destination_cidr"]]
        commands = [
            ["tc", "class", "replace", "dev", args.interface, "parent", "1:", "classid", f"1:{minor}", "htb", "rate", f"{row['rate_mbit']}mbit"],
            ["tc", "qdisc", "replace", "dev", args.interface, "parent", f"1:{minor}", "handle", f"{minor}0:", "netem", "delay", f"{row['delay_ms']}ms", "loss", f"{row['loss_percent']}%"],
        ]
        for command in commands:
            apply(command, args.apply)
        applied_rows.append({**row, "commands": [command_text(command) for command in commands], "executed": args.apply})

    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.write_text(json.dumps({"interface": args.interface, "executed": args.apply, "rows": applied_rows}, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote replay log: {args.log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
