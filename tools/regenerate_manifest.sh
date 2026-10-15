#!/usr/bin/env sh
set -eu
python "$(dirname "$0")/regenerate_manifest.py"
