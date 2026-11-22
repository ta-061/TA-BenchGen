
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_judge import CLASSES, DEFECTIVE, NORMAL, UUID, FakeRunner, defect, test_plan

from ta_bench.candidate.materialize import materialize
from ta_bench.candidate.plan import validate_plan
from ta_bench.cli import main
from ta_bench.common.jsonio import atomic_json, load_json
from ta_bench.dataset.store import approval_hashes, inspect_case
from ta_bench.errors import ValidationError
from ta_bench.generation.session import run_generation
from ta_bench.providers.file import FileProvider
from ta_bench.verification.reverify import reverify_cases


@pytest.fixture
def setup_run(tmp_path):
    benchmark, work = tmp_path / 'benchmark', tmp_path / 'work'
    normal = benchmark / 'normal' / 'sample'
    (normal / 'ta').mkdir(parents=True)
    (normal / 'ta/entry.c').write_text(NORMAL)
    (normal / 'ta/id.h').write_text(f'#define SAMPLE_UUID "{UUID}"\n')
    candidate = tmp_path / 'candidate.json'
    atomic_json(candidate, {'files': {'ta/entry.c': DEFECTIVE}, 'defects': [defect()], 'tests': test_plan()})
    request = [{'ta': str(normal), 'defects': {'IVW': 1}, 'count': 1, 'max_attempts': 3}]
    return benchmark, work, normal, candidate, request


def run_case(setup_run, runner=None):
    benchmark, work, _normal, candidate, request = setup_run
    summary = run_generation(request, CLASSES, benchmark, work,
        lambda: FileProvider(candidate), lambda: runner or FakeRunner(), progress=lambda _: None)
    return summary


def test_generation_save_review_reverify_and_resume(setup_run):
    benchmark, work, normal, _candidate, _request = setup_run
    summary = run_case(setup_run)
    assert summary['saved'] == 1 and summary['unmet'] == 0
    case = benchmark / 'defective' / summary['requests'][0]['saved'][0]
    assert inspect_case(case, benchmark, CLASSES)['warnings'] == []
    verification = load_json(case / 'verification.json')
    assert verification['generation']['model_id'] == 'manual-candidate'
    labels = load_json(case / 'labels.json')
    labels['review'].update(status='approved', reviews=[], approved_against=approval_hashes(case, normal))
    atomic_json(case / 'labels.json', labels)
    results = reverify_cases(benchmark, CLASSES, work, FakeRunner())
    assert results[0]['status'] == 'machine_pass'
    assert inspect_case(case, benchmark, CLASSES)['status'] == 'approved'
    resumed = run_generation([], CLASSES, benchmark, work, lambda: None, lambda: None,
                             resume=summary['run_id'], progress=lambda _: None)
    assert resumed['saved'] == 1
    assert len(resumed['requests'][0]['attempts']) == 1


def test_duplicate_and_attempt_limit_are_honest(setup_run):
    setup_run[-1][0]['count'] = 2
    summary = run_case(setup_run)
    assert summary['requested'] == 2 and summary['saved'] == 1 and summary['unmet'] == 1
    assert len(summary['requests'][0]['attempts']) == 3
    assert summary['requests'][0]['attempts'][-1]['status'] == 'machine_fail'


def test_failed_and_development_cases_never_published(setup_run):
    benchmark = setup_run[0]
    summary = run_case(setup_run, FakeRunner('broken'))
    assert summary['saved'] == 0
    assert not (benchmark / 'defective').exists()
    runner = FakeRunner()
    runner.publishable = False
    summary = run_case(setup_run, runner)
    assert summary['saved'] == 0
    assert not (benchmark / 'defective').exists()


def test_unsupported_does_not_initialize_api_or_runner(setup_run):
    benchmark, work, _normal, _candidate, request = setup_run
    request[0]['defects'] = {'DUS': 1}
    def forbidden():
        pytest.fail('must not initialize provider or runner')
    summary = run_generation(request, {'DUS': {'supported': False}}, benchmark, work,
                             forbidden, forbidden, progress=lambda _: None)
    assert summary['saved'] == 0 and summary['unmet'] == 1


