# ruff: noqa: F811 -- imported pytest fixture is injected by parameter name
"""Offline API regressions. All credentials and HTTP responses are test fixtures."""
import json
from types import SimpleNamespace

import pytest
from test_generate import setup_run  # noqa: F401
from test_judge import CLASSES, FakeRunner, defect, test_plan

from ta_bench.common.jsonio import load_json
from ta_bench.errors import GenerationAPIError, ValidationError
from ta_bench.generation.session import run_generation
from ta_bench.providers import api
from ta_bench.providers.api import APIProvider

ANTHROPIC_URL = 'https://api.anthropic.com/v1/chat/completions'


@pytest.fixture(autouse=True)
def isolated_api(monkeypatch):
    for name in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'ANTHROPIC_WORKSPACE_ID', 'TA_BENCH_API_URL'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('OPENAI_API_KEY', 'test-openai-secret')

    def no_network(*args, **kwargs):
        pytest.fail('API tests must never make a real HTTP request')

    monkeypatch.setattr(api.requests, 'post', no_network)


def changed_defect():
    """A defect as written with changes: its edits come from the changes that name it."""
    return {key: value for key, value in defect().items() if key != 'edits'}


def response(status, candidate=None):
    def body():
        if status != 200:
            return {'error': {'message': 'sensitive-error-body'}}
        return {'choices': [{'message': {'content': json.dumps(candidate)}}]}
    return SimpleNamespace(status_code=status, json=body, text='sensitive-error-body')


@pytest.mark.parametrize('endpoint,model', [
    (None, 'test-openai-model'),
    (ANTHROPIC_URL, 'claude-sonnet-5-5'),
    ('https://compatible.example/v1/chat/completions', 'claude-sonnet-5-5'),
])
def test_api_request_format_and_credentials(setup_run, monkeypatch, endpoint, model):
    _benchmark, work, normal, candidate, _request = setup_run
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-anthropic-secret')
    monkeypatch.setenv('ANTHROPIC_WORKSPACE_ID', 'test-workspace')
    calls = []
    expected = load_json(candidate)

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return response(200, expected)

    monkeypatch.setattr(api.requests, 'post', post)
    provider = APIProvider(model, endpoint)
    assert provider.propose(normal, {'IVW': 1}, CLASSES, None, work) == expected
    url, options = calls[0]
    payload, headers = options['json'], options['headers']
    assert options['timeout'] == (15, 180)
    if endpoint == ANTHROPIC_URL:
        assert url == ANTHROPIC_URL
        assert 'response_format' not in payload and payload['max_tokens'] == 16384
        assert headers['Authorization'] == 'Bearer test-anthropic-secret'
        assert headers['anthropic-workspace-id'] == 'test-workspace'
    else:
        assert payload['response_format'] == {'type': 'json_object'}
        assert headers == {'Authorization': 'Bearer test-openai-secret'}
    recorded = (work / 'api-request.json').read_text()
    assert 'test-openai-secret' not in recorded and 'test-anthropic-secret' not in recorded


def test_anthropic_accepts_existing_openai_key_variable():
    assert APIProvider('claude-sonnet-5-5', ANTHROPIC_URL).key == 'test-openai-secret'


def test_wrong_location_roles_are_saved_and_returned_on_retry(setup_run, monkeypatch):
    benchmark, work, _normal, candidate, request = setup_run
    valid = load_json(candidate)
    wrong = json.loads(json.dumps(valid))
    wrong['defects'][0]['detector_targets'][0]['role'] = 'unsafe_use'
    calls = []

    def post(url, **kwargs):
        calls.append(json.loads(kwargs['json']['messages'][1]['content'])['previous_failure'])
        return response(200, wrong if len(calls) == 1 else valid)

    monkeypatch.setattr(api.requests, 'post', post)
    summary = run_generation(request, CLASSES, benchmark, work,
        lambda: APIProvider('test-model'), lambda: FakeRunner(), progress=lambda _: None)
    assert summary['saved'] == 1
    assert calls[1]['status'] == 'machine_fail' and 'one effect' in calls[1]['reason']
    assert calls[1]['proposed'][0]['detector_targets'] == [
        {**valid['defects'][0]['detector_targets'][0], 'role': 'unsafe_use'}]
    assert load_json(work / 'runs' / summary['run_id'] / 'request_1/attempt_1/candidate.json') == wrong


