"""One candidate, from untrusted JSON to measured semantic evidence."""
from collections import Counter

from ..candidate.check import check_candidate
from ..candidate.diff import compute_edits
from ..candidate.materialize import apply_changes, assign_edits, materialize
from ..candidate.plan import validate_plan
from ..common.jsonio import atomic_json, canonical_hash, load_json
from ..common.locking import now
from ..dataset.duplicates import check_duplicates
from ..errors import JudgmentError, ValidationError
from ..runtime.ta_uuid import discover_uuid
from ..verification.judge import verify
from .corpus import merge_corpus

CANDIDATE_FIELDS = ({'changes', 'defects', 'tests'}, {'files', 'defects', 'tests'})


def static_check(normal, source, defects, classes, existing_dir):
    """All checks that need no execution; returns defects with resolved edits."""
    resolved = check_candidate(normal, source, defects, classes)
    check_duplicates(normal, source, resolved, existing_dir)
    return resolved


def _requested_defects(candidate, requested):
    defects = candidate['defects']
    if not isinstance(defects, list) or any(not isinstance(d, dict) for d in defects):
        raise ValidationError('defects must be a list of objects')
    try:
        counts = Counter(d['class'] for d in defects)
    except (KeyError, TypeError) as exc:
        raise ValidationError('invalid defect class') from exc
    if counts != requested:
        raise ValidationError(f'requested defects {requested}, received {dict(counts)}')
    return defects


def process_candidate(candidate, normal, requested, classes, benchmark, work, runner, corpus):
    if not isinstance(candidate, dict):
        raise ValidationError('candidate must be a JSON object')
    if 'unsupported' in candidate:
        raise JudgmentError('unsupported', str(candidate['unsupported']))
    if set(candidate) not in CANDIDATE_FIELDS:
        raise ValidationError('candidate requires exactly changes (or files), defects, tests')
    defects = _requested_defects(candidate, requested)

    tests = validate_plan(candidate['tests'], defects)
    # Validate the complete plan before it is frozen, including persisted normal inputs.
    tests = validate_plan(merge_corpus(tests, corpus), defects)
    atomic_json(work / 'plan.json', tests)
    plan_digest = canonical_hash(tests)
    atomic_json(work / 'plan-digest.json', {'plan_digest': plan_digest, 'frozen_at': now()})

    source = work / 'source'
    if 'files' in candidate:
        materialize(normal, source, candidate['files'])
    else:
        files, owners = apply_changes(normal, candidate['changes'])
        materialize(normal, source, files)
        defects = assign_edits(defects, compute_edits(normal, source), owners)
    resolved = static_check(normal, source, defects, classes, benchmark / 'defective')
    uuid_value = discover_uuid(normal)
    for test in tests:
        for step in test['steps']:
            if step.get('uuid', uuid_value).lower() != uuid_value.lower():
                raise ValidationError('input UUID differs from normal TA UUID')

    semantic = verify(normal, source, resolved, tests, classes, runner, uuid_value, work)
    if canonical_hash(load_json(work / 'plan.json')) != plan_digest:
        raise ValidationError('frozen input plan changed during verification')
    return source, resolved, tests, plan_digest, semantic