def test_makefile_change_rejected_before_execution(setup_run):
    _benchmark, _work, normal, candidate, _request = setup_run
    (normal / 'Makefile').write_text('all:\n\ttrue\n')
    value = load_json(candidate)
    value['files']['Makefile'] = 'all:\n\texit 1\n'
    atomic_json(candidate, value)
    class Unused(FakeRunner):
        def build(self, source):
            pytest.fail('static check must happen before build')
    summary = run_case(setup_run, Unused())
    assert all(a['status'] == 'machine_fail' for a in summary['requests'][0]['attempts'])


def test_symlink_normal_root_rejected_before_resolution(setup_run, tmp_path):
    normal = setup_run[2]
    alias = tmp_path / 'normal-alias'
    alias.symlink_to(normal, target_is_directory=True)
    setup_run[-1][0]['ta'] = str(alias)
    with pytest.raises(ValidationError, match='real directory'):
        run_case(setup_run)
    assert not (setup_run[0] / 'defective').exists()


@pytest.mark.parametrize('name', ['../ta/entry.c', '/ta/entry.c', 'ta/../ta/entry.c', 'ta/new.c', 'ta//entry.c', 'host/x.c'])
def test_no_path_traversal(setup_run, tmp_path, name):
    with pytest.raises(ValidationError):
        materialize(setup_run[2], tmp_path / 'output', {name: DEFECTIVE})


def test_plan_forbids_executable_data_and_invalid_params():
    plan = test_plan()
    plan[0]['steps'].append({'op': 'shell', 'command': 'echo no'})
    with pytest.raises(ValidationError):
        validate_plan(plan, [defect()])
    plan = test_plan()
    plan[0]['steps'][1]['params'][0]['a'] = True
    with pytest.raises(ValidationError):
        validate_plan(plan, [defect()])
    plan = test_plan()
    plan[1]['witness_step'] = 0
    with pytest.raises(ValidationError):
        validate_plan(plan, [defect()])


def test_cli_help_and_invalid_request(capsys):
    with pytest.raises(SystemExit) as exc:
        main(['--help'])
    assert exc.value.code == 0
    assert main(['generate', '--ta', 'examples/secure_kv', '--defects', 'UNKNOWN=1']) == 2
    assert 'unknown class' in capsys.readouterr().err


