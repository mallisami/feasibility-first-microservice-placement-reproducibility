#!/usr/bin/env python3
"""Compatibility wrapper; use verify_reviewer_package.py for this cleaned release."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).with_name("verify_reviewer_package.py")), run_name="__main__")
