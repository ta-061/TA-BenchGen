"""Candidate generation through an OpenAI-compatible Chat Completions API."""
import requests

from ..common.jsonio import atomic_json
from ..errors import ExecutionError, GenerationAPIError
from .api_errors import http_error, parse_candidate
from .profiles import ModelProfile, build_profile
from .prompt import messages


class APIProvider:
    """One HTTP request per attempt. The API proposes; it never measures or judges."""

    def __init__(self, model=None, endpoint=None, profile: ModelProfile | None = None):
        self.profile = profile or build_profile('command-line', model, endpoint)
        self.model_id = self.profile.model
        self.endpoint = self.profile.api_url
        self.anthropic = self.profile.anthropic
        self.key = self.profile.api_key()

    def _payload(self, normal, requested, classes, feedback, existing=()) -> dict:
        profile = self.profile
        payload = {'model': profile.model, 'messages': messages(normal, requested, classes, feedback, existing)}
        if profile.max_tokens is not None:
            payload['max_tokens'] = profile.max_tokens
        if profile.temperature is not None:
            payload['temperature'] = profile.temperature
        if profile.json_mode:
            payload['response_format'] = {'type': 'json_object'}
        return payload

    def _headers(self) -> dict:
        headers = {'Authorization': f'Bearer {self.key}'} if self.key else {}
        for header, variable in self.profile.headers_env.items():
            value = self.profile.secret(variable)
            if value:
                headers[header] = value
        return headers

    def propose(self, normal, requested, classes, feedback, directory, existing=()):
        payload = self._payload(normal, requested, classes, feedback, existing)
        atomic_json(directory / 'api-request.json', payload)  # never headers or keys
        try:
            response = requests.post(self.endpoint, headers=self._headers(), json=payload,
                                     timeout=(self.profile.connect_timeout, self.profile.read_timeout))
            if response.status_code != 200:
                raise http_error(response, self.anthropic)
            try:
                result = response.json()
            except ValueError as exc:
                raise GenerationAPIError('generation API returned a non-JSON HTTP response; '
                                         'check the API endpoint') from exc
            atomic_json(directory / 'api-response.json', result)
            return parse_candidate(result)
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ExecutionError(f'generation API returned invalid response ({type(exc).__name__})') from exc