def test_buffer_size_failure_reaches_next_api_attempt_before_any_execution(setup_run, monkeypatch):
    benchmark, work, _normal, candidate, request = setup_run
    valid = load_json(candidate)
    malformed = load_json(candidate)
    malformed['tests'][0]['steps'][1]['params'][0] = {
        'type': 'memref_input', 'size': 65, 'data': '41' * 107}
    runner = FakeRunner()
    calls = []

    def post(url, **kwargs):
        assert not runner.calls
        previous = json.loads(kwargs['json']['messages'][1]['content'])['previous_failure']
        calls.append(previous)
        return response(200, malformed if len(calls) == 1 else valid)

    monkeypatch.setattr(api.requests, 'post', post)
    summary = run_generation(request, CLASSES, benchmark, work,
        lambda: APIProvider('test-model'), lambda: runner, progress=lambda _: None)
    assert summary['saved'] == 1 and summary['unmet'] == 0
    assert calls[0] is None
    assert calls[1] == {'status': 'machine_fail', 'reason':
        f'{valid["tests"][0]["id"]}: step 2, params[0]: buffer data exceeds size (107 bytes > 65 bytes)',
        'proposed': [{key: d[key] for key in ('id', 'class', 'reason', 'detector_targets')} for d in valid['defects']]}
    run = work / 'runs' / summary['run_id']
    assert not (run / 'request_1/attempt_1/source').exists()
    # Bookkeeping stays in the run state and is not sent to the model.
    assert load_json(run / 'request_1/attempt_1/result.json') == {'index': 1, **calls[1]}
    assert runner.calls


@pytest.mark.parametrize('crashed', [False, True])
def test_equal_witness_failure_reaches_next_api_attempt_with_input_and_measurements(
        setup_run, monkeypatch, crashed):
    benchmark, work, _normal, candidate, request = setup_run
    request[0]['max_attempts'] = 2
    calls = []

    class SameFailure(FakeRunner):
        def run(self, artifact, steps, uuid):
            rows = super().run(artifact, steps, uuid)
            if steps[1]['params'][0]['a'] == 8:
                rows[1].update(result=0xffff3024 if crashed else 0xffff0006, ta_crashed=crashed)
            return rows

    def post(url, **kwargs):
        calls.append(json.loads(kwargs['json']['messages'][1]['content'])['previous_failure'])
        return response(200, load_json(candidate))

    monkeypatch.setattr(api.requests, 'post', post)
    summary = run_generation(request, CLASSES, benchmark, work,
        lambda: APIProvider('test-model'), SameFailure, progress=lambda _: None)
    assert summary['saved'] == 0 and summary['unmet'] == 1
    assert len(calls) == 2 and calls[0] is None
    feedback = calls[1]
    assert 'observed_differences' not in feedback
    test = feedback['failed_test']
    assert test['id'] == 'T02' and test['source'] == 'candidate'
    assert test['steps'] == load_json(candidate)['tests'][1]['steps']
    measured = test['observations'][1]
    assert measured['normal'] == measured['defective']
    assert measured['normal']['result'] == (0xffff3024 if crashed else 0xffff0006)
    assert measured['normal']['ta_crashed'] is crashed
    run = work / 'runs' / summary['run_id']
    assert load_json(run / 'request_1/attempt_1/result.json') == {'index': 1, **feedback}
    evidence = load_json(run / 'request_1/attempt_1/failed-semantic.json')
    assert evidence['tests'][1]['different_steps'] == []
    assert 'source' not in evidence['tests'][1]


def test_claude_with_default_openai_endpoint_is_rejected_before_http():
    with pytest.raises(GenerationAPIError, match='TA_BENCH_API_URL') as error:
        APIProvider('claude-sonnet-5-5')
    assert error.value.retryable is False


