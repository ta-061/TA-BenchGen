"""Where things live inside benchmark/, and the warnings inspection can report."""
from __future__ import annotations

from pathlib import Path

from ..errors import ValidationError

CASE_FILES = {"source", "labels.json", "changes.diff", "verification.json"}
STALE_APPROVAL_WARNING = "approval hashes changed; review is stale"
NORMAL_CHANGED_WARNING = "normal source digest changed; original baseline required"


def resolve_normal(benchmark_dir: Path, labels: dict) -> Path:
    value = labels.get("normal", {}).get("path")
    if not isinstance(value, str) or not value:
        raise ValidationError("normal.path must be a nonempty string")
    path = Path(value)
    return path if path.is_absolute() else Path(benchmark_dir) / path


def blocking_warnings(info: dict) -> list[str]:
    """Warnings other than a stale approval, which only invalidates the approval."""
    return [w for w in info.get("warnings", []) if w != STALE_APPROVAL_WARNING]
