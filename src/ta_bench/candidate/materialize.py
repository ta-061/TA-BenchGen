"""Write a candidate's source changes over a private copy of the normal TA.

A candidate gives either changes (exact text to find once, what replaces it, and the defect the
change belongs to) or files (complete replacement texts). Both end in the same replacement files.
"""
import shutil
from itertools import accumulate, pairwise
from pathlib import PurePosixPath

from ..common.sources import source_digest
from ..errors import ValidationError
from .diff import edit_units
from .paths import allowed_path

MAX_FILE_CHARS = 2_000_000
MAX_CHANGES = 64
CHANGE_FIELDS = ('path', 'old', 'new', 'defect')


def _replaceable(normal, name, content) -> bool:
    try:
        allowed = allowed_path(name)
    except ValidationError:
        return False
    return (allowed and PurePosixPath(name).as_posix() == name
            and (normal / name).is_file() and len(content) <= MAX_FILE_CHARS)


def _owners(name, before, after, spans) -> list:
    """The defect of each edit between two texts of one file, in the order edits are numbered.

    Match removed and added lines against the changes' half-open character ranges on each side.
    The spans are sorted by original position. The line diff need not cut the file where the
    changes did, so an edit that touches no change belongs to the file's only defect.
    """
    before_lines, after_lines = before.splitlines(keepends=True), after.splitlines(keepends=True)
    before_starts = list(accumulate(map(len, before_lines), initial=0))
    after_starts = list(accumulate(map(len, after_lines), initial=0))
    regions, offset = [], 0
    for start, end, new, defect in spans:
        regions.append((start, end, start + offset, start + offset + len(new), defect))
        offset += len(new) - (end - start)
    touched = {}
    for (_tag, i1, i2, j1, j2), number in edit_units(before_lines, after_lines):
        if number is not None:
            touched.setdefault(number, set()).update(
                defect for first, last, new_first, new_last, defect in regions
                if max(first, before_starts[i1]) < min(last, before_starts[i2])
                or max(new_first, after_starts[j1]) < min(new_last, after_starts[j2]))
    owners = []
    for number in sorted(touched):
        found = touched[number] or {region[-1] for region in regions}
        if len(found) != 1:
            raise ValidationError(f'changes of {", ".join(sorted(found))} in {name} share an edit; '
                                  'leave an unchanged line between the changes of different defects')
        owners.append(found.pop())
    return owners


def apply_changes(normal, changes) -> tuple[dict, dict]:
    """changes -> ({path: new text}, {path: defect of each edit in that file, in order}).

    Each old text must occur exactly once in the normal file. Edits are still counted from the
    resulting line diff: one change may come out as several edits.
    """
    if not isinstance(changes, list) or not 1 <= len(changes) <= MAX_CHANGES:
        raise ValidationError(f'changes must be a list of 1 to {MAX_CHANGES} objects')
    spans = {}
    for number, change in enumerate(changes, 1):
        where = f'changes[{number}]'
        if not isinstance(change, dict) or set(change) != set(CHANGE_FIELDS) or any(
                not isinstance(change[key], str) for key in CHANGE_FIELDS):
            raise ValidationError(f'{where} requires exactly {", ".join(CHANGE_FIELDS)} (strings)')
        name, old, new = change['path'], change['old'], change['new']
        if not _replaceable(normal, name, new):
            raise ValidationError(f'forbidden replacement path: {name}')
        if not old or old == new:
            raise ValidationError(f'{where}: old must be nonempty and differ from new')
        text = (normal / name).read_text(encoding='utf-8')
        found = text.count(old)
        if found != 1:
            raise ValidationError(f'{where}: old must occur exactly once in {name}, found {found} times; '
                                  'copy the lines exactly, with enough surrounding lines to be unique')
        start = text.index(old)
        spans.setdefault(name, []).append((start, start + len(old), new, change['defect'], where))
    files, owners = {}, {}
    for name, items in spans.items():
        original, items = (normal / name).read_text(encoding='utf-8'), sorted(items)
        for (_, end, _, _, _), (start, _, _, _, where) in pairwise(items):
            if start < end:
                raise ValidationError(f'{where}: overlaps another change in {name}')
        text = original
        for start, end, new, _, _ in reversed(items):
            text = text[:start] + new + text[end:]
        files[name] = text
        owners[name] = _owners(name, original, text, [(start, end, new, defect)
                                                    for start, end, new, defect, _ in items])
    return files, owners


def assign_edits(defects, edits, owners) -> list:
    """Defects with the edits of the changes that name them; owners comes from apply_changes."""
    if any('edits' in defect for defect in defects):
        raise ValidationError('with changes, leave edits out of defects: every change names its defect')
    remaining = {name: iter(names) for name, names in owners.items()}
    assigned = {}
    for edit in edits:
        assigned.setdefault(next(remaining[edit['path']]), []).append(edit['edit_id'])
    unknown = set(assigned) - {defect['id'] for defect in defects}
    if unknown:
        raise ValidationError(f'changes name defects that are not in defects: {", ".join(sorted(unknown))}')
    return [{**defect, 'edits': assigned.get(defect['id'], [])} for defect in defects]


def materialize(normal, destination, files):
    source_digest(normal)  # reject links and special files before copying
    if not isinstance(files, dict) or not files:
        raise ValidationError('files must contain source replacements')
    for name, content in files.items():
        if not isinstance(name, str) or not isinstance(content, str):
            raise ValidationError('files must map paths to text')
        if not _replaceable(normal, name, content):
            raise ValidationError(f'forbidden replacement path: {name}')
    shutil.copytree(normal, destination)
    for name, content in files.items():
        (destination / name).write_text(content, encoding='utf-8')
