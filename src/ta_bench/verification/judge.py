"""Class-independent differential rules, and the revert that separates several defects."""
import copy
from pathlib import Path

from ..candidate.diff import revert_edits, saved_before_moves
from ..common.classes import class_definitions
from ..errors import ExecutionError, JudgmentError
from ..runtime.events import INSTRUMENTATION, collect_checkpoints, required_features
from ..runtime.observations import comparison, validate_observations
from .conditions import WITNESS_CONDITIONS, condition_names

REPETITIONS = 2  # every input sequence is measured twice on each variant (R3)


def _observe(runner, artifact, steps, uuid):
    return validate_observations(steps, runner.run(artifact, copy.deepcopy(steps), uuid))


def verify(normal: Path, defective: Path, defects: list, tests: list,
           classes: dict, runner, uuid: str, work_dir: Path):
    """Returns semantic record only on complete pass; failed evidence stays in exception."""
    semantic = {'tests': [], 'defect_reverts': [],
                'machine_validation': {'status': 'machine_pass',
                    'per_defect': {d['id']: 'machine_pass' for d in defects}, 'repetitions': REPETITIONS}}

    moves = not saved_before_moves(normal, defective, defects)

    def fail(status, reason):
        semantic['machine_validation'] = {'status': status,
            'per_defect': {d['id']: status for d in defects}, 'repetitions': REPETITIONS, 'reason': reason}
        raise JudgmentError(status, reason, semantic)

    definitions = class_definitions(classes)
    by_id = {d['id']: d for d in defects}
    features = set().union(*(required_features(test['steps']) for test in tests))
    for test in tests:
        for target in test['targets']:
            definition = definitions[by_id[target]['class']]
            if set(definition.get('required_features', [])) - required_features(test['steps']):
                fail('machine_fail', f'{test["id"]}: witness lacks required execution features')
    missing = features - set(getattr(runner, 'features', ()))
    if missing:
        fail('unsupported', 'runtime image lacks features: ' + ', '.join(sorted(missing)))
    checkpoints = collect_checkpoints(tests)
    if features:
        semantic['execution'] = {'features': sorted(features), 'instrumentation': INSTRUMENTATION,
                                 'checkpoints': checkpoints}

    def build(source):
        return runner.build(source, checkpoints=checkpoints) if checkpoints else runner.build(source)

    normal_artifact, defective_artifact = build(normal), build(defective)
    originals = {}
    for test in tests:
        steps = test['steps']
        n1, n2 = (_observe(runner, normal_artifact, steps, uuid) for _ in range(REPETITIONS))
        d1, d2 = (_observe(runner, defective_artifact, steps, uuid) for _ in range(REPETITIONS))
        variable, view = comparison((n1, n2), (d1, d2))
        different = [i for i, (a, b) in enumerate(zip(view(n1), view(d1))) if a != b]
        record = {**copy.deepcopy(test), 'observed': {'normal': n1, 'defective': d1},
                  'repeated_observed': {'normal': n2, 'defective': d2},
                  'variable_items': [{'step': i + 1, 'items': items} for i, items in enumerate(variable) if items],
                  'different_steps': [i + 1 for i in different], 'equal': not different}
        semantic['tests'].append(record)
        originals[test['id']] = (n1, [(n1, n2), (d1, d2)])

    # Finish the frozen plan even when an early comparison fails. This preserves
    # a complete, inspectable record and allows a failed reverify to be retried.
    # Items that two runs of the same version did not reproduce are never compared (R3, see comparison()).
    for test in semantic['tests']:
        n1, d1 = test['observed']['normal'], test['observed']['defective']
        n2, d2 = test['repeated_observed']['normal'], test['repeated_observed']['defective']
        variable = [entry['step'] - 1 for entry in test['variable_items']]
        different = [n - 1 for n in test['different_steps']]
        if test['purpose'] == 'normal':
            if different:
                fail('machine_fail', f'{test["id"]}: normal input differs (R1)')
        else:
            start = test['witness_step'] - 1
            if any(row['ta_crashed'] for row in n1 + n2):
                fail('machine_fail', f'{test["id"]}: normal TA crashed (R2)')
            if not any(i >= start for i in different):
                fail('unknown' if any(i >= start for i in variable) else 'machine_fail',
                     f'{test["id"]}: no reproducible difference at/after witness step (R2)')
            for target in test['targets']:
                for name in condition_names(definitions[by_id[target]['class']]):
                    predicate = WITNESS_CONDITIONS.get(name)
                    if predicate is None:
                        fail('unsupported', f'unsupported witness condition: {name}')
                    passed, reason = predicate(test)
                    if not passed:
                        fail('machine_fail', f'{test["id"]}: {reason}')

    # One defect reverted alone gives the normal TA again, which shows nothing. With several,
    # reverting one must restore its witnesses while the others stay in the source.
    for defect in defects if len(defects) > 1 else ():
        edit_ids = [edit['edit_id'] for edit in defect['edits']]
        destination = work_dir / f'revert_{defect["id"]}'
        revert_edits(normal, defective, destination, edit_ids, moves=moves)
        try:
            artifact = build(destination)
        except ExecutionError as exc:
            fail('unknown', f'revert {edit_ids} cannot be isolated/built: {exc}')
        evidence = []
        for test in tests:
            if test['purpose'] != 'witness' or defect['id'] not in test['targets']:
                continue
            expected, pairs = originals[test['id']]
            observed = [_observe(runner, artifact, test['steps'], uuid) for _ in range(REPETITIONS)]
            _, view = comparison(*pairs, tuple(observed))
            evidence.append({'test_id': test['id'], 'observed': observed,
                             'matches_normal': view(observed[0]) == view(expected)})
        match = all(entry['matches_normal'] for entry in evidence)
        semantic['defect_reverts'].append({'defect_id': defect['id'],
            'witness_matches_normal_after_revert': match, 'tests': evidence})
        if not match:
            fail('unknown', f'{defect["id"]}: defects cannot be isolated')
    return semantic
