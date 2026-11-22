"""Specification v4 acceptance tests against a real, pinned OP-TEE/QEMU image.

Review actions below are automated UI fixtures in a temporary dataset. They are
not human approval of cases saved under the repository's benchmark directory.
"""
import copy
import os
import re
import shutil
from pathlib import Path

import pytest

from ta_bench.candidate.diff import compute_diff, compute_edits
from ta_bench.candidate.materialize import materialize
from ta_bench.common.classes import load_classes
from ta_bench.common.jsonio import atomic_json, load_json
from ta_bench.common.sources import source_digest
from ta_bench.dataset.store import inspect_case
from ta_bench.generation.session import run_generation
from ta_bench.providers.file import FileProvider
from ta_bench.review.app import create_app
from ta_bench.review.blind_export import export_blind
from ta_bench.runtime.docker import DockerRunner
from ta_bench.verification.reverify import reverify_cases

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.qemu


@pytest.fixture
def project(tmp_path):
    image = os.environ.get('TA_BENCH_TEST_IMAGE')
    if not image:
        pytest.skip('set TA_BENCH_TEST_IMAGE to a locally available pinned runtime image')
    benchmark, work = tmp_path / 'benchmark', tmp_path / 'work'
    normal = benchmark / 'normal' / 'secure_kv'
    shutil.copytree(ROOT / 'examples/secure_kv', normal)
    classes = load_classes(ROOT / 'config/classes.yaml')
    candidate = load_json(ROOT / 'examples/secure_kv_ivw.json')
    runner = DockerRunner(image, work / 'runner', timeout=300)
    return benchmark, work, normal, classes, candidate, runner


def generate(project, candidate):
    benchmark, work, normal, classes, _original, runner = project
    candidate_path = work / 'manual-candidate.json'
    atomic_json(candidate_path, candidate)
    return run_generation(
        [{'ta': str(normal), 'defects': {'IVW': 1}, 'count': 1, 'max_attempts': 1}],
        classes, benchmark, work, lambda: FileProvider(candidate_path), lambda: runner,
    )


def test_real_avb_rejected_write_preserves_state_before_order_mutation(project):
    benchmark, work, _normal, classes, _candidate, runner = project
    if 'rpmb_storage_v1' not in runner.features:
        pytest.skip('AVB requires the Dockerfile.rpmb image')
    normal = benchmark / 'normal' / 'avb'
    shutil.copytree(ROOT / 'benchmark/normal/avb', normal)
    summary = run_generation(
        [{'ta': str(normal), 'defects': {'ORDER': 1}, 'count': 1, 'max_attempts': 1}],
        classes, benchmark, work, lambda: FileProvider(ROOT / 'examples/avb_order.json'), lambda: runner,
    )
    assert (summary['saved'], summary['unmet']) == (1, 0)
    case = benchmark / 'defective' / summary['requests'][0]['saved'][0]
    info = inspect_case(case, benchmark, classes)
    assert info['warnings'] == [] and info['status'] == 'unreviewed'
    ordinary, control, witness = info['verification']['semantic']['tests']
    assert ordinary['equal'] is True and control['equal'] is True
    # Fresh emulated storage starts at zero. Equal and increasing writes succeed,
    # including a 64-bit value, while an out-of-range slot is still rejected.
    for variant in ('normal', 'defective'):
        rows = ordinary['observed'][variant]
        assert rows[1]['params'][1]['b'] == 0
        assert rows[3]['params'][1]['b'] == rows[5]['params'][1]['b'] == 5
        assert (rows[7]['params'][1]['a'], rows[7]['params'][1]['b']) == (1, 7)
        assert rows[8]['result'] == 0xffff0006
        # The identical write of 3 is accepted on fresh storage and rejected once 5
        # is stored: the decision depends on earlier calls, not on the parameters.
        assert control['steps'][1] == witness['steps'][3]
        assert control['observed'][variant][1]['result'] == 0
        assert control['observed'][variant][2]['params'][1]['b'] == 3
        assert witness['observed'][variant][3]['result'] == 0xffff000f
    # Both versions return the same security error. Only the subsequent read
    # exposes the premature state change; a return-code-only test would miss it.
    assert witness['different_steps'] == [5]
    assert witness['observed']['normal'][4]['params'][1]['b'] == 5
    assert witness['observed']['defective'][4]['params'][1]['b'] == 3
    for test in (ordinary, control, witness):
        assert test['variable_items'] == []
        assert test['observed'] == test['repeated_observed']
        assert not any(row['ta_crashed'] for rows in test['observed'].values() for row in rows)


