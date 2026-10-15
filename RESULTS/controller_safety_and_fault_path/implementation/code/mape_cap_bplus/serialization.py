"""JSON serialization helpers for examples and evidence."""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def _convert(value: Any) -> Any:
    if is_dataclass(value):
        return _convert(asdict(value))
    if isinstance(value, dict):
        converted = {}
        for key, item in value.items():
            if isinstance(key, tuple):
                key = "->".join(str(part) for part in key)
            converted[str(key)] = _convert(item)
        return converted
    if isinstance(value, (list, tuple)):
        return [_convert(item) for item in value]
    return value


def write_json(path: str | Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_convert(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")
