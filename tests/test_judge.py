"""Tests use explicit in-process observations; never represent QEMU verification."""
from copy import deepcopy
from pathlib import Path
from typing import ClassVar

import pytest

from ta_bench.candidate.check import check_candidate
from ta_bench.errors import JudgmentError
from ta_bench.verification.judge import verify

NORMAL = 'int read_slot(int index) {\n    if (index >= 8)\n        return -1;\n    return index + 1;\n}\n'
DEFECTIVE = 'int read_slot(int index) {\n    return index + 1;\n}\n'
CLASSES = {'IVW': {'supported': True, 'description': 'bounds', 'extra_condition': 'normal_error_at_witness'}}
UUID = 'd987bb20-2323-4a70-9d97-717255082611'


def test_plan():
    def steps(n):
        return [{'op': 'open', 'session': 's1'}, {'op': 'invoke', 'session': 's1', 'command_id': 0,
            'params': [{'type': 'value_inout', 'a': n, 'b': 0}] + [{'type': 'none'}] * 3},
            {'op': 'close', 'session': 's1'}]
    return [{'id': 'T01', 'purpose': 'normal', 'targets': [], 'steps': steps(2)},
            {'id': 'T02', 'purpose': 'witness', 'targets': ['D1'], 'witness_step': 2, 'steps': steps(8)}]


# Avoid pytest treating the data factory as a test.
test_plan.__test__ = False


def defect():
    return {'id': 'D1', 'class': 'IVW', 'edits': ['E1'], 'detector_targets': [
        {'path': 'ta/entry.c', 'function': 'read_slot', 'lines': [2, 2], 'role': 'effect'}],
        'witness_test_ids': ['T02'], 'reason': 'range check removed'}


class FakeRunner:
    publishable = True  # Only used within tests, never exposed by CLI.
    environment: ClassVar[dict] = {'optee_revision': 'test', 'qemu_revision': 'test', 'toolchain': 'test',
                       'image_digest': 'sha256:' + '0' * 64, 'runner_version': 'test'}

    def __init__(self, mode=''):
        self.mode, self.calls = mode, {}

    def build(self, source):
        return Path(source)

    def run(self, artifact, steps, uuid):
        code = (artifact / 'ta/entry.c').read_text()
        guard = 'if (index >= 8)' in code
        index = steps[1]['params'][0]['a']
        key = (str(artifact), index)
        self.calls[key] = self.calls.get(key, 0) + 1
        rows = [{'op': s['op'], 'result': 0, 'origin': 4, 'params': [], 'ta_crashed': False} for s in steps]
        rows[1]['result'] = 0xffff0006 if guard and index >= 8 else 0
        rows[1]['params'] = [{'type': 'value_inout', 'a': index, 'b': 0}]
        if self.mode == 'broken' and not guard and index == 2:
            rows[1]['result'] = 9
        if self.mode == 'nondeterministic' and guard and index == 8:
            rows[1]['result'] += self.calls[key] % 2
        if self.mode == 'defective_nondeterministic' and not guard and index == 8:
            rows[1]['result'] += self.calls[key] % 2
        if self.mode == 'crash' and guard and index == 8:
            rows[1]['ta_crashed'] = True
        if self.mode in {'no_difference', 'only_variable_differs'}:
            rows[1]['result'] = 0
        if self.mode in {'variable_bytes', 'only_variable_differs'} and index == 8:
            # A fixed status word followed by a value that changes on every run (a timer).
            rows[1]['params'] = [{'type': 'memref_output', 'size': 8,
                                  'data': '02000000' + f'{sum(self.calls.values()) % 256:02x}000000'}]
        if self.mode == 'defective_random_output' and not guard and index == 8:
            # The defective TA returns fresh random bytes where the normal TA rejects the request.
            rows[1]['params'] = [{'type': 'memref_output', 'size': 4, 'data': f'{self.calls[key]:08x}'}]
        return deepcopy(rows)