def review(client, app, case_id, action, checks, reason=''):
    page = client.get(f'/cases/{case_id}?reviewer=integration-test-fixture')
    assert page.status_code == 200
    expected = re.search(r'name="expected_against" value="([^"]+)"', page.text)
    assert expected is not None
    return client.post(f'/cases/{case_id}/review', json={
        'csrf_token': app.config['CSRF_TOKEN'], 'expected_against': expected.group(1),
        'reviewer': 'integration-test-fixture', 'action': action, 'checks': checks, 'reason': reason,
    })


def test_real_qemu_generation_review_reverify_and_blind_export(project, tmp_path):
    benchmark, work, normal, classes, candidate, runner = project
    normal_hash = source_digest(normal)
    summary = generate(project, candidate)
    assert (summary['requested'], summary['saved'], summary['unmet']) == (1, 1, 0)
    case = benchmark / 'defective' / summary['requests'][0]['saved'][0]
    assert {p.name for p in case.iterdir()} == {'source', 'labels.json', 'changes.diff', 'verification.json'}
    info = inspect_case(case, benchmark, classes)
    assert info['warnings'] == [] and info['status'] == 'unreviewed'
    assert (case / 'changes.diff').read_text() == compute_diff(normal, case / 'source')
    semantic = info['verification']['semantic']
    assert semantic['machine_validation']['status'] == 'machine_pass'
    ordinary, witness = semantic['tests']
    assert ordinary['equal'] is True and witness['equal'] is False
    assert ordinary['observed']['normal'][2]['params'][0]['b'] == 17
    assert witness['observed']['normal'][1]['result'] == 0xffff0006
    assert witness['observed']['defective'][1]['result'] == 0
    assert witness['different_steps'] == [2]
    for test in semantic['tests']:
        assert test['observed'] == test['repeated_observed']
    assert info['verification']['environment']['image_digest'] == runner.environment['image_digest']

    app = create_app(benchmark, classes, work)
    app.config['TESTING'] = True
    client = app.test_client()
    assert case.name in client.get('/').text
    page = client.get(f'/cases/{case.name}')
    assert '入力と観測' in page.text and 'TA_InvokeCommandEntryPoint' in page.text
    incomplete = {'D1': {'class': True, 'location': False, 'behavior': False}}
    complete = {'D1': {'class': True, 'location': True, 'behavior': True}}
    assert review(client, app, case.name, 'approve', incomplete).status_code == 400
    assert review(client, app, case.name, 'save', incomplete).json['status'] == 'in_review'
    assert review(client, app, case.name, 'reject', incomplete).status_code == 400
    assert review(client, app, case.name, 'reject', incomplete, 'automated rejection fixture').json['status'] == 'rejected'
    assert review(client, app, case.name, 'approve', complete).json['status'] == 'approved'
    before = load_json(case / 'verification.json')
    approved_hashes = inspect_case(case, benchmark, classes)['hashes']

    results = reverify_cases(benchmark, classes, work, runner)
    assert results == [{'case_id': case.name, 'status': 'machine_pass'}]
    after = load_json(case / 'verification.json')
    assert after['semantic'] == before['semantic']
    assert after['run_meta'] != before['run_meta']
    assert inspect_case(case, benchmark, classes)['status'] == 'approved'
    assert inspect_case(case, benchmark, classes)['hashes'] == approved_hashes
    archived = list((work / 'reverify' / case.name).glob('*/previous-verification.json'))
    assert len(archived) == 1 and load_json(archived[0]) == before

    destination = tmp_path / 'detector-input'
    result = export_blind(benchmark, destination, classes, work)
    assert result['count'] == 1
    sample = next(destination.iterdir())
    assert sample.name.startswith('sample_') and case.name not in sample.name
    files = [p for p in sample.rglob('*') if p.is_file()]
    assert files and all(p.suffix in {'.c', '.h', '.S', '.s'} for p in files)
    assert all(p.relative_to(sample).parts[0] == 'ta' for p in files)
    for path in files:
        assert path.read_bytes() == (case / 'source' / path.relative_to(sample)).read_bytes()
    mapping = Path(result['mapping_path'])
    assert not mapping.is_relative_to(destination)
    assert load_json(mapping)['cases'][sample.name]['case_id'] == case.name

    labels_path = case / 'labels.json'
    labels = load_json(labels_path)
    changed = copy.deepcopy(labels)
    changed['defects'][0]['reason'] += ' (automated stale fixture)'
    atomic_json(labels_path, changed)
    assert inspect_case(case, benchmark, classes)['status'] == 'stale'
    assert 'stale' in client.get(f'/cases/{case.name}').text
    with pytest.raises(ValueError, match='eligible'):
        export_blind(benchmark, tmp_path / 'stale-input', classes, work)
    atomic_json(labels_path, labels)
    for path in (normal / 'ta/entry.c', case / 'source/ta/entry.c'):
        original = path.read_bytes()
        try:
            path.write_bytes(original + b'\n')
            assert inspect_case(case, benchmark, classes)['status'] == 'stale'
        finally:
            path.write_bytes(original)
    assert source_digest(normal) == normal_hash
    assert inspect_case(case, benchmark, classes)['status'] == 'approved'


