"""Exclusive file locks and the timestamp format used in every record."""
import fcntl
from contextlib import contextmanager
from datetime import UTC, datetime

from ..errors import ValidationError


def now():
    return datetime.now(UTC).isoformat()


@contextmanager
def lock_file(path):
    """Fail immediately when another operation holds the lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValidationError(f'another operation holds {path}') from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