def test_cli_resume_restores_candidate_and_runtime_settings(setup_run, monkeypatch):
    from ta_bench import cli
    benchmark, work, normal, candidate, _request = setup_run
    classes_path = work.parent / 'custom-classes.json'
    atomic_json(classes_path, CLASSES)
    original = FileProvider.propose
    calls = 0

    def interrupt_once(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise KeyboardInterrupt()
        return original(self, *args, **kwargs)

    monkeypatch.setattr(FileProvider, 'propose', interrupt_once)
    monkeypatch.setattr(cli, 'DockerRunner', lambda *a, **kw: FakeRunner())
    assert main(['generate', '--ta', str(normal), '--candidate', str(candidate),
                 '--defects', 'IVW=1', '--max-attempts', '2', '--image', 'sha256:' + '0' * 64,
                 '--classes', str(classes_path), '--benchmark', str(benchmark), '--work-dir', str(work)]) == 130
    run_id = next((work / 'runs').iterdir()).name
    assert main(['generate', '--resume', run_id, '--work-dir', str(work)]) == 0
    assert calls == 2
    state = load_json(work / 'runs' / run_id / 'state.json')
    assert len(state['requests'][0]['saved']) == 1


@pytest.mark.parametrize('registry_change', ['replace', 'delete'])
def test_cli_resume_freezes_api_options_but_reloads_secrets(setup_run, monkeypatch, registry_change):
    from ta_bench import cli
    from ta_bench.providers import api

    benchmark, work, normal, candidate, _request = setup_run
    classes_path = work.parent / 'custom-classes.json'
    atomic_json(classes_path, CLASSES)
    models = work.parent / 'models.yaml'
    key_file = models.parent / 'api_keys.local.yaml'
    atomic_json(models, {'use': 'hosted', 'models': {'hosted': {
        'api_url': 'https://llm.example/v1/chat/completions', 'model': 'initial-model',
        'api_key_env': 'TEST_PROFILE_KEY', 'headers_env': {'x-workspace': 'TEST_PROFILE_WORKSPACE'},
        'max_tokens': 4096, 'temperature': 0.25, 'json_mode': False, 'read_timeout': 42,
    }}})
    monkeypatch.delenv('TEST_PROFILE_KEY', raising=False)
    monkeypatch.delenv('TEST_PROFILE_WORKSPACE', raising=False)
    monkeypatch.delenv('TA_BENCH_USE', raising=False)
    atomic_json(key_file, {'TEST_PROFILE_KEY': 'first-secret', 'TEST_PROFILE_WORKSPACE': 'first-workspace'})
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        if len(calls) == 1:
            return SimpleNamespace(status_code=401, json=dict)
        return SimpleNamespace(status_code=200, json=lambda: {
            'choices': [{'message': {'content': json.dumps(load_json(candidate))}}]})

    monkeypatch.setattr(api.requests, 'post', post)
    monkeypatch.setattr(cli, 'DockerRunner', lambda *a, **kw: FakeRunner())
    assert main(['generate', '--ta', str(normal), '--models', str(models),
                 '--defects', 'IVW=1', '--max-attempts', '2', '--image', 'sha256:' + '0' * 64,
                 '--classes', str(classes_path), '--benchmark', str(benchmark), '--work-dir', str(work)]) == 2
    run_dir = next((work / 'runs').iterdir())
    if registry_change == 'delete':
        models.unlink()
    else:
        atomic_json(models, {'use': 'different', 'models': {'different': {
            'api_url': 'https://different.example/v1/chat/completions', 'model': 'different-model',
        }}})
    monkeypatch.setenv('TA_BENCH_MODEL', 'environment-model')
    monkeypatch.setenv('TA_BENCH_API_URL', 'https://environment.example/v1/chat/completions')
    monkeypatch.setenv('TA_BENCH_USE', 'different')
    atomic_json(key_file, {'TEST_PROFILE_KEY': 'corrected-secret', 'TEST_PROFILE_WORKSPACE': 'corrected-workspace'})

    assert main(['generate', '--resume', run_dir.name, '--work-dir', str(work)]) == 0
    assert len(calls) == 2
    assert calls[0][0] == calls[1][0] == 'https://llm.example/v1/chat/completions'
    for _, options in calls:
        assert options['json']['model'] == 'initial-model'
        assert options['json']['max_tokens'] == 4096 and options['json']['temperature'] == 0.25
        assert 'response_format' not in options['json']
        assert options['timeout'] == (15, 42)
    assert calls[0][1]['headers'] == {'Authorization': 'Bearer first-secret', 'x-workspace': 'first-workspace'}
    assert calls[1][1]['headers'] == {'Authorization': 'Bearer corrected-secret', 'x-workspace': 'corrected-workspace'}
    state = load_json(run_dir / 'state.json')
    assert len(state['requests'][0]['saved']) == 1
    assert state['settings']['model_profile']['model'] == 'initial-model'
    for path in run_dir.rglob('*.json'):
        assert all(secret not in path.read_text() for secret in (
            'first-secret', 'corrected-secret', 'first-workspace', 'corrected-workspace'))

    # A completed run remains inspectable even after credentials have been removed.
    key_file.unlink()
    assert main(['generate', '--resume', run_dir.name, '--work-dir', str(work)]) == 0
    assert len(calls) == 2


def test_cli_legacy_resume_ignores_new_profile_selection(setup_run, monkeypatch):
    from ta_bench import cli
    from ta_bench.providers import api

    benchmark, work, _normal, candidate, request = setup_run
    classes_path = work.parent / 'custom-classes.json'
    atomic_json(classes_path, CLASSES)
    settings = {'candidate': None, 'model': 'legacy-model',
                'api_url': 'https://legacy.example/v1/chat/completions',
                'image': 'sha256:' + '0' * 64, 'classes': str(classes_path), 'benchmark': str(benchmark)}

    def interrupt():
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        run_generation(request, CLASSES, benchmark, work, interrupt, lambda: FakeRunner(),
                       progress=lambda _: None, settings=settings)
    run_dir = next((work / 'runs').iterdir())
    monkeypatch.setenv('TA_BENCH_USE', 'unrelated-profile')
    monkeypatch.setenv('OPENAI_API_KEY', 'test-legacy-secret')
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs['json']['model']))
        return SimpleNamespace(status_code=200, json=lambda: {
            'choices': [{'message': {'content': json.dumps(load_json(candidate))}}]})

    monkeypatch.setattr(api.requests, 'post', post)
    monkeypatch.setattr(cli, 'DockerRunner', lambda *a, **kw: FakeRunner())
    assert main(['generate', '--resume', run_dir.name, '--work-dir', str(work)]) == 0
    assert calls == [('https://legacy.example/v1/chat/completions', 'legacy-model')]
    assert load_json(run_dir / 'state.json')['settings']['model_profile']['model'] == 'legacy-model'


