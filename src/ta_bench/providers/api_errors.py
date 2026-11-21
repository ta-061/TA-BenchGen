"""Turn API failures into fixed, safe advice, and completions into candidates."""
import json

import requests

from ..errors import GenerationAPIError

# Only fixed diagnostic advice may reach logs or later model feedback.
STATUS_HINTS = {400: 'check the model ID and API request options',
                401: 'authentication failed; check that the API key belongs to TA_BENCH_API_URL',
                403: 'access denied; check the API key permissions and workspace',
                404: 'check the complete Chat Completions URL and model ID',
                422: 'check the API request options'}
RETRYABLE_STATUSES = {408, 409, 429}


def http_error(response, anthropic) -> GenerationAPIError:
    message = f'generation API HTTP {response.status_code}'
    hint = error_hint(response, anthropic) or STATUS_HINTS.get(response.status_code)
    if hint:
        message += ': ' + hint
    retryable = response.status_code in RETRYABLE_STATUSES or response.status_code >= 500
    return GenerationAPIError(message, retryable=retryable)


def error_hint(response, anthropic):
    """Map recognized JSON errors to fixed advice; never echo provider text."""
    try:
        body = response.json()
    except (ValueError, requests.RequestException):
        return None
    error = body.get('error') if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return None
    detail = error.get('message')
    if not isinstance(detail, str):
        return None
    detail = detail.lower()
    if anthropic and ('anthropic-workspace-id' in detail or (
            'workspace' in detail and any(term in detail for term in (
                'not scoped', 'required', 'not found', 'does not exist', 'access')))):
        return ('check ANTHROPIC_WORKSPACE_ID: set the workspace ID from Claude Console; '
                'keys not scoped to a workspace require it, and the key must have access to that workspace')
    if any(term in detail for term in ('credit balance', 'insufficient credit', 'billing',
                                      'spend limit', 'usage limit', 'insufficient_quota')):
        return 'check API credits, billing and organization/workspace spending limits in the provider console'
    if 'response_format' in detail:
        return 'the API rejected response_format; check JSON output support for the selected model and endpoint'
    if 'max_tokens' in detail or 'max_completion_tokens' in detail:
        return 'the API rejected the output token limit; check the token limits for the selected model'
    if 'model' in detail and any(term in detail for term in (
            'not found', 'does not exist', 'invalid', 'not available', 'not supported',
            'access', 'unknown', 'deprecated', 'retired')):
        return 'check the model ID and model access for this API key in the provider console'
    return None


def parse_candidate(result):
    """Check completion status before interpreting model text as a candidate."""
    choices = result.get('choices') if isinstance(result, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise GenerationAPIError('generation API returned invalid Chat Completions response: missing choices')
    choice = choices[0]
    if choice.get('finish_reason') == 'content_filter':
        raise GenerationAPIError('generation API stopped by provider content filter '
                                 '(finish_reason=content_filter); this request is not retried',
                                 declined=True)
    if choice.get('finish_reason') == 'length':
        raise GenerationAPIError('generation API output was truncated (finish_reason=length); '
                                 'check output token limits before retrying')
    message = choice.get('message')
    if not isinstance(message, dict):
        raise GenerationAPIError('generation API returned invalid Chat Completions response: missing message')
    if message.get('refusal'):
        raise GenerationAPIError('generation API returned a provider refusal; this request is not retried',
                                 declined=True)
    content = message.get('content')
    if not isinstance(content, str) or not content.strip():
        raise GenerationAPIError('generation API returned no candidate text; check the saved API response')
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise GenerationAPIError('generation API returned invalid candidate JSON '
                                 f'(line {exc.lineno}, column {exc.colno}); '
                                 'return one complete JSON object without Markdown fences', retryable=True) from exc
