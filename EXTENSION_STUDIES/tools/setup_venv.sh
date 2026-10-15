#!/bin/bash
# Creates the revision analysis environment with the package's pinned versions.
set -euo pipefail
VENV="$HOME/mape_venv"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet numpy==2.3.5 scipy==1.17.0 pandas==2.2.3 matplotlib==3.10.8 \
    jsonschema==4.26.0 pytest==9.0.2 PyYAML==6.0.3 psutil==7.2.2
"$VENV/bin/python" -c "import numpy, scipy, pandas, matplotlib; print('ok', numpy.__version__, scipy.__version__, pandas.__version__)"