@pytest.mark.parametrize('status', [400, 401, 403, 404, 422])
def test_permanent_http_error_stops_all_requests_and_preserves_failure(setup_run, monkeypatch, status):
    benchmark, work, _normal, _candidate, request = setup_run
    request[0].update(count=3, max_attempts=15)
    requests = [dict(request[0]), dict(request[0])]
    calls = []

    def post(*args, **kwargs):
        calls.append(args)
        return response(status)

    monkeypatch.setattr(api.requests, 'post', post)
    summary = run_generation(requests, CLASSES, benchmark, work,
        lambda: APIProvider('test-model'), lambda: FakeRunner(), progress=lambda _: None)
    assert len(calls) == 1
    assert summary['requested'] == summary['unmet'] == 6 and summary['saved'] == 0
    first, second = summary['requests']
    assert len(first['attempts']) == 1 and second['attempts'] == []
    attempt = first['attempts'][0]
    assert attempt['status'] == 'execution_error' and attempt['retryable'] is False
    assert f'HTTP {status}' in attempt['reason']
    directory = work / 'runs' / summary['run_id']
    assert load_json(directory / 'request_1/attempt_1/result.json') == attempt
    assert not (benchmark / 'defective').exists()
    for path in directory.rglob('*.json'):
        text = path.read_text()
        assert 'test-openai-secret' not in text and 'sensitive-error-body' not in text


@pytest.mark.parametrize('status,detail,expected', [
    (400, 'This API key is not scoped to a workspace; include the anthropic-workspace-id header.',
     'ANTHROPIC_WORKSPACE_ID'),
    (400, 'anthropic-workspace-id header must be a valid workspace ID.', 'ANTHROPIC_WORKSPACE_ID'),
    (404, 'Workspace wrkspc_private not found.', 'ANTHROPIC_WORKSPACE_ID'),
    (400, 'Your credit balance is too low to access the Anthropic API.', 'API credits'),
    (400, 'Organization spend limit exceeded.', 'spending limits'),
    (400, 'response_format: json_object is not supported.', 'JSON output support'),
    (400, 'max_tokens exceeds the allowed value.', 'output token limit'),
    (404, 'The model is not available for this API key.', 'model ID and model access'),
])
def test_actionable_api_errors_do_not_echo_provider_data(setup_run, monkeypatch, status, detail, expected):
    benchmark, work, _normal, _candidate, request = setup_run
    message = detail + ' test-openai-secret sensitive-error-body'
    monkeypatch.setattr(api.requests, 'post', lambda *a, **k: SimpleNamespace(
        status_code=status, json=lambda: {'error': {'message': message}}))
    summary = run_generation(request, CLASSES, benchmark, work,
        lambda: APIProvider('claude-sonnet-5-5', ANTHROPIC_URL),
        lambda: FakeRunner(), progress=lambda _: None)
    attempts = summary['requests'][0]['attempts']
    assert len(attempts) == 1 and attempts[0]['retryable'] is False
    assert expected in attempts[0]['reason']
    for path in (work / 'runs' / summary['run_id']).rglob('*.json'):
        recorded = path.read_text()
        assert 'test-openai-secret' not in recorded
        assert 'sensitive-error-body' not in recorded
        assert 'wrkspc_private' not in recorded


@pytest.mark.parametrize('body', [None, [], 'proxy error', {'error': 'proxy error'},
                                  {'error': {'message': None}}, {'error': {'message': 'unknown error'}}])
def test_unrecognized_error_body_keeps_http_status(setup_run, monkeypatch, body):
    _benchmark, work, normal, _candidate, _request = setup_run
    monkeypatch.setattr(api.requests, 'post', lambda *a, **k: SimpleNamespace(
        status_code=400, json=lambda: body))
    with pytest.raises(GenerationAPIError, match='HTTP 400: check the model ID') as error:
        APIProvider('test-model').propose(normal, {'IVW': 1}, CLASSES, None, work)
    assert error.value.retryable is False


def test_non_json_error_body_keeps_http_status(setup_run, monkeypatch):
    _benchmark, work, normal, _candidate, _request = setup_run

    def invalid_json():
        raise ValueError('private proxy response')

    monkeypatch.setattr(api.requests, 'post', lambda *a, **k: SimpleNamespace(
        status_code=403, json=invalid_json))
    with pytest.raises(GenerationAPIError, match='HTTP 403: access denied') as error:
        APIProvider('test-model').propose(normal, {'IVW': 1}, CLASSES, None, work)
    assert error.value.retryable is False


