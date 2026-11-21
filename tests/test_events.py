"""Scheduling must mutate real shared buffers and fail closed on missed events."""
import copy
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from test_runtime import client as common_client
from test_runtime import entry

from ta_bench.candidate.plan import validate_plan, validate_steps
from ta_bench.common.classes import load_classes
from ta_bench.common.jsonio import atomic_json, load_json
from ta_bench.common.sources import source_digest
from ta_bench.dataset.store import approval_hashes, inspect_case
from ta_bench.errors import ExecutionError, ValidationError
from ta_bench.generation.session import run_generation
from ta_bench.providers.file import FileProvider
from ta_bench.review.blind_export import export_blind
from ta_bench.runtime.docker import DockerRunner
from ta_bench.runtime.events import (
    FEATURE,
    checkpoint_id,
    collect_checkpoints,
    expected_receipts,
    instrument_source,
    validate_receipts,
)
from ta_bench.verification.reverify import reverify_cases

ROOT = Path(__file__).resolve().parents[1]
client = common_client


def candidate():
    return load_json(ROOT / 'examples/shared_record_dus.json')


def witness():
    return candidate()['tests'][-1]


def event_classes():
    classes = load_classes(ROOT / 'config/classes.yaml')
    classes['DUS'].update(supported=True, required_features=[FEATURE],
                          witness_conditions=['shared_memory_changed'])
    classes['DUS'].pop('unsupported_reason', None)
    return classes


@pytest.mark.parametrize('damage', [
    'temporary', 'output', 'bounds', 'empty', 'size', 'negative', 'unknown_trigger',
    'unknown_action', 'code', 'declaration', 'control', 'comment', 'path', 'occurrence', 'bool',
])
def test_invalid_events_are_rejected(damage):
    steps = witness()['steps']
    step = steps[1]
    event = step['events'][0]
    trigger, action = event['trigger'], event['action']
    if damage == 'temporary':
        step['params'][0]['type'] = 'memref_input'
    elif damage == 'output':
        step['params'][0] = {'type': 'shared_memref_output', 'size': 4}
    elif damage == 'bounds':
        action['offset'] = 1
    elif damage == 'empty':
        action.update(expect='', data='')
    elif damage == 'size':
        action['data'] = '00'
    elif damage == 'negative':
        action['param'] = -1
    elif damage == 'unknown_trigger':
        trigger['kind'] = 'sleep'
    elif damage == 'unknown_action':
        action['kind'] = 'shell'
    elif damage == 'code':
        trigger['before'] = 'x = 1; system("ls");'
    elif damage == 'declaration':
        trigger['before'] = 'int x = 1;'
    elif damage == 'control':
        trigger['before'] = 'return x;'
    elif damage == 'comment':
        trigger['before'] += ' // trailing comment'
    elif damage == 'path':
        trigger['path'] = '../ta/entry.c'
    elif damage == 'occurrence':
        trigger['occurrence'] = 0
    else:
        action['offset'] = False
    with pytest.raises(ValidationError):
        validate_steps(steps)


def test_instrumentation_preserves_sources_and_unbraced_scope(tmp_path):
    source = tmp_path / 'source'
    (source / 'ta').mkdir(parents=True)
    code = 'void update_record(void)\n{\n    if (enabled)\n        state->value = request->value;\n    else\n        skip();\n}\n'
    (source / 'ta/entry.c').write_text(code)
    digest = source_digest(source)
    points = collect_checkpoints([witness()])
    evidence = instrument_source(source, tmp_path / 'build', points)
    assert evidence['source_digest'] == digest == source_digest(source)
    generated = (tmp_path / 'build/ta/entry.c').read_text()
    assert 'do { _ta_bench_checkpoint(' in generated and '} while (0);\n    else' in generated
    assert evidence['locations'][0]['line'] == 4
    assert evidence['instrumented_digest'] != digest


@pytest.mark.parametrize('code', [
    'void update_record(void)\n{\n other();\n}\n',
    'void update_record(void)\n{\n state->value = request->value;\n state->value = request->value;\n}\n',
    'void update_record(void)\n{\n /*\n state->value = request->value;\n */\n}\n',
])
def test_missing_ambiguous_or_commented_anchor_rejected(tmp_path, code):
    (tmp_path / 'source/ta').mkdir(parents=True)
    (tmp_path / 'source/ta/entry.c').write_text(code)
    with pytest.raises(ValidationError):
        instrument_source(tmp_path / 'source', tmp_path / 'build', collect_checkpoints([witness()]))


def host_plan():
    test = witness()
    test['steps'] = test['steps'][:2] + test['steps'][-1:]
    step = test['steps'][1]
    step['command_id'] = 77
    step['params'][2] = {'type': 'value_input', 'a': checkpoint_id(step['events'][0]['trigger']), 'b': 2}
    return {'uuid': 'c3d128bd-bf96-438e-bcd6-e3436b30569f', 'steps': test['steps']}


def test_common_client_mutates_shared_memory_at_occurrence(client):
    plan = host_plan()
    step = plan['steps'][1]
    step['events'][0]['trigger']['occurrence'] = 2
    result = subprocess.run([str(client)], input=entry.encode_plan(plan), capture_output=True, check=True)
    row = json.loads(result.stdout.splitlines()[1])
    assert row['params'][1]['a'] == 9
    assert row['params'][0]['data'] == '09000000'
    assert row['events'] == expected_receipts(step)
    validate_receipts(step, row)


