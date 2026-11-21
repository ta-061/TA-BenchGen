"""Source-only export for detectors; the answer key stays in private work/."""
from __future__ import annotations

import os
import secrets
import shutil
import tempfile
from pathlib import Path

from ..common.jsonio import atomic_json
from ..common.locking import now
from ..common.sources import source_digest
from ..dataset.store import inspect_case
from .cases import case_paths, reviewable

EXPORTED_SUFFIXES = {".c", ".h", ".S", ".s"}


def export_blind(benchmark_dir: Path, destination: Path, classes: dict, work_dir: Path,
                 approved_only: bool = True, include_host: bool = False) -> dict:
    """Atomically export TA sources, with a private mapping outside detector input."""
    benchmark_dir, destination, work_dir = (Path(p).resolve() for p in (benchmark_dir, destination, work_dir))
    if destination.exists():
        raise ValueError("Blind export destination already exists; use a new directory.")
    # Neither the original benchmark nor the evaluator mapping may sit inside detector input.
    if destination == benchmark_dir or destination in benchmark_dir.parents or benchmark_dir in destination.parents:
        raise ValueError("Blind export must be outside benchmark/.")
    if destination == work_dir or destination in work_dir.parents or work_dir in destination.parents:
        raise ValueError("Blind export and private work/ must be separate directories.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".blind-", dir=destination.parent))
    mapping = {}
    skipped = []
    try:
        for case_dir in case_paths(benchmark_dir):
            info = inspect_case(case_dir, benchmark_dir, classes)
            if info.get("warnings") or not reviewable(info) or (approved_only and info["status"] != "approved"):
                skipped.append(case_dir.name)
                continue
            blind_id = "sample_" + secrets.token_hex(16)
            source = case_dir / "source"
            before = source_digest(source)
            target = staging / blind_id
            target.mkdir()
            included = 0
            for section in (("ta", "host") if include_host else ("ta",)):
                section_root = source / section
                if not section_root.is_dir():
                    continue
                for path in sorted(section_root.rglob("*")):
                    # Source-only means no executable, labels, build logs, or metadata sidecars.
                    if path.is_file() and path.suffix in EXPORTED_SUFFIXES:
                        relative = path.relative_to(source)
                        out = target / relative
                        out.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(path, out)
                        included += 1
            if not included:
                raise ValueError(f"No TA sources found in {case_dir.name}")
            after = inspect_case(case_dir, benchmark_dir, classes)
            # Individual decisions may change while the aggregate status stays partially approved.
            if (before != source_digest(source) or info["hashes"] != after.get("hashes")
                    or info["status"] != after.get("status") or info["labels"] != after.get("labels")):
                raise ValueError(f"Case changed while exporting: {case_dir.name}")
            mapping[blind_id] = {"case_id": case_dir.name, "labels": info["labels"], "against": info["hashes"]}
        if not mapping:
            raise ValueError("No intact eligible cases to export.")
        mapping_path = work_dir / "blind-mappings" / ("mapping_" + secrets.token_hex(16) + ".json")
        atomic_json(mapping_path, {"created_at": now(), "destination": str(destination),
                                   "cases": mapping, "evaluation": {"matching_granularity": None, "generation_detector_model_relationship": None}})
        os.chmod(mapping_path, 0o600)
        try:
            # Never replace an existing export, including one created concurrently.
            if destination.exists():
                raise ValueError("Blind export destination was created concurrently.")
            os.rename(staging, destination)
        except BaseException:
            mapping_path.unlink(missing_ok=True)
            raise
        return {"count": len(mapping), "mapping_path": str(mapping_path), "skipped": skipped}
    finally:
        if staging.exists():
            shutil.rmtree(staging)
