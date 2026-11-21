"""Which stored cases exist, and which of them a human may review or export."""
from __future__ import annotations

from pathlib import Path

from ..dataset.layout import blocking_warnings
from ..dataset.schema import CASE_ID


def case_paths(benchmark_dir: Path) -> list[Path]:
    root = benchmark_dir / "defective"
    if not root.exists():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink() and CASE_ID.fullmatch(p.name))


def machine_pass(info: dict) -> bool:
    verification = info.get("verification")
    if not isinstance(verification, dict):
        return False
    validation = verification.get("semantic", {}).get("machine_validation", {})
    return validation.get("status") == "machine_pass"


def reviewable(info: dict) -> bool:
    return (info.get("structural_valid", False) and not blocking_warnings(info)
            and bool(info.get("hashes")) and machine_pass(info))
