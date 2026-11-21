"""Registered models (config/models.yaml) and the choice of which one a run uses.

A profile names an OpenAI-compatible Chat Completions endpoint. Secrets are never
written in the profile: it names the environment variable that holds the key.
"""
from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from ..errors import GenerationAPIError

DEFAULT_API_URL = 'https://api.openai.com/v1/chat/completions'
OPENAI_HOST = 'api.openai.com'
ANTHROPIC_HOST = 'api.anthropic.com'
LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1'}
ANTHROPIC_MAX_TOKENS = 16384
CONNECT_TIMEOUT, READ_TIMEOUT = 15, 180
KEY_FILE_NAME = 'api_keys.local.yaml'  # git-ignored; sits next to models.yaml
PROFILE_FIELDS = {'api_url', 'model', 'api_key_env', 'json_mode', 'max_tokens', 'temperature',
                  'headers_env', 'connect_timeout', 'read_timeout'}


@dataclass(frozen=True)
class ModelProfile:
    name: str
    api_url: str
    model: str
    api_key_envs: tuple[str, ...]          # tried in order; empty means no key (local LLM)
    json_mode: bool                        # send response_format: json_object
    max_tokens: int | None = None
    temperature: float | None = None
    headers_env: dict[str, str] = field(default_factory=dict)   # header name -> environment variable
    connect_timeout: float = CONNECT_TIMEOUT
    read_timeout: float = READ_TIMEOUT
    key_file: Path | None = None

    def to_settings(self) -> dict:
        """Persist resolved options and secret references, never secret values."""
        settings = asdict(self)
        settings['api_key_envs'] = list(self.api_key_envs)
        settings['key_file'] = str(self.key_file.resolve()) if self.key_file else None
        return settings

    @classmethod
    def from_settings(cls, settings: dict) -> ModelProfile:
        """Resume without rereading the model registry or model-selection environment."""
        try:
            values = dict(settings)
            if not isinstance(values['api_key_envs'], list):
                raise TypeError()
            values['api_key_envs'] = tuple(values['api_key_envs'])
            if values['key_file'] is not None:
                values['key_file'] = Path(values['key_file'])
            profile = cls(**values)
        except (KeyError, TypeError, ValueError) as exc:
            raise GenerationAPIError('invalid saved model profile') from exc
        return _validate_profile(profile)

    @property
    def host(self) -> str:
        return urlsplit(self.api_url).hostname or ''

    @property
    def anthropic(self) -> bool:
        return self.host == ANTHROPIC_HOST

    def secret(self, name: str) -> str | None:
        """Environment first, then the local key file. Values are never persisted."""
        value = os.environ.get(name)
        if value:
            return value
        if self.key_file and self.key_file.is_file():
            try:
                keys = yaml.safe_load(self.key_file.read_text()) or {}
            except (OSError, UnicodeError, yaml.YAMLError) as exc:
                # YAML's default diagnostic can contain the line holding a secret.
                raise GenerationAPIError(f'cannot read {self.key_file.name}; check its YAML format') from exc
            if not isinstance(keys, dict):
                raise GenerationAPIError(f'{self.key_file.name} must map variable names to keys')
            value = keys.get(name)
            return value if isinstance(value, str) and value else None
        return None

    def api_key(self) -> str | None:
        return next((key for key in map(self.secret, self.api_key_envs) if key), None)


def _check_url(api_url: str) -> str:
    try:
        if not isinstance(api_url, str) or any(c.isspace() for c in api_url):
            raise ValueError()
        address = urlsplit(api_url)
        host = address.hostname
        local = address.scheme == 'http' and host in LOCAL_HOSTS
        if (not host or not (address.scheme == 'https' or local)
                or address.username is not None or address.password is not None):
            raise ValueError()
        _ = address.port  # Validate malformed/out-of-range port numbers before sending.
    except (ValueError, AttributeError) as exc:
        raise GenerationAPIError('API endpoint must be a valid HTTPS URL '
                                 '(plain HTTP is accepted only for localhost)') from exc
    return host


