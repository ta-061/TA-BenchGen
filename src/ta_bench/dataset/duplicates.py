"""Reject a candidate that repeats an already published case."""
from __future__ import annotations

import re
from pathlib import Path

from ..candidate.c_source import mask_c
from ..candidate.diff import changed_files, opcodes
from ..common.jsonio import canonical_hash, load_json
from ..common.sources import source_digest
from ..errors import ValidationError
from .layout import resolve_normal


def _normalized_patch(normal: Path, defective: Path) -> str:
    records = []
    keywords = {"if", "else", "return", "for", "while", "switch", "case", "break", "continue", "sizeof", "int", "unsigned", "void", "char", "const", "struct", "static", "bool", "true", "false", "NULL"}
    def normalize(lines):
        text = mask_c("".join(lines))
        text = re.sub(r"\b(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d+)?)\b", "#", text)
        text = re.sub(r"\b[A-Za-z_]\w*\b", lambda m: m.group() if m.group() in keywords else "ID", text)
        return re.sub(r"\s+", "", text)
    for path, a, b in changed_files(normal, defective):
        for tag, i1, i2, j1, j2 in opcodes(a, b):
            if tag != "equal":
                # The place in the normal file is part of the edit: the same code elsewhere is another case.
                records.append([path, i1, i2, tag, normalize(a[i1:i2]), normalize(b[j1:j2])])
    return canonical_hash(records)


def _edited_places(normal: Path, defective: Path) -> list:
    """Line ranges of the normal files that the case changes."""
    return [[path, i1, i2] for path, a, b in changed_files(normal, defective)
            for tag, i1, i2, _j1, _j2 in opcodes(a, b) if tag != "equal"]


def _target_fingerprint(defects: list[dict]) -> str:
    targets = []
    for defect in defects:
        for target in defect["detector_targets"]:
            if target.get("role") != "protection":
                targets.append([target["path"], target["function"], target["lines"]])
    return canonical_hash(sorted(targets, key=repr))


def check_duplicates(normal: Path, defective: Path, defects: list[dict], existing_dir: Path) -> None:
    fingerprint = _normalized_patch(normal, defective)
    locations = _target_fingerprint(defects)
    places = _edited_places(normal, defective)
    normal_hash = source_digest(normal)
    for case in sorted(Path(existing_dir).glob("case_*")):
        try:
            labels = load_json(case / "labels.json")
            if labels["normal"]["source_digest"] != normal_hash:
                continue  # the same edit in another TA is another case
            other_normal = resolve_normal(Path(existing_dir).parent, labels)
            other_patch = _normalized_patch(other_normal, case / "source") if other_normal.is_dir() else None
            # Another edit may be reported at the same lines; only the same lines edited another way repeat a case.
            same_locations = (locations == _target_fingerprint(labels["defects"]) and other_normal.is_dir()
                              and places == _edited_places(other_normal, case / "source"))
        except (OSError, KeyError, TypeError, ValidationError):
            # Corrupt persisted cases remain review warnings, not duplicate evidence.
            continue
        if fingerprint == other_patch:
            raise ValidationError(f"duplicate normalized patch: {case.name} (the same added and removed code at "
                                  "the same place as a saved case, once names and numbers are ignored)")
        if same_locations:
            raise ValidationError(f"duplicate detector targets: {case.name} (the same lines edited and the same "
                                  "detector_targets as a saved case)")