@pytest.mark.parametrize('status', [408, 409, 429, 500, 503])
def test_transient_http_error_can_retry_and_save_valid_candidate(setup_run, monkeypatch, status):
    benchmark, work, _normal, candidate, request = setup_run
    responses = iter([response(status), response(200, load_json(candidate))])
    monkeypatch.setattr(api.requests, 'post', lambda *a, **k: next(responses))
    summary = run_generation(request, CLASSES, benchmark, work,
        lambda: APIProvider('test-model'), lambda: FakeRunner(), progress=lambda _: None)
    assert summary['saved'] == 1 and summary['unmet'] == 0
    attempts = summary['requests'][0]['attempts']
    assert len(attempts) == 2 and attempts[0]['retryable'] is True
    assert attempts[1]['status'] == 'machine_pass'


def test_authentication_failure_can_resume_after_key_fix(setup_run, monkeypatch):
    benchmark, work, _normal, candidate, request = setup_run
    responses = iter([response(401), response(200, load_json(candidate))])
    keys = []

    def post(*args, **kwargs):
        keys.append(kwargs['headers']['Authorization'])
        return next(responses)

    monkeypatch.setattr(api.requests, 'post', post)
    args = (CLASSES, benchmark, work, lambda: APIProvider('test-model'), lambda: FakeRunner())
    failed = run_generation(request, *args, progress=lambda _: None)
    monkeypatch.setenv('OPENAI_API_KEY', 'test-corrected-secret')
    resumed = run_generation([], *args, resume=failed['run_id'], progress=lambda _: None)
    assert resumed['saved'] == 1 and resumed['unmet'] == 0
    assert len(resumed['requests'][0]['attempts']) == 2
    assert keys == ['Bearer test-openai-secret', 'Bearer test-corrected-secret']
    historical = work / 'runs' / failed['run_id'] / 'request_1/attempt_1/result.json'
    assert 'HTTP 401' in load_json(historical)['reason']


def test_workspace_failure_can_resume_after_environment_fix(setup_run, monkeypatch):
    benchmark, work, _normal, candidate, request = setup_run
    workspaces = []

    def post(*args, **kwargs):
        workspace = kwargs['headers'].get('anthropic-workspace-id')
        workspaces.append(workspace)
        if not workspace:
            return SimpleNamespace(status_code=400, json=lambda: {
                'error': {'message': 'This request must include the anthropic-workspace-id header.'}})
        return response(200, load_json(candidate))

    monkeypatch.setattr(api.requests, 'post', post)
    args = (CLASSES, benchmark, work,
            lambda: APIProvider('claude-sonnet-5-5', ANTHROPIC_URL), lambda: FakeRunner())
    failed = run_generation(request, *args, progress=lambda _: None)
    assert 'ANTHROPIC_WORKSPACE_ID' in failed['requests'][0]['attempts'][0]['reason']
    monkeypatch.setenv('ANTHROPIC_WORKSPACE_ID', 'test-corrected-workspace')
    resumed = run_generation([], *args, resume=failed['run_id'], progress=lambda _: None)
    assert resumed['saved'] == 1 and resumed['unmet'] == 0
    assert workspaces == [None, 'test-corrected-workspace']