def _validate_profile(profile: ModelProfile) -> ModelProfile:
    """Reject invalid settings locally instead of failing inside the HTTP client."""
    host = _check_url(profile.api_url)
    if not isinstance(profile.model, str):
        raise GenerationAPIError('model profile: model must be a string')
    if (any(not isinstance(name, str) or not name.strip() for name in profile.api_key_envs)
            or not isinstance(profile.headers_env, dict)
            or any(not isinstance(k, str) or not k.strip() or not isinstance(v, str) or not v.strip()
                   for k, v in profile.headers_env.items())):
        raise GenerationAPIError('model profile: api_key_env and headers_env must name environment variables')
    if type(profile.json_mode) is not bool:
        raise GenerationAPIError('model profile: json_mode must be a boolean')
    if (profile.max_tokens is not None
            and (type(profile.max_tokens) is not int or profile.max_tokens < 1)):
        raise GenerationAPIError('model profile: max_tokens must be a positive integer or null')
    for name in ('temperature', 'connect_timeout', 'read_timeout'):
        value = getattr(profile, name)
        if value is None and name == 'temperature':
            continue
        if (type(value) not in (int, float) or not math.isfinite(value)
                or (value < 0 if name == 'temperature' else value <= 0)):
            raise GenerationAPIError(f'model profile: {name} must be a finite '
                                     + ('nonnegative number or null' if name == 'temperature' else 'positive number'))
    if not profile.model.strip() or (profile.api_key_envs and not profile.api_key()):
        key_name = ' (or '.join(profile.api_key_envs) + (')' if len(profile.api_key_envs) > 1 else '')
        needs = ' and '.join(filter(None, ['TA_BENCH_MODEL / --model', key_name]))
        raise GenerationAPIError(f'set {needs}, or use --candidate')
    if profile.model.startswith('claude-') and host == OPENAI_HOST:
        raise GenerationAPIError('Claude model is configured for the OpenAI API; set TA_BENCH_API_URL '
                                 'to https://api.anthropic.com/v1/chat/completions or your compatible API')
    return profile


def build_profile(name: str, model: str | None, api_url: str | None = None,
                  options: dict | None = None, key_file: Path | None = None) -> ModelProfile:
    """Fill unspecified fields from the endpoint: OpenAI-style by default, Anthropic by host."""
    options = dict(options or {})
    for key in ('model', 'api_url'):
        if key in options and options[key] is not None and not isinstance(options[key], str):
            raise GenerationAPIError(f'model profile: {key} must be a string')
    # Precedence: explicit argument, then the registered entry, then the environment.
    model = model or options.get('model') or os.environ.get('TA_BENCH_MODEL')
    api_url = api_url or options.get('api_url') or os.environ.get('TA_BENCH_API_URL') or DEFAULT_API_URL
    host = _check_url(api_url)
    anthropic = host == ANTHROPIC_HOST
    if 'api_key_env' in options:
        key_env = options['api_key_env']
        key_envs = (key_env,) if key_env is not None else ()
    elif host in LOCAL_HOSTS:
        key_envs = ()
    else:
        key_envs = ('ANTHROPIC_API_KEY', 'OPENAI_API_KEY') if anthropic else ('OPENAI_API_KEY',)
    headers_env = options.get('headers_env')
    if headers_env is None:
        headers_env = {'anthropic-workspace-id': 'ANTHROPIC_WORKSPACE_ID'} if anthropic else {}
    profile = ModelProfile(
        name=name, api_url=api_url, model=model or '',
        api_key_envs=key_envs,
        # Anthropic's compatibility endpoint rejects json_object; the prompt requires JSON instead.
        json_mode=options.get('json_mode', not anthropic),
        max_tokens=options.get('max_tokens', ANTHROPIC_MAX_TOKENS if anthropic else None),
        temperature=options.get('temperature'), headers_env=headers_env,
        connect_timeout=options.get('connect_timeout', CONNECT_TIMEOUT),
        read_timeout=options.get('read_timeout', READ_TIMEOUT), key_file=key_file)
    return _validate_profile(profile)


def select_profile(models_file: Path | None, use: str | None = None,
                   model: str | None = None, api_url: str | None = None) -> ModelProfile:
    """Pick the registered model named by `use` (or the file's own `use:`).

    --model / --api-url override single fields of that entry; TA_BENCH_MODEL and
    TA_BENCH_API_URL only fill fields the entry leaves empty. Without a models
    file the endpoint defaults to OpenAI.
    """
    if models_file is None or not Path(models_file).is_file():
        if use:
            raise GenerationAPIError(f'model profile {use} requested, but no models file was found')
        return build_profile('command-line', model, api_url)
    models_file = Path(models_file)
    data = yaml.safe_load(models_file.read_text())
    models = data.get('models') if isinstance(data, dict) else None
    if not isinstance(models, dict) or not models:
        raise GenerationAPIError(f'{models_file}: requires a nonempty models mapping')
    name = use or data.get('use')
    if not isinstance(name, str) or name not in models:
        raise GenerationAPIError(f'{models_file}: use must name one of: ' + ', '.join(map(str, models)))
    options = models[name]
    if not isinstance(options, dict) or set(options) - PROFILE_FIELDS:
        raise GenerationAPIError(f'{models_file}: model {name} allows only: ' + ', '.join(sorted(PROFILE_FIELDS)))
    return build_profile(name, model, api_url, options, models_file.parent / KEY_FILE_NAME)
