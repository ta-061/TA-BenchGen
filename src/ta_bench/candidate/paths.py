"""The single definition of which source paths a candidate may change."""
from __future__ import annotations

from pathlib import PurePosixPath

from ..errors import ValidationError


def safe_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValidationError("invalid relative source path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in {"", ".", ".."} for p in value.split("/")):
        raise ValidationError(f"unsafe source path: {value}")
    if any(c in value for c in ("\n", "\r", ":")):
        raise ValidationError(f"unsafe source path: {value}")
    return path.as_posix()


def allowed_path(value: str) -> bool:
    value = safe_relative_path(value)
    path = PurePosixPath(value)
    return len(path.parts) >= 2 and path.parts[0] == "ta" and path.suffix in {".c", ".h"}
