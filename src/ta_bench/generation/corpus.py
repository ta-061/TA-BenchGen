"""Normal inputs accumulated per normal-source digest, replayed on later candidates."""
import copy
from pathlib import Path

from ..common.jsonio import atomic_json, canonical_hash, load_json
from ..common.locking import lock_file


def corpus_path(work_dir: Path, normal_digest: str) -> Path:
    return work_dir / 'normal-inputs' / (normal_digest.split(':')[1] + '.json')


def load_corpus(path: Path) -> list:
    return load_json(path) if path.exists() else []


def extend_corpus(work_dir: Path, path: Path, step_lists: list) -> None:
    with lock_file(work_dir / '.corpus.lock'):
        unique = {canonical_hash(steps): steps for steps in load_corpus(path) + step_lists}
        atomic_json(path, list(unique.values()))


def normal_steps(tests: list) -> list:
    return [t['steps'] for t in tests if t['purpose'] == 'normal']


def merge_corpus(tests: list, corpus: list) -> list:
    """Append stored normal inputs that the candidate's own plan does not already contain."""
    tests = copy.deepcopy(tests)
    seen = {canonical_hash(steps) for steps in normal_steps(tests)}
    ids = {t['id'] for t in tests}
    for steps in corpus:
        key = canonical_hash(steps)
        if key in seen:
            continue
        tid = 'C' + key.split(':')[1][:16]
        while tid in ids:
            tid += '_'
        tests.append({'id': tid, 'purpose': 'normal', 'targets': [], 'steps': steps})
        seen.add(key)
        ids.add(tid)
    return tests