@pytest.mark.parametrize('kind,reason', [
    ('makefile', 'forbidden replacement path'),
    ('broken_function', '(R1)'),
])
def test_real_qemu_rejects_specification_negative_candidates(project, kind, reason, monkeypatch):
    benchmark, work, normal, _classes, candidate, runner = project
    original_hash = source_digest(normal)
    if kind == 'makefile':
        candidate['files']['Makefile'] = 'all:\n\tfalse\n'

        def forbidden_build(_source):
            pytest.fail('a forbidden Makefile edit reached the build stage')

        monkeypatch.setattr(runner, 'build', forbidden_build)
    else:
        code = candidate['files']['ta/entry.c'].replace('state->values[index] = params[0].value.b;',
                                                        'state->values[index] = params[0].value.b + 1;')
        candidate['files']['ta/entry.c'] = code
        tree = work / 'negative-source'
        materialize(normal, tree, candidate['files'])
        edits = compute_edits(normal, tree)
        assert len(edits) == 2
        candidate['defects'][0]['edits'] = [e['edit_id'] for e in edits]
        target = next(i for i, line in enumerate(code.splitlines(), 1) if 'state->values[index] =' in line)
        candidate['defects'][0]['detector_targets'][0]['lines'] = [target, target]
    summary = generate(project, candidate)
    assert (summary['requested'], summary['saved'], summary['unmet']) == (1, 0, 1)
    attempt = summary['requests'][0]['attempts'][0]
    assert attempt['status'] == 'machine_fail' and reason in attempt['reason']
    assert not list((benchmark / 'defective').glob('case_*'))
    assert source_digest(normal) == original_hash
    results = list((work / 'runs' / summary['run_id']).glob('request_*/attempt_*/result.json'))
    assert len(results) == 1 and load_json(results[0])['status'] == 'machine_fail'
