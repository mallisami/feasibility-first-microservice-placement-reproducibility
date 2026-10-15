#!/usr/bin/env python3
"""Run or resume the complete local MAPE-CAP B+ campaign."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from mape_cap_bplus.campaign import FullCampaign  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="rerun all stages even when valid checkpoints exist")
    parser.add_argument("--status", action="store_true", help="show saved stage status without running")
    args = parser.parse_args()
    campaign = FullCampaign(ROOT, force=args.force)
    if args.status:
        print(json.dumps(campaign.status(), indent=2, sort_keys=True))
        return 0
    campaign.run()
    print("Full local campaign is complete. Existing valid stages will be skipped on future runs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