def test_retry_feedback_keeps_output_lengths_values_and_truncation():
    from ta_bench.generation.session import observed_differences, proposed_changes, proposed_defects

    def row(result, crashed, data, value):
        return {'result': result, 'origin': 4, 'ta_crashed': crashed, 'params': [
            {'type': 'memref_input', 'data': 'aa' * 500},
            {'type': 'memref_output', 'size': len(data) // 2, 'data': data},
            {'type': 'value_output', 'a': 7, 'b': value}]}

    semantic = {'tests': [{'id': 'T01', 'purpose': 'normal', 'different_steps': [2], 'observed': {
        'normal': [row(0, False, '', 0), row(0, False, '01' * 100, 0)],
        'defective': [row(0, False, '', 0), row(0xffff3024, True, '00' * 100, 99)]}}]}
    feedback = observed_differences(semantic)[0]
    assert feedback['normal']['outputs'] == [
        {'param': 1, 'type': 'memref_output', 'size': 100, 'data': '01' * 32,
         'data_bytes': 100, 'data_truncated': True},
        {'param': 2, 'type': 'value_output', 'a': 7, 'b': 0}]
    assert feedback['defective']['ta_crashed'] is True
    assert feedback['defective']['outputs'][1]['b'] == 99
    assert {'param': 2, 'field': 'b'} in feedback['different_items']
    assert 'aa' * 500 not in json.dumps(feedback)
    assert proposed_defects({'unsupported': 'x'}) == []
    target = {'role': 'effect', 'path': 'ta/entry.c', 'function': 'f', 'lines': [4, 4]}
    assert proposed_defects({'defects': [{'id': 'D1', 'class': 'DUS', 'reason': 'r' * 999,
                                          'detector_targets': [{**target, 'extra': 'x' * 999}, 'junk']}]}) == [
        {'id': 'D1', 'class': 'DUS', 'reason': 'r' * 300, 'detector_targets': [target]}]
    assert proposed_defects({'defects': [{'class': 'DUS', 'detector_targets': 'x'}]}) == [
        {'id': None, 'class': 'DUS', 'reason': None, 'detector_targets': []}]
    assert proposed_changes({'files': {}}) == []
    assert proposed_changes({'changes': [{'path': 'ta/entry.c', 'defect': 'D1', 'old': 'a' * 5000, 'new': 'b'}] * 40}) == [
        {'path': 'ta/entry.c', 'defect': 'D1', 'old': 'a' * 1000, 'new': 'b'}] * 16


def test_failed_corpus_feedback_explains_signature_length_not_random_bytes():
    from ta_bench.generation.session import failed_test_feedback

    def row(size, data):
        return {'op': 'invoke', 'result': 0, 'origin': 4, 'ta_crashed': False, 'params': [
            {'type': 'memref_input', 'data': 'aa' * 32},
            {'type': 'memref_output', 'size': size, 'data': data}]}

    test = {'id': 'Cstored', 'purpose': 'normal', 'steps': test_plan()[0]['steps'],
            'different_steps': [2], 'variable_items': [{'step': 2, 'items': [{'param': 1, 'field': 'data'}]}],
            'observed': {'normal': [row(0, ''), row(64, '01' * 64), row(0, '')],
                         'defective': [row(0, ''), row(96, '02' * 96), row(0, '')]}}
    test['steps'][1]['params'] = [
        {'type': 'memref_input', 'data': 'aa' * 32}, {'type': 'memref_output', 'size': 128},
        {'type': 'none'}, {'type': 'none'}]
    semantic = {'machine_validation': {'reason': 'Cstored: normal input differs (R1)'}, 'tests': [test]}
    before = deepcopy(semantic)
    feedback = failed_test_feedback(semantic, test_plan())
    assert feedback['source'] == 'corpus'
    assert feedback['steps'] == test['steps']
    observed = feedback['observations'][1]
    assert observed['normal']['outputs'][0]['size'] == 64
    assert observed['defective']['outputs'][0]['size'] == 96
    assert observed['normal']['outputs'][0]['data'] == observed['defective']['outputs'][0]['data'] == '**'
    assert observed['different_items'] == [{'param': 1, 'field': 'size'}]
    assert observed['ignored_variable_items'] == [{'param': 1, 'field': 'data'}]
    assert semantic == before


@pytest.mark.parametrize('late_crash', [False, True])
def test_failed_feedback_keeps_setup_inserts_and_late_failure_with_bounded_data(late_crash):
    from ta_bench.generation.session import FEEDBACK_ROWS, failed_test_feedback

    steps = [deepcopy(test_plan()[1]['steps'][1]) for _ in range(20)]
    steps[0] = {'op': 'open', 'session': 's1'}
    steps[1]['params'][0] = {'type': 'memref_input', 'data': 'ab' * 1000}
    steps[18]['params'][0]['inserts'] = [
        {'offset': 0, 'from': {'step': 3, 'param': 0, 'offset': 0, 'length': 4}}]
    steps[-1] = {'op': 'close', 'session': 's1'}
    rows = [{'result': 0, 'origin': 4, 'ta_crashed': False, 'params': []} for _ in steps]
    rows[1]['result'] = 0xffff0006
    rows[18]['result'] = 0xffff0006
    if late_crash:
        rows[17].update(result=0xffff3024, ta_crashed=True)
    test = {'id': 'T02', 'purpose': 'witness', 'steps': steps, 'witness_step': 19,
            'different_steps': [], 'observed': {'normal': rows, 'defective': deepcopy(rows)}}
    reason = 'normal TA crashed' if late_crash else 'no reproducible difference at/after witness step'
    semantic = {'machine_validation': {'reason': f'T02: {reason} (R2)'}, 'tests': [test]}
    before = deepcopy(semantic)
    feedback = failed_test_feedback(semantic, [test])
    assert feedback['source'] == 'candidate'
    assert len(feedback['steps']) == 20 and feedback['steps'][18] == steps[18]
    data = feedback['steps'][1]['params'][0]
    assert data['data'] == 'ab' * 32 and data['data_bytes'] == 1000 and data['data_truncated'] is True
    assert len(feedback['observations']) == FEEDBACK_ROWS
    assert feedback['observations_omitted'] == 20 - FEEDBACK_ROWS
    observed = {row['step']: row for row in feedback['observations']}
    for step in (2, 19):
        assert observed[step]['normal']['result'] == observed[step]['defective']['result'] == 0xffff0006
        assert observed[step]['different_items'] == []
    if late_crash:
        assert observed[18]['normal']['ta_crashed'] is True
    assert semantic == before
