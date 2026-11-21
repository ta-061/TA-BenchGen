"""Full source files aligned with the same line matching used for the saved edits."""
from itertools import zip_longest
from pathlib import Path

from ..candidate.diff import opcodes
from ..common.sources import source_files


def _lines(path: Path) -> list[str]:
    return path.read_bytes().decode("utf-8", errors="replace").splitlines(keepends=True)


def compare_sources(normal: Path, defective: Path) -> dict:
    before, after = source_files(normal), source_files(defective)
    if before.keys() != after.keys():
        raise ValueError("Source file inventory changed since case inspection")
    files = {}
    for path, source in after.items():
        if source.suffix not in {".c", ".h"}:
            continue
        left, right = _lines(before[path]), _lines(source)
        blocks = []
        removed = added = 0
        if left and left == right:
            operations = [("equal", 0, len(left), 0, len(right))]
        else:
            operations = opcodes(left, right)
        for tag, i, end_i, j, end_j in operations:
            changed = tag != "equal"
            if changed:
                removed += end_i - i
                added += end_j - j
            old_lines = enumerate(left[i:end_i], start=i + 1)
            new_lines = enumerate(right[j:end_j], start=j + 1)
            blocks.append({"changed": changed, "rows": list(zip_longest(old_lines, new_lines))})
        files[path] = {"id": f"source-{len(files)}", "blocks": blocks, "removed": removed, "added": added}
    # Open a changed file first. Keep the original path order within each group.
    return dict(sorted(files.items(), key=lambda item: not (item[1]["removed"] or item[1]["added"])))


def source_annotations(labels: dict) -> dict:
    marks = {}

    def mark(path, side, lines, kind, label):
        if lines:
            for number in range(lines[0], lines[1] + 1):
                marks.setdefault((path, side, number), []).append((kind, label))

    for defect in labels.get("defects", []):
        for target in defect["detector_targets"]:
            mark(target["path"], "right", target["lines"], target["role"], defect["id"])
        for edit in defect["edits"]:
            mark(edit["path"], "left", edit["normal_lines"], "edit", edit["edit_id"])
            mark(edit["path"], "right", edit["defective_lines"], "edit", edit["edit_id"])
    return marks