@pytest.mark.parametrize('finish_reason,content,refusal,expected', [
    ('content_filter', '', None, 'finish_reason=content_filter'),
    ('content_filter', '{"files":', None, 'finish_reason=content_filter'),
    ('content_filter', '{"unsupported":"filtered"}', None, 'finish_reason=content_filter'),
    ('length', '{"files":', None, 'finish_reason=length'),
    ('stop', None, 'private refusal text', 'provider refusal'),
    ('stop', '', None, 'no candidate text'),
])
def test_incomplete_completion_stops_without_parsing_or_retrying(
        setup_run, monkeypatch, finish_reason, content, refusal, expected):
    benchmark, work, _normal, _candidate, request = setup_run
    request[0].update(count=3, max_attempts=15)
    requests = [dict(request[0]), dict(request[0])]
    result = {'choices': [{'finish_reason': finish_reason,
                          'message': {'role': 'assistant', 'content': content, 'refusal': refusal}}]}
    calls = []

    def post(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(status_code=200, json=lambda: result)

    class NoBuildRunner(FakeRunner):
        def build(self, source):
            pytest.fail('incomplete output must never reach the TA build')

    monkeypatch.setattr(api.requests, 'post', post)
    summary = run_generation(requests, CLASSES, benchmark, work,
        lambda: APIProvider('claude-sonnet-5-5', ANTHROPIC_URL),
        lambda: NoBuildRunner(), progress=lambda _: None)
    assert summary['saved'] == 0 and summary['unmet'] == 6
    first, second = summary['requests']
    attempt = first['attempts'][0]
    # A filter or refusal ends only its own request; the next request is still tried once.
    declined = finish_reason == 'content_filter' or refusal is not None
    assert len(calls) == (2 if declined else 1)
    assert len(first['attempts']) == 1 and len(second['attempts']) == (1 if declined else 0)
    assert summary['provider_declined'] == (2 if declined else 0)
    assert ('provider_declined' in first) is declined and attempt.get('provider_declined', False) is declined
    assert attempt['status'] == 'execution_error' and attempt['retryable'] is False
    assert expected in attempt['reason'] and 'JSONDecodeError' not in attempt['reason']
    assert 'private refusal text' not in attempt['reason']
    directory = work / 'runs' / summary['run_id'] / 'request_1/attempt_1'
    assert load_json(directory / 'api-response.json') == result
    assert load_json(directory / 'result.json') == attempt
    assert not (directory / 'candidate.json').exists()
    assert not (benchmark / 'defective').exists()


@pytest.mark.parametrize('result', [None, [], {}, {'choices': []}, {'choices': 'invalid'},
                                    {'choices': [None]}, {'choices': [{}]}])
def test_invalid_completion_structure_stops(setup_run, monkeypatch, result):
    _benchmark, work, normal, _candidate, _request = setup_run
    monkeypatch.setattr(api.requests, 'post', lambda *a, **k: SimpleNamespace(
        status_code=200, json=lambda: result))
    with pytest.raises(GenerationAPIError, match='invalid Chat Completions response') as error:
        APIProvider('test-model').propose(normal, {'IVW': 1}, CLASSES, None, work)
    assert error.value.retryable is False


def test_non_json_http_success_stops(setup_run, monkeypatch):
    _benchmark, work, normal, _candidate, _request = setup_run

    def non_json():
        raise api.requests.exceptions.JSONDecodeError('private proxy text', '<html>', 0)

    monkeypatch.setattr(api.requests, 'post', lambda *a, **k: SimpleNamespace(
        status_code=200, json=non_json))
    with pytest.raises(GenerationAPIError, match='non-JSON HTTP response') as error:
        APIProvider('test-model').propose(normal, {'IVW': 1}, CLASSES, None, work)
    assert error.value.retryable is False
    assert 'private proxy text' not in str(error.value)


def test_anthropic_non_json_output_still_fails_validation(setup_run, monkeypatch):
    _benchmark, work, normal, _candidate, _request = setup_run
    monkeypatch.setattr(api.requests, 'post', lambda *a, **k: SimpleNamespace(
        status_code=200, json=lambda: {'choices': [{'message': {'content': 'not JSON'}}]}))
    provider = APIProvider('claude-sonnet-5-5', ANTHROPIC_URL)
    with pytest.raises(GenerationAPIError, match='invalid candidate JSON') as error:
        provider.propose(normal, {'IVW': 1}, CLASSES, None, work)
    assert error.value.retryable is True


def test_malformed_candidate_json_can_retry_with_format_feedback(setup_run, monkeypatch):
    benchmark, work, _normal, candidate, request = setup_run
    results = iter([
        {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"files":'}}]},
        {'choices': [{'finish_reason': 'stop', 'message': {'content': candidate.read_text()}}]},
    ])
    feedback = []

    def post(*args, **kwargs):
        feedback.append(json.loads(kwargs['json']['messages'][1]['content'])['previous_failure'])
        result = next(results)
        return SimpleNamespace(status_code=200, json=lambda: result)

    monkeypatch.setattr(api.requests, 'post', post)
    summary = run_generation(request, CLASSES, benchmark, work,
        lambda: APIProvider('test-model'), lambda: FakeRunner(), progress=lambda _: None)
    assert summary['saved'] == 1
    assert feedback[0] is None
    assert feedback[1] == {'status': 'execution_error', 'reason': feedback[1]['reason']}
    assert 'invalid candidate JSON' in feedback[1]['reason']


def test_feature_prompt_is_sent_only_for_classes_that_require_it(tmp_path):
    from ta_bench.providers.prompt import instructions, messages
    (tmp_path / 'ta').mkdir()
    (tmp_path / 'ta/entry.c').write_text('int f(void) { return 0; }\n')
    classes = {'IVW': {'description': 'bounds', 'supported': True},
               'DUS': {'description': 'shared', 'supported': True, 'required_features': ['shared_memory_events_v1']}}
    plain = messages(tmp_path, {'IVW': 1}, classes, None)[0]['content']
    shared = messages(tmp_path, {'IVW': 1, 'DUS': 1}, classes, None)[0]['content']
    assert 'write_memory' not in plain and 'write_memory' in shared
    assert shared.startswith(plain)
    with pytest.raises(ValidationError, match='no prompt text'):
        instructions({'missing_feature_v9'})


def test_saved_cases_are_shown_and_end_the_request_when_nothing_new_is_left(setup_run, monkeypatch):
    benchmark, work, _normal, _candidate, request = setup_run
    request[0].update(count=3, max_attempts=9)
    change = {'path': 'ta/entry.c', 'defect': 'D1', 'old': '    if (index >= 8)\n        return -1;\n', 'new': ''}
    answers = [{'changes': [change], 'defects': [changed_defect()], 'tests': test_plan()},
               {'exhausted': 'no further distinct defect'}]
    sent = []

    def post(url, **request):
        sent.append(json.loads(request['json']['messages'][1]['content']))
        return response(200, answers[len(sent) - 1])

    monkeypatch.setattr(api.requests, 'post', post)
    summary = run_generation(request, CLASSES, benchmark, work,
        lambda: APIProvider('test-model'), lambda: FakeRunner(), progress=lambda _: None)
    assert sent[0]['existing'] == [] and len(sent) == 2
    assert '-    if (index >= 8)' in sent[1]['existing'][0]
    done = summary['requests'][0]
    assert len(done['saved']) == 1 and done['exhausted'] == 'no further distinct defect'
    assert 'unsupported' not in done and summary['exhausted'] == 1 and summary['unmet'] == 2


def test_unsupported_after_a_saved_case_of_another_class_stays_unsupported(setup_run, monkeypatch):
    benchmark, work, normal, _candidate, request = setup_run
    change = {'path': 'ta/entry.c', 'defect': 'D1', 'old': '    if (index >= 8)\n        return -1;\n', 'new': ''}
    classes = {**CLASSES, 'UDO': {'supported': True, 'description': 'output'}}
    requests = [request[0], {'ta': str(normal), 'defects': {'UDO': 1}, 'count': 1, 'max_attempts': 3},
                {'ta': str(normal), 'defects': {'UDO': 1}, 'count': 1, 'max_attempts': 2}]
    answers = [{'changes': [change], 'defects': [changed_defect()], 'tests': test_plan()},
               {'unsupported': 'the TA has no protected value'},
               {'exhausted': 'nothing left'}, {'exhausted': 'nothing left'}]
    sent = []

    def post(url, **request):
        sent.append(json.loads(request['json']['messages'][1]['content']))
        return response(200, answers[len(sent) - 1])

    monkeypatch.setattr(api.requests, 'post', post)
    summary = run_generation(requests, classes, benchmark, work,
        lambda: APIProvider('test-model'), lambda: FakeRunner(), progress=lambda _: None)
    _, second, third = summary['requests']
    assert second['unsupported'] == 'the TA has no protected value' and 'exhausted' not in second
    assert sent[1]['existing'] and summary['exhausted'] == 1 and 'unsupported' not in third