@pytest.mark.parametrize('failure', ['missing', 'expect', 'order'])
def test_common_client_schedule_failures_never_produce_valid_observations(client, failure):
    plan = host_plan()
    step = plan['steps'][1]
    if failure == 'missing':
        step['command_id'] = 76
    elif failure == 'expect':
        step['events'][0]['action']['expect'] = '03000000'
    else:
        other = copy.deepcopy(step['events'][0])
        other['trigger']['occurrence'] = 2
        step['events'].insert(0, other)
    result = subprocess.run([str(client)], input=entry.encode_plan(plan), capture_output=True, check=False)
    assert result.returncode == 2 and b'schedule failed' in result.stderr
    assert len(result.stdout.splitlines()) == 1


def test_receipts_are_required_and_not_user_supplied():
    test = witness()
    step = test['steps'][1]
    for row in ({}, {'events': []}, {'events': list(reversed(expected_receipts(step))) + [{}]}):
        with pytest.raises(ExecutionError):
            validate_receipts(step, row)
    proposed = candidate()
    proposed['tests'][-1]['observed'] = {}
    with pytest.raises(ValidationError):
        validate_plan(proposed['tests'], proposed['defects'])


def test_new_class_reuses_features_without_name_specific_code(tmp_path):
    path = tmp_path / 'classes.yaml'
    path.write_text(yaml.safe_dump({'classes': {'SNAPSHOT': event_classes()['DUS']}}))
    assert load_classes(path)['SNAPSHOT']['required_features'] == [FEATURE]


def test_old_runtime_rejected_before_provider_is_initialized(tmp_path):
    class OldRunner:
        features = frozenset()

    def provider():
        pytest.fail('an unsupported runtime must not spend an API request')

    summary = run_generation([{'ta': str(ROOT / 'benchmark/normal/shared_record'),
        'defects': {'DUS': 1}, 'count': 1, 'max_attempts': 3}], event_classes(),
        tmp_path / 'benchmark', tmp_path / 'work', provider, OldRunner)
    assert summary['saved'] == 0
    attempts = summary['requests'][0]['attempts']
    assert len(attempts) == 1 and attempts[0]['status'] == 'unsupported'


@pytest.mark.qemu
def test_real_qemu_shared_events_generation_reverify_and_export(tmp_path):
    image = os.environ.get('TA_BENCH_TEST_IMAGE')
    if not image:
        pytest.skip('set TA_BENCH_TEST_IMAGE to a pinned event-capable image')
    runner = DockerRunner(image, tmp_path / 'runner')
    if FEATURE not in runner.features:
        pytest.skip('runtime has no shared-memory event capability')
    benchmark, work = tmp_path / 'benchmark', tmp_path / 'work'
    normal = benchmark / 'normal/shared_record'
    shutil.copytree(ROOT / 'benchmark/normal/shared_record', normal)
    digest = source_digest(normal)
    classes = event_classes()
    summary = run_generation([{'ta': str(normal), 'defects': {'DUS': 1}, 'count': 1, 'max_attempts': 1}],
        classes, benchmark, work, lambda: FileProvider(ROOT / 'examples/shared_record_dus.json'), lambda: runner)
    assert summary['saved'] == 1, summary
    case = benchmark / 'defective' / summary['requests'][0]['saved'][0]
    info = inspect_case(case, benchmark, classes)
    assert info['status'] == 'unreviewed' and not info['warnings']
    semantic = info['verification']['semantic']
    test = semantic['tests'][-1]
    assert test['different_steps'] == [2, 3]
    assert test['observed']['normal'][1]['params'][1]['a'] == 2
    assert test['observed']['defective'][1]['params'][1]['a'] == 9
    assert test['observed'] == test['repeated_observed']
    assert source_digest(normal) == digest
    assert all('_ta_bench_checkpoint' not in p.read_text() for p in (case / 'source').rglob('*.c'))
    assert reverify_cases(benchmark, classes, work, runner) == [{'case_id': case.name, 'status': 'machine_pass'}]
    assert inspect_case(case, benchmark, classes)['verification']['semantic'] == semantic

    # Automated export fixture in tmp_path only; this is not human benchmark approval.
    labels = load_json(case / 'labels.json')
    labels['review'].update(status='approved', approved_against=approval_hashes(case, normal))
    atomic_json(case / 'labels.json', labels)
    destination = tmp_path / 'blind'
    assert export_blind(benchmark, destination, classes, work)['count'] == 1
    assert all('_ta_bench_checkpoint' not in p.read_text() for p in destination.rglob('*.c'))

    # Persisted receipts are evidence: deleting one must invalidate the case.
    verification = load_json(case / 'verification.json')
    verification['semantic']['tests'][-1]['observed']['normal'][1].pop('events')
    atomic_json(case / 'verification.json', verification)
    assert inspect_case(case, benchmark, classes)['warnings']


def test_spaces_in_buffer_data_are_removed_from_the_stored_plan():
    def steps(data):
        return [{'op': 'open', 'session': 's1'}, {'op': 'invoke', 'session': 's1', 'command_id': 0,
            'params': [{'type': 'memref_input', 'data': data}] + [{'type': 'none'}] * 3}]
    assert validate_steps(steps('00000000 0400 41'))[1]['params'][0]['data'] == '00000000040041'
    for bad in ('00\n00', '0 00'):
        with pytest.raises(ValidationError, match='even-length hex'):
            validate_steps(steps(bad))
