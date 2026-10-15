#!/usr/bin/env python3
"""Check/pull the exact container images required by the strengthening campaign."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from common import atomic_json, docker_available, image_report, load_config, run


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--groups", default="online_boutique,r4,helpers,ns3")
    p.add_argument("--pull-missing", action="store_true")
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    if not docker_available():
        raise SystemExit("Docker is not running")
    cfg = load_config()["images"]
    images = []
    for group in args.groups.split(","):
        if group not in cfg:
            p.error(f"unknown image group: {group}")
        images.extend(cfg[group])
    images = list(dict.fromkeys(images))
    before = image_report(images)
    if args.pull_missing:
        for row in before:
            if not row["present"] and not row["image"].startswith("ns3-wigig:"):
                print(f"pulling {row['image']}", flush=True)
                run(["docker", "pull", row["image"]], timeout=900)
    after = image_report(images)
    payload = {"groups": args.groups.split(","), "images": after}
    if args.output:
        atomic_json(args.output, payload)
    print(json.dumps(payload, indent=2))
    missing = [x["image"] for x in after if not x["present"]]
    if missing:
        print("Missing images:", *missing, sep="\n  - ")
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