@pytest.fixture
def trees(tmp_path):
    normal, defective = tmp_path / 'normal', tmp_path / 'defective'
    for root, code in ((normal, NORMAL), (defective, DEFECTIVE)):
        (root / 'ta').mkdir(parents=True)
        (root / 'ta/entry.c').write_text(code)
        (root / 'ta/id.h').write_text(f'#define SAMPLE_UUID "{UUID}"\n')
    return normal, defective


def test_all_rules_pass(trees, tmp_path):
    normal, defective = trees
    defects = check_candidate(normal, defective, [defect()], CLASSES)
    semantic = verify(normal, defective, defects, test_plan(), CLASSES, FakeRunner(), UUID, tmp_path)
    assert semantic['machine_validation']['status'] == 'machine_pass'
    assert semantic['tests'][1]['different_steps'] == [2]
    # Reverting the only defect would rebuild the normal TA, so nothing is reverted.
    assert semantic['defect_reverts'] == [] and not list(tmp_path.glob('revert_*'))


def test_only_unreproduced_items_are_left_out_of_the_witness_step(trees, tmp_path):
    normal, defective = trees
    defects = check_candidate(normal, defective, [defect()], CLASSES)
    semantic = verify(normal, defective, defects, test_plan(), CLASSES, FakeRunner('variable_bytes'), UUID, tmp_path)
    witness = semantic['tests'][1]
    assert semantic['machine_validation']['status'] == 'machine_pass'
    assert witness['variable_items'] == [{'step': 2, 'items': [
        {'param': 0, 'field': 'data'}]}]
    assert witness['different_steps'] == [2]
    assert semantic['tests'][0]['variable_items'] == []


def test_items_the_defective_runs_did_not_reproduce_are_left_out_too(trees, tmp_path):
    normal, defective = trees
    defects = check_candidate(normal, defective, [defect()], CLASSES)
    semantic = verify(normal, defective, defects, test_plan(), CLASSES,
                      FakeRunner('defective_random_output'), UUID, tmp_path)
    assert semantic['machine_validation']['status'] == 'machine_pass'
    witness = semantic['tests'][1]
    assert witness['variable_items'] == [{'step': 2, 'items': [{'param': 0, 'field': 'data'}]}]
    assert witness['different_steps'] == [2]


def test_a_difference_only_inside_variable_bytes_is_not_evidence(trees, tmp_path):
    normal, defective = trees
    defects = check_candidate(normal, defective, [defect()], CLASSES)
    with pytest.raises(JudgmentError, match='no reproducible difference') as error:
        verify(normal, defective, defects, test_plan(), CLASSES, FakeRunner('only_variable_differs'), UUID, tmp_path)
    assert error.value.status == 'unknown'


@pytest.mark.parametrize('mode,status', [('broken', 'machine_fail'), ('nondeterministic', 'unknown'),
    ('defective_nondeterministic', 'unknown'), ('crash', 'machine_fail'), ('no_difference', 'machine_fail')])
def test_rules_reject_bad_evidence(trees, tmp_path, mode, status):
    normal, defective = trees
    defects = check_candidate(normal, defective, [defect()], CLASSES)
    with pytest.raises(JudgmentError) as error:
        verify(normal, defective, defects, test_plan(), CLASSES, FakeRunner(mode), UUID, tmp_path)
    assert error.value.status == status
    assert error.value.semantic['machine_validation']['status'] == status


def test_a_defect_of_several_edits_passes_without_reverting_each_edit(trees, tmp_path):
    # Whether every edit is needed is not measured; a reviewer decides it from the diff.
    normal, defective = trees
    (normal / 'ta/entry.c').write_text(NORMAL + '\nint other(void) {\n    return 3;\n}\n')
    (defective / 'ta/entry.c').write_text(DEFECTIVE + '\nint other(void) {\n    return 4;\n}\n')
    d = defect()
    d['edits'] = ['E1', 'E2']
    defects = check_candidate(normal, defective, [d], CLASSES)
    semantic = verify(normal, defective, defects, test_plan(), CLASSES, FakeRunner(), UUID, tmp_path)
    assert semantic['machine_validation']['status'] == 'machine_pass'
    assert 'necessity' not in semantic and not list(tmp_path.glob('revert_*'))
