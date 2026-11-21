"""Source tree inventory and digests. Links and special files are rejected."""
from __future__ import annotations

import os
import stat
from pathlib import Path

from ..errors import ValidationError
from .jsonio import bytes_hash, canonical_hash


def source_files(root: Path) -> dict[str, Path]:
    """Inventory every file. Reject links (including the root) and special files."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValidationError(f"source must be a real directory: {root}")
    result: dict[str, Path] = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise ValidationError(f"symlinks and special files are forbidden: {path}")
            relative = path.relative_to(root).as_posix()
            if any(c in relative for c in ("\n", "\r", "\x00", "\\")):
                raise ValidationError(f"unsupported source path: {relative!r}")
            if stat.S_ISREG(mode):
                result[relative] = path
    return dict(sorted(result.items()))


def source_digest(root: Path) -> str:
    records = []
    for relative, path in source_files(root).items():
        records.append([relative, path.stat().st_mode & 0o111, bytes_hash(path.read_bytes())])
    return canonical_hash(records)
