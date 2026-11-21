# ruff: noqa: F811 -- imported pytest fixture is injected by parameter name
"""Regression cases from the integration audit: interruption and malformed AI output."""
from copy import deepcopy

import pytest
from test_generate import (
    run_case,
    setup_run,  # noqa: F401 -- reusable pytest fixture
)
from test_judge import CLASSES, UUID, FakeRunner, defect, test_plan

from ta_bench.candidate.check import check_candidate
from ta_bench.candidate.plan import validate_plan, validate_steps
from ta_bench.common.jsonio import atomic_json, load_json
from ta_bench.dataset.store import approval_hashes, inspect_case
from ta_bench.errors import JudgmentError, ValidationError
from ta_bench.generation import session
from ta_bench.generation.session import run_generation
from ta_bench.providers.file import FileProvider
from ta_bench.verification.judge import verify
from ta_bench.verification.reverify import reverify_cases


@pytest.mark.parametrize('bad', [{}, {'id': []}, {'id': {}}, {'id': None}])
def test_malformed_defect_id_raises_validation_error(bad):
    value = defect()
    value.pop('id')
    value.update(bad)
    with pytest.raises(ValidationError):
        validate_plan(test_plan(), [value])


@pytest.mark.parametrize('bad', [None, {}, [{'id': 'T02'}]])
def test_malformed_witness_ids_raises_validation_error(bad):
    value = defect()
    value['witness_test_ids'] = bad
    with pytest.raises(ValidationError):
        validate_plan(test_plan(), [value])


def test_unhashable_parameter_type_raises_validation_error():
    steps = test_plan()[0]['steps']
    steps[1]['params'][0]['type'] = []
    with pytest.raises(ValidationError):
        validate_steps(steps)


@pytest.mark.parametrize('kind', ['memref_input', 'memref_inout',
                                  'shared_memref_input', 'shared_memref_inout'])
def test_oversized_buffer_reports_test_step_parameter_and_byte_counts(kind):
    plan = test_plan()
    plan[0]['steps'][1]['params'][0] = {'type': kind, 'size': 65, 'data': '41' * 107}
    with pytest.raises(ValidationError) as error:
        validate_plan(plan, [defect()])
    assert str(error.value) == (
        f'{plan[0]["id"]}: step 2, params[0]: buffer data exceeds size (107 bytes > 65 bytes)')


@pytest.mark.parametrize('bad', [12, None, [], 'not-a-uuid'])
def test_open_uuid_has_valid_string_type(bad):
    steps = test_plan()[0]['steps']
    steps[0]['uuid'] = bad
    with pytest.raises(ValidationError):
        validate_steps(steps)


def test_resume_recovers_published_case_before_state_commit(setup_run, monkeypatch):
    benchmark, work, _normal, candidate, _request = setup_run
    real_save = session.save_case

    def interrupted_save(*args, **kwargs):
        real_save(*args, **kwargs)
        raise KeyboardInterrupt()

    monkeypatch.setattr(session, 'save_case', interrupted_save)
    with pytest.raises(KeyboardInterrupt):
        run_case(setup_run)
    published = list((benchmark / 'defective').glob('case_*'))
    assert len(published) == 1
    run_id = next((work / 'runs').iterdir()).name
    monkeypatch.setattr(session, 'save_case', real_save)
    summary = run_generation([], CLASSES, benchmark, work, lambda: FileProvider(candidate),
                             lambda: FakeRunner(), resume=run_id, progress=lambda _: None)
    assert summary['saved'] == 1 and summary['unmet'] == 0
    assert summary['requests'][0]['saved'] == [published[0].name]
    assert len(summary['requests'][0]['attempts']) == 1


def test_failed_reverify_remains_inspectable_and_recoverable(setup_run):
    benchmark, work, normal, _candidate, _request = setup_run
    summary = run_case(setup_run)
    case = benchmark / 'defective' / summary['requests'][0]['saved'][0]
    labels = load_json(case / 'labels.json')
    labels['review'].update(status='approved', reviews=[], approved_against=approval_hashes(case, normal))
    atomic_json(case / 'labels.json', labels)
    results = reverify_cases(benchmark, CLASSES, work, FakeRunner('broken'))
    assert results[0]['status'] == 'machine_fail'
    inspected = inspect_case(case, benchmark, CLASSES)
    assert inspected['structural_valid'], inspected['warnings']
    assert inspected['status'] == 'stale'
    rerun = reverify_cases(benchmark, CLASSES, work, FakeRunner())
    assert rerun[0]['status'] == 'machine_pass'
    assert inspect_case(case, benchmark, CLASSES)['structural_valid']


def test_valid_stale_approval_can_be_reverified(setup_run):
    benchmark, work, normal, _candidate, _request = setup_run
    summary = run_case(setup_run)
    case = benchmark / 'defective' / summary['requests'][0]['saved'][0]
    labels = load_json(case / 'labels.json')
    labels['review'].update(status='approved', reviews=[], approved_against=approval_hashes(case, normal))
    atomic_json(case / 'labels.json', labels)
    labels['defects'][0]['reason'] += ' (review wording updated)'
    atomic_json(case / 'labels.json', labels)
    assert inspect_case(case, benchmark, CLASSES)['status'] == 'stale'
    results = reverify_cases(benchmark, CLASSES, work, FakeRunner())
    assert results[0]['status'] == 'machine_pass'
    assert inspect_case(case, benchmark, CLASSES)['status'] == 'stale'


def test_several_defects_must_each_be_separable(tmp_path):
    normal, defective = tmp_path / 'normal', tmp_path / 'defective'
    one = 'int first(int index) {\n    if (index >= 8)\n        return -1;\n    return index;\n}\n'
    two = one.replace('first', 'second')
    changed = 'int first(int index) {\n    return index;\n}\n'
    for root, code in ((normal, one + '\n' + two),
                       (defective, changed + '\n' + changed.replace('first', 'second'))):
        (root / 'ta').mkdir(parents=True)
        (root / 'ta/entry.c').write_text(code)
    defects = [dict(defect(), detector_targets=[{'path': 'ta/entry.c', 'function': 'first', 'lines': [2, 2], 'role': 'effect'}]),
               dict(defect(), id='D2', edits=['E2'], witness_test_ids=['T03'],
                    detector_targets=[{'path': 'ta/entry.c', 'function': 'second', 'lines': [6, 6], 'role': 'effect'}])]
    defects = check_candidate(normal, defective, defects, CLASSES)
    plan = test_plan()
    plan.append(dict(deepcopy(plan[1]), id='T03', targets=['D2']))
    semantic = verify(normal, defective, defects, plan, CLASSES, FakeRunner(), UUID, tmp_path / 'separable')
    assert [(revert['defect_id'], revert['witness_matches_normal_after_revert'])
            for revert in semantic['defect_reverts']] == [('D1', True), ('D2', True)]
    assert (tmp_path / 'separable/revert_D1/ta/entry.c').read_text().count('if (index >= 8)') == 1

    class CoupledRunner(FakeRunner):
        def run(self, artifact, steps, uuid):
            rows = super().run(artifact, steps, uuid)
            both_present = (artifact / 'ta/entry.c').read_text().count('if (index >= 8)') == 2
            index = steps[1]['params'][0]['a']
            rows[1]['result'] = 0xffff0006 if both_present and index >= 8 else 0
            return rows

    with pytest.raises(JudgmentError) as error:
        verify(normal, defective, defects, plan, CLASSES, CoupledRunner(), UUID, tmp_path)
    assert error.value.status == 'unknown'
