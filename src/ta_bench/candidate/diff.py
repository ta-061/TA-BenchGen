"""Line edits between the normal and defective trees, and their selective reversal."""
from __future__ import annotations

import difflib
import shutil
from pathlib import Path

from ..common.sources import source_files
from ..errors import ValidationError
from .paths import allowed_path


def _pair(normal: Path, defective: Path) -> tuple[dict, dict]:
    left, right = source_files(normal), source_files(defective)
    if set(left) != set(right):
        raise ValidationError(f"file additions, deletions and renames are forbidden: {sorted(set(left) ^ set(right))}")
    return left, right


def changed_files(normal: Path, defective: Path):
    left, right = _pair(normal, defective)
    for relative in left:
        before, after = left[relative], right[relative]
        if before.stat().st_mode & 0o777 != after.stat().st_mode & 0o777:
            raise ValidationError(f"file permissions may not change: {relative}")
        a, b = before.read_bytes(), after.read_bytes()
        if a != b:
            if not allowed_path(relative):
                raise ValidationError(f"change outside permitted ta/*.c and ta/*.h: {relative}")
            try:
                yield relative, a.decode("utf-8").splitlines(keepends=True), b.decode("utf-8").splitlines(keepends=True)
            except UnicodeDecodeError as exc:
                raise ValidationError(f"changed source must be UTF-8: {relative}") from exc


def opcodes(a: list[str], b: list[str]):
    return difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()


def edit_units(a: list[str], b: list[str], moves: bool = True) -> list[tuple[tuple, int | None]]:
    """Opcodes of one file, each changed one with its 0-based edit number (None for equal).

    Lines removed in one place and inserted unchanged in another are one edit, a move:
    reverting only half of it would leave the lines twice or not at all.
    """
    ops = opcodes(a, b)
    partner = {}
    for x, (tag, i1, i2, _j1, _j2) in enumerate(ops):
        removed = [line.strip() for line in a[i1:i2]]
        if not moves or tag != "delete" or not any(removed):
            continue
        for y, (other, _i1, _i2, j1, j2) in enumerate(ops):
            if other == "insert" and y not in partner and [line.strip() for line in b[j1:j2]] == removed:
                partner[x], partner[y] = y, x
                break
    numbers, count = {}, 0
    for x, op in enumerate(ops):
        if op[0] == "equal":
            numbers[x] = None
        elif partner.get(x, x) < x:
            numbers[x] = numbers[partner[x]]
        else:
            numbers[x], count = count, count + 1
    return [(op, numbers[x]) for x, op in enumerate(ops)]


def compute_edits(normal: Path, defective: Path, moves: bool = True) -> list[dict]:
    result = []
    for path, a, b in changed_files(normal, defective):
        first = len(result)
        for (tag, i1, i2, j1, j2), number in edit_units(a, b, moves):
            if number is None:
                continue
            if first + number < len(result):  # second half of a move
                edit = result[first + number]
                edit["kind"] = "move"
                edit["normal_lines"] = edit["normal_lines"] or [i1 + 1, i2]
                edit["defective_lines"] = edit["defective_lines"] or [j1 + 1, j2]
                continue
            result.append({"edit_id": f"E{len(result) + 1}", "path": path, "kind": tag,
                           "normal_lines": [i1 + 1, i2] if i1 != i2 else None,
                           "defective_lines": [j1 + 1, j2] if j1 != j2 else None})
    return result


def saved_before_moves(normal: Path, defective: Path, defects: list) -> bool:
    """True for a case saved when a move was still a removal and an insertion (two edits).

    Such a case stays valid with the edits it was saved and verified with.
    """
    stored = [edit for defect in defects if isinstance(defect, dict) and isinstance(defect.get("edits"), list)
              for edit in defect["edits"] if isinstance(edit, dict)]
    if not stored or all(edit.get("kind") != "move" for edit in compute_edits(normal, defective)):
        return False
    old = compute_edits(normal, defective, moves=False)
    return all(edit in old for edit in stored)


def compute_diff(normal: Path, defective: Path) -> str:
    pieces = []
    for path, a, b in changed_files(normal, defective):
        for line in difflib.unified_diff(a, b, fromfile=f"a/{path}", tofile=f"b/{path}", n=3):
            pieces.append(line)
            if not line.endswith("\n"):
                pieces.append("\n\\ No newline at end of file\n")
    return "".join(pieces)

def revert_edits(normal: Path, defective: Path, destination: Path, edit_ids: list[str],
                 moves: bool = True) -> None:
    """Rebuild each changed file from opcodes, replacing selected units by normal."""
    edits = compute_edits(normal, defective, moves)
    known = {edit["edit_id"] for edit in edits}
    if not isinstance(edit_ids, list) or not set(edit_ids) <= known or len(set(edit_ids)) != len(edit_ids):
        raise ValidationError("unknown or duplicate edit to revert")
    destination = Path(destination)
    if destination.exists():
        raise ValidationError("revert destination must not exist")
    destination_abs = destination.absolute()
    for source in (Path(normal).absolute(), Path(defective).absolute()):
        if destination_abs == source or source in destination_abs.parents:
            raise ValidationError("revert destination must be outside source trees")
    shutil.copytree(defective, destination, symlinks=False)
    first = 0
    for path, a, b in changed_files(normal, defective):
        rebuilt = []
        units = edit_units(a, b, moves)
        for (_tag, i1, i2, j1, j2), number in units:
            reverted = number is not None and f"E{first + number + 1}" in edit_ids
            rebuilt.extend(a[i1:i2] if reverted else b[j1:j2])
        first += len({number for _op, number in units if number is not None})
        (destination / path).write_bytes("".join(rebuilt).encode("utf-8"))
