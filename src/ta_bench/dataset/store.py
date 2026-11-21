"""Atomic publication of cases and read-only integrity inspection."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from ..candidate.check import check_candidate
from ..candidate.diff import compute_diff
from ..common.jsonio import atomic_json, bytes_hash, canonical_hash, load_json, sync_dir
from ..common.sources import source_digest
from ..errors import ValidationError
from .layout import (
    CASE_FILES,
    NORMAL_CHANGED_WARNING,
    STALE_APPROVAL_WARNING,
    resolve_normal,
)
from .reviews import HISTORY_FILE, case_status, defect_statuses, defect_versions, read_label_history
from .schema import require, validate_labels, validate_verification


def labels_digest(labels: dict) -> str:
    return canonical_hash({k: v for k, v in labels.items() if k != "review"})


def approval_hashes(case_dir: Path, normal_dir: Path) -> dict[str, str]:
    case_dir = Path(case_dir)
    labels = load_json(case_dir / "labels.json")
    verification = load_json(case_dir / "verification.json")
    return {
        "normal_source": source_digest(normal_dir),
        "defective_source": source_digest(case_dir / "source"),
        "changes_diff": bytes_hash((case_dir / "changes.diff").read_bytes()),
        "labels": labels_digest(labels),
        "semantic": canonical_hash(verification["semantic"]),
    }


def save_case(defective_root: Path, source: Path, labels: dict, verification: dict, diff: str) -> Path:
    """Publish a complete machine-passing case with one directory rename."""
    validate_labels(labels)
    validate_verification(verification, labels)
    require(verification["semantic"]["machine_validation"]["status"] == "machine_pass", "only machine_pass cases may be published")
    require(labels["review"]["status"] == "unreviewed", "new cases must be unreviewed")
    source_digest(source)
    defective_root = Path(defective_root)
    defective_root.mkdir(parents=True, exist_ok=True)
    destination = defective_root / labels["case_id"]
    require(not destination.exists(), "case already exists")
    temporary = Path(tempfile.mkdtemp(prefix=".case-", dir=defective_root))
    try:
        shutil.copytree(source, temporary / "source", symlinks=False)
        atomic_json(temporary / "labels.json", labels)
        atomic_json(temporary / "verification.json", verification)
        with (temporary / "changes.diff").open("w", encoding="utf-8", newline="") as stream:
            stream.write(diff)
            stream.flush()
            os.fsync(stream.fileno())
        sync_dir(temporary)
        # A lock held by generate prevents concurrent publication of identical IDs.
        os.rename(temporary, destination)
        sync_dir(defective_root)
        return destination
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def inspect_case(case_dir: Path, benchmark_dir: Path, classes: dict) -> dict:
    """Read-only integrity inspection; damaged cases remain visible but unapprovable."""
    case_dir = Path(case_dir)
    result = {"labels": None, "verification": None, "warnings": [], "status": "invalid", "normal_dir": None, "hashes": None, "structural_valid": False}
    try:
        require(not case_dir.is_symlink() and case_dir.is_dir(), "case directory must not be a symlink")
        names = {p.name for p in case_dir.iterdir()}
        require(names == CASE_FILES or names == CASE_FILES | {HISTORY_FILE},
                "case must contain exactly source/, labels.json, changes.diff, verification.json and optional label history")
        require(all(not (case_dir / name).is_symlink() for name in names), "case elements must not be symlinks")
        labels = load_json(case_dir / "labels.json")
        result["labels"] = labels
        validate_labels(labels)
        result["label_history"] = read_label_history(case_dir, labels)
        require(case_dir.name == labels["case_id"], "directory/case_id mismatch")
        verification = load_json(case_dir / "verification.json")
        result["verification"] = verification
        validate_verification(verification, labels)
        normal = resolve_normal(benchmark_dir, labels)
        result["normal_dir"] = str(normal)
        require(normal.is_dir(), f"normal source is missing: {normal}")
        hashes = approval_hashes(case_dir, normal)
        result["hashes"] = hashes
        result["status"] = labels["review"]["status"]
        versions = defect_versions(labels, hashes)
        states = defect_statuses(labels, hashes, versions)
        result.update(defect_versions=versions, defect_statuses=states)
        if "per_defect" in labels["review"]:
            saved = {did: state["status"] for did, state in labels["review"]["per_defect"].items()}
            require(case_status(saved) == result["status"], "inconsistent case and per-defect review status")
            result["status"] = case_status(states)
        if hashes["normal_source"] != labels["normal"]["source_digest"]:
            result["status"] = "stale"
            result["warnings"].append(NORMAL_CHANGED_WARNING)
        if "stale" in states.values() or (labels["review"]["status"] == "approved" and hashes != labels["review"]["approved_against"]):
            result["status"] = "stale"
            result["warnings"].append(STALE_APPROVAL_WARNING)
        actual_diff = compute_diff(normal, case_dir / "source")
        require((case_dir / "changes.diff").read_text(encoding="utf-8") == actual_diff, "changes.diff does not match source trees")
        check_candidate(normal, case_dir / "source", labels["defects"], classes)
        result["structural_valid"] = True
    except (ValidationError, OSError, UnicodeError, KeyError, TypeError, ValueError) as exc:
        result["warnings"].append(str(exc))
        if result["status"] != "stale":
            result["status"] = "invalid"
    return result
