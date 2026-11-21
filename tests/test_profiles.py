"""Model registration (config/models.yaml): selection, overrides, keys, local endpoints."""
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from ta_bench.errors import GenerationAPIError
from ta_bench.providers import api
from ta_bench.providers.api import APIProvider
from ta_bench.providers.profiles import select_profile

MODELS = '''
use: hosted
models:
  hosted:
    api_url: https://llm.example/v1/chat/completions
    model: hosted-model
    api_key_env: HOSTED_KEY
    temperature: 0
  local:
    api_url: http://127.0.0.1:11434/v1/chat/completions
    model: local-model
    api_key_env: null
    read_timeout: 600
  blank:
    api_key_env: HOSTED_KEY
'''


@pytest.fixture
def models(tmp_path, monkeypatch):
    for name in ('HOSTED_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'TA_BENCH_MODEL', 'TA_BENCH_API_URL'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('HOSTED_KEY', 'test-hosted-secret')
    path = tmp_path / 'models.yaml'
    path.write_text(MODELS)
    return path


def test_use_in_file_selects_the_default_and_argument_overrides_it(models):
    assert select_profile(models).name == 'hosted'
    local = select_profile(models, use='local')
    assert (local.model, local.api_key(), local.read_timeout) == ('local-model', None, 600)


def test_command_line_overrides_single_fields(models):
    profile = select_profile(models, model='other-model')
    assert (profile.model, profile.api_url) == ('other-model', 'https://llm.example/v1/chat/completions')


def test_environment_only_fills_fields_the_entry_leaves_empty(models, monkeypatch):
    monkeypatch.setenv('TA_BENCH_MODEL', 'env-model')
    assert select_profile(models).model == 'hosted-model'
    blank = select_profile(models, use='blank')
    assert (blank.model, blank.api_url) == ('env-model', 'https://api.openai.com/v1/chat/completions')


def test_key_file_is_used_when_the_environment_has_no_key(models, monkeypatch):
    monkeypatch.delenv('HOSTED_KEY')
    with pytest.raises(GenerationAPIError, match='HOSTED_KEY'):
        select_profile(models)
    (models.parent / 'api_keys.local.yaml').write_text('HOSTED_KEY: test-file-secret\n')
    assert select_profile(models).api_key() == 'test-file-secret'


@pytest.mark.parametrize('text,use,expected', [
    (MODELS, 'missing', 'use must name one of'),
    ('use: a\nmodels: {a: {model: m, surprise: 1}}', None, 'allows only'),
    ('use: a\nmodels: {a: {model: m, api_url: "http://llm.example/v1"}}', None, 'HTTPS'),
    ('models: {}', None, 'nonempty models'),
])
def test_invalid_registrations_are_rejected(tmp_path, text, use, expected):
    path = tmp_path / 'models.yaml'
    path.write_text(text)
    with pytest.raises(GenerationAPIError, match=expected):
        select_profile(path, use=use)


def test_local_model_sends_no_authorization_and_never_records_keys(models, tmp_path, monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=200, json=lambda: {'choices': [{'message': {'content': '{"unsupported": "x"}'}}]})

    monkeypatch.setattr(api.requests, 'post', post)
    normal = tmp_path / 'normal'
    (normal / 'ta').mkdir(parents=True)
    (normal / 'ta' / 'entry.c').write_text('int f(void) { return 0; }\n')
    for use, headers in (('local', {}), ('hosted', {'Authorization': 'Bearer test-hosted-secret'})):
        provider = APIProvider(profile=select_profile(models, use=use))
        assert provider.propose(normal, {'IVW': 1}, {}, None, tmp_path) == {'unsupported': 'x'}
        assert calls[-1][1]['headers'] == headers
    assert calls[0][1]['timeout'] == (15, 600) and 'temperature' not in calls[0][1]['json']
    assert calls[1][1]['json']['temperature'] == 0
    assert 'test-hosted-secret' not in (tmp_path / 'api-request.json').read_text()


def test_shipped_registration_file_is_valid(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-secret')
    path = Path(__file__).resolve().parents[1] / 'config' / 'models.yaml'
    assert select_profile(path, use='claude').anthropic
    assert select_profile(path, use='local', model='m').api_key() is None


@pytest.mark.parametrize('field,value', [
    ('model', 123), ('api_url', 123),
    ('api_url', 'https://llm.example:invalid/v1'),
    ('api_url', 'https://user:secret@llm.example/v1'),
    ('json_mode', 'false'), ('json_mode', None),
    ('max_tokens', True), ('max_tokens', 0), ('max_tokens', 1.5),
    ('temperature', -1), ('temperature', float('nan')), ('temperature', True),
    ('connect_timeout', 0), ('read_timeout', -1), ('read_timeout', float('inf')),
    ('read_timeout', '600'), ('api_key_env', False), ('api_key_env', ''),
    ('headers_env', {'x-workspace': ''}),
])
def test_invalid_profile_values_fail_before_http(models, field, value):
    data = yaml.safe_load(MODELS)
    data['models']['hosted'][field] = value
    models.write_text(yaml.safe_dump(data))
    with pytest.raises(GenerationAPIError) as exc:
        select_profile(models)
    assert exc.value.retryable is False


def test_malformed_key_file_does_not_expose_its_contents(models, monkeypatch):
    monkeypatch.delenv('HOSTED_KEY')
    (models.parent / 'api_keys.local.yaml').write_text('HOSTED_KEY: [test-private-secret\n')
    with pytest.raises(GenerationAPIError, match='YAML format') as exc:
        select_profile(models)
    assert 'test-private-secret' not in str(exc.value)
