"""Static checks at the boundary between model output and trusted execution."""
from __future__ import annotations

import copy
import re
from collections import Counter
from pathlib import Path

from ..common.classes import class_definitions
from ..errors import ValidationError
from .c_source import function_ranges, mask_c
from .diff import changed_files, compute_edits, opcodes, saved_before_moves
from .paths import allowed_path

# These are deliberately conservative lexical checks, not semantic classification.
LEAK_WORDS = {
    "defect", "defective", "vulnerability", "vulnerable", "unsafe", "insecure",
    "intentional", "injected", "backdoor", "bug", "buggy", "exploit",
    "不備", "脆弱", "欠陥", "意図的", "検査削除",
}

TARGET_ROLES = ("effect", "protection")
TARGET_FIELDS = {"path", "function", "lines", "role"}


def validate_target_roles(targets) -> None:
    if not isinstance(targets, list) or not targets or not all(isinstance(t, dict) for t in targets):
        raise ValidationError("detector_targets must be a nonempty list of locations")
    roles = [target.get("role") for target in targets]
    if roles.count("effect") != 1 or len(roles) > 2 or any(role not in TARGET_ROLES for role in roles):
        raise ValidationError("expected one effect location and at most one protection location")


def validate_target(target: dict, defective: Path) -> None:
    if not isinstance(target, dict) or set(target) != TARGET_FIELDS:
        raise ValidationError("detector target must have exactly path, function, lines and role")
    if target["role"] not in TARGET_ROLES:
        raise ValidationError("target role must be effect or protection")
    path = target.get("path")
    if not allowed_path(path):
        raise ValidationError("detector target must refer to TA C source")
    file = defective / path
    if not file.is_file() or file.is_symlink():
        raise ValidationError(f"detector target file does not exist: {path}")
    lines = target.get("lines")
    source = file.read_text(encoding="utf-8")
    if not isinstance(lines, list) or len(lines) != 2 or any(type(n) is not int for n in lines):
        raise ValidationError("target lines must be two integers")
    source_lines = mask_c(source, keep_literals=True).splitlines()
    if not 1 <= lines[0] <= lines[1] <= len(source_lines):
        raise ValidationError(f"detector target lines do not exist: {path}:{lines}")
    selected = "\n".join(source_lines[lines[0] - 1:lines[1]])
    if not re.search(r"[^\s{}()\[\];,\\]", selected):
        raise ValidationError("target range must contain a C operation (only whitespace, comments or delimiters found)")
    function = target.get("function")
    if not isinstance(function, str) or not re.fullmatch(r"[A-Za-z_]\w*", function):
        raise ValidationError("target function must be a C identifier")
    if not any(start <= lines[0] <= lines[1] <= end for start, end in function_ranges(source).get(function, [])):
        raise ValidationError(f"target lines are outside function {function}: {path}:{lines}")


def _check_leaks(normal: Path, defective: Path, classes: dict) -> None:
    words = LEAK_WORDS | {str(name) for name in classes}
    pattern = re.compile("|".join(
        re.escape(w) if any(ord(c) > 127 for c in w) else r"(?<![A-Za-z0-9])" + re.escape(w) + r"(?![A-Za-z0-9])"
        for w in sorted(words, key=len, reverse=True)), re.IGNORECASE)
    for path, a, b in changed_files(normal, defective):
        for tag, _i1, _i2, j1, j2 in opcodes(a, b):
            if tag not in {"insert", "replace"}:
                continue
            # Split camelCase identifiers as well as snake_case identifiers.
            changed = re.sub(r"([a-z])([A-Z])", r"\1 \2", "".join(b[j1:j2]))
            found = pattern.search(changed)
            if found:
                raise ValidationError(f"classification/defect clue on changed source line: {path}:{j1 + 1} ({found.group()})")

def check_candidate(normal: Path, defective: Path, defects: list, classes: dict) -> list[dict]:
    """Check edits, attribution, targets and leaks; return defects with resolved edits."""
    normal, defective = Path(normal), Path(defective)
    classes = class_definitions(classes)
    edits = compute_edits(normal, defective, moves=not saved_before_moves(normal, defective, defects))
    if not edits:
        raise ValidationError("candidate has no source edits")
    if not isinstance(defects, list) or not defects:
        raise ValidationError("candidate needs at least one defect")
    edit_map = {edit["edit_id"]: edit for edit in edits}
    attributed = []
    identifiers = []
    resolved = copy.deepcopy(defects)
    for defect in resolved:
        if not isinstance(defect, dict):
            raise ValidationError("defect must be an object")
        did = defect.get("id")
        if not isinstance(did, str) or not re.fullmatch(r"D[1-9][0-9]*", did):
            raise ValidationError("defect id must have form D1")
        identifiers.append(did)
        if not isinstance(defect.get("class"), str) or defect["class"] not in classes:
            raise ValidationError(f"unknown defect class: {defect.get('class')}")
        if not isinstance(defect.get("reason"), str) or not defect["reason"].strip():
            raise ValidationError("defect reason required")
        assigned = defect.get("edits")
        if not isinstance(assigned, list) or not assigned:
            raise ValidationError(f"defect {did} has no edits")
        concrete = []
        for edit in assigned:
            eid = edit if isinstance(edit, str) else edit.get("edit_id") if isinstance(edit, dict) else None
            if not isinstance(eid, str) or eid not in edit_map:
                raise ValidationError(f"unknown edit: {eid}")
            if isinstance(edit, dict) and edit != edit_map[eid]:
                raise ValidationError(f"edit metadata differs from computed diff: {eid}")
            concrete.append(copy.deepcopy(edit_map[eid]))
            attributed.append(eid)
        defect["edits"] = concrete
        targets = defect.get("detector_targets")
        validate_target_roles(targets)
        for target in targets:
            validate_target(target, defective)
        witness = defect.get("witness_test_ids")
        if not isinstance(witness, list) or not witness or any(not isinstance(t, str) or not t for t in witness):
            raise ValidationError("witness_test_ids required")
        if len(witness) != len(set(witness)):
            raise ValidationError("duplicate witness_test_ids")
    if len(identifiers) != len(set(identifiers)):
        raise ValidationError("duplicate defect ids")
    if Counter(attributed) != Counter(edit_map.keys()):
        raise ValidationError("every edit must belong to exactly one defect")
    _check_leaks(normal, defective, classes)
    return resolved
