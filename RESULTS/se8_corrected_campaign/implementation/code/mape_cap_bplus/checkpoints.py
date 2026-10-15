"""Idempotent stage checkpoints for one-run/resumable experiment campaigns."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import traceback
from typing import Callable, Iterable, Mapping, Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_json_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def tree_hash(paths: Iterable[Path], base: Path | None = None) -> str:
    entries: list[tuple[str, str]] = []
    resolved_base = Path(base).resolve() if base is not None else None
    for path in sorted({Path(p).resolve() for p in paths}, key=lambda p: str(p)):
        def label(item: Path) -> str:
            if resolved_base is not None:
                try:
                    return str(item.relative_to(resolved_base))
                except ValueError:
                    pass
            return item.name if item == path else str(item.relative_to(path.parent))
        if not path.exists():
            entries.append((label(path), "MISSING"))
        elif path.is_file():
            entries.append((label(path), sha256_file(path)))
        else:
            for child in sorted(path.rglob("*")):
                if child.is_file() and "__pycache__" not in child.parts:
                    entries.append((label(child), sha256_file(child)))
    return stable_json_hash(entries)


@dataclass
class StageRecord:
    stage_id: str
    status: str
    fingerprint: str
    started_at: str
    completed_at: str | None
    attempts: int
    outputs: dict[str, str]
    message: str = ""
    traceback: str = ""


class CampaignState:
    def __init__(self, state_path: str | Path, root: str | Path | None = None):
        self.path = Path(state_path)
        self.root = Path(root).resolve() if root is not None else self.path.parent.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data: dict[str, Any] = {"schema_version": "1.0", "stages": {}}
        if self.path.exists():
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if loaded.get("schema_version") != "1.0":
                raise ValueError(f"unsupported campaign state schema: {loaded.get('schema_version')}")
            self.data = loaded

    def save(self) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def _outputs_valid(self, record: Mapping[str, Any]) -> bool:
        output_hashes = record.get("outputs", {})
        if not output_hashes:
            return False
        for raw_path, expected in output_hashes.items():
            path = Path(raw_path)
            if not path.is_absolute():
                path = self.root / path
            if not path.exists() or not path.is_file() or sha256_file(path) != expected:
                return False
        return True

    def is_current(self, stage_id: str, fingerprint: str) -> bool:
        record = self.data["stages"].get(stage_id)
        return bool(
            record
            and record.get("status") == "complete"
            and record.get("fingerprint") == fingerprint
            and self._outputs_valid(record)
        )

    def run_stage(
        self,
        stage_id: str,
        fingerprint: str,
        outputs: Iterable[str | Path],
        action: Callable[[], str | None],
        *,
        force: bool = False,
    ) -> tuple[str, str]:
        output_paths = [Path(p).resolve() for p in outputs]
        if not force and self.is_current(stage_id, fingerprint):
            return "skipped", "checkpoint and output hashes are current"

        previous = self.data["stages"].get(stage_id, {})
        record = StageRecord(
            stage_id=stage_id,
            status="running",
            fingerprint=fingerprint,
            started_at=utc_now(),
            completed_at=None,
            attempts=int(previous.get("attempts", 0)) + 1,
            outputs={},
        )
        self.data["stages"][stage_id] = asdict(record)
        self.save()
        try:
            message = action() or ""
            missing = [str(path) for path in output_paths if not path.exists() or not path.is_file()]
            if missing:
                raise RuntimeError(f"stage {stage_id} did not create required outputs: {missing}")
            record.status = "complete"
            record.completed_at = utc_now()
            record.outputs = {}
            for path in output_paths:
                try:
                    key = str(path.relative_to(self.root))
                except ValueError:
                    key = str(path)
                record.outputs[key] = sha256_file(path)
            record.message = message
            self.data["stages"][stage_id] = asdict(record)
            self.save()
            return "complete", message
        except Exception as exc:
            record.status = "failed"
            record.completed_at = utc_now()
            record.message = str(exc)
            record.traceback = traceback.format_exc()
            self.data["stages"][stage_id] = asdict(record)
            self.save()
            raise

    def summary(self) -> list[dict[str, Any]]:
        return [dict(value) for _, value in sorted(self.data["stages"].items())]
