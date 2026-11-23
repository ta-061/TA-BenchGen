"""Functions used by the recorded e12 local transport hook."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path


def append_jsonl(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def exclusive_lock(path, nonblocking=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
        yield stream


def phase(event):
    first = (event.get("messages") or [{}])[0]
    if first.get("content", "").startswith("You are screening external functions for potential taint-analysis endpoints"):
        return "phase3"
    if first.get("role") == "system" and first.get("content", "").startswith("You are a taint analyst for security-critical applications."):
        return "phase5"
    return "unclassified"
