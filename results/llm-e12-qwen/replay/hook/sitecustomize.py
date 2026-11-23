"""Bind unchanged IISA messages to the selected local model and record requests."""
import json
import os
from pathlib import Path
import time
import uuid


def install():
    filename = os.environ.get('IISA_LOCAL_PROFILE')
    if not filename:
        return
    import httpx
    from openai.resources.chat.completions import Completions
    from openai.types.chat import ChatCompletion
    from local_replay import ResponseReplay, request_key
    from rerun_support import append_jsonl, exclusive_lock, phase
    profile = json.loads(Path(filename).read_text())
    base = profile['base_url'].rstrip('/')
    target = httpx.URL(base)
    private = Path(os.environ['IISA_LOCAL_PRIVATE'])
    replay_sources = json.loads(os.environ.get('IISA_LOCAL_REPLAY_SOURCES', '[]'))
    replay = ResponseReplay(replay_sources, profile['max_output_tokens'])
    original_create, original_send = Completions.create, httpx.Client.send

    def send(self, request, *args, **kwargs):
        if request.url.host != target.host or request.url.port != target.port:
            raise RuntimeError('IISA local run rejected a request to a different endpoint')
        return original_send(self, request, *args, **kwargs)

    def create(self, *args, **kwargs):
        if args or kwargs.get('model') != profile['model'] or kwargs.get('stream'):
            raise RuntimeError('Unexpected model, positional arguments, or streaming mode')
        if str(self._client.base_url).rstrip('/') != base:
            raise RuntimeError('The client base URL differs from the pinned local endpoint')
        self._client.max_retries = profile['sdk_max_retries']
        values = dict(kwargs)
        supplied = {k: values.get(k) for k in ['model', 'temperature', 'max_tokens', 'response_format']}
        settings = profile['sampling']
        values.update(temperature=settings['temperature'], top_p=settings['top_p'],
                      presence_penalty=settings['presence_penalty'], timeout=profile['request_timeout_seconds'])
        extra = dict(values.get('extra_body') or {})
        extra.update(top_k=settings['top_k'], min_p=settings['min_p'], repetition_penalty=settings['repetition_penalty'],
                     chat_template_kwargs={'enable_thinking': False})
        values['extra_body'] = extra
        event = dict(call_id=str(uuid.uuid4()), started_unix=time.time(), model_requested=profile['model'],
                     base_url=base, messages=values['messages'], process_id=os.getpid(),
                     original_call_parameters=supplied, effective_sampling=settings,
                     transport_extra_body=extra, reasoning_effort='disabled', status='started')
        event['phase'] = phase(event)
        event['request_key'] = request_key(event)
        logical_id = event['call_id']
        event['logical_call_id'] = logical_id
        started = time.monotonic()
        with exclusive_lock(private.parent / 'local-request.lock'):
            delivered = False
            try:
                saved = replay.take(event)
                if saved:
                    previous, provenance = saved
                    event.update(status='succeeded', response_source='replayed', replay_provenance=provenance,
                                 model_reported=previous['model_reported'], choices=previous['choices'],
                                 response_id=previous.get('response_id'), usage={}, replayed_usage=previous.get('usage'),
                                 prompt_tokens_preflight=previous['prompt_tokens_preflight'],
                                 max_tokens=previous['max_tokens'], tokenization_source='recorded_exact_request',
                                 elapsed_seconds=round(time.monotonic()-started, 6))
                    result = ChatCompletion.model_validate(dict(id=previous.get('response_id') or logical_id,
                        object='chat.completion', created=int(previous['started_unix']), model=previous['model_reported'],
                        choices=[dict(index=i, finish_reason=c['finish_reason'],
                                      message=dict(role='assistant', content=c['content']))
                                 for i,c in enumerate(previous['choices'])], usage=previous.get('usage')))
                    append_jsonl(private / 'api_calls.jsonl', event)
                    delivered = True
                    return result
                # Count the exact rendered messages without dropping source or history.
                response = self._client._client.post(base.removesuffix('/v1') + '/tokenize',
                    json={'model': profile['model'], 'messages': values['messages'],
                          'chat_template_kwargs': {'enable_thinking': False}}, timeout=20)
                response.raise_for_status()
                tokens = response.json()['count']
                available = profile['max_model_len'] - tokens - 64
                if available < profile['minimum_output_tokens']:
                    raise RuntimeError('Context budget exhausted; source and conversation were not truncated')
                limits = [profile['max_output_tokens']]
                expanded = profile.get('truncation_retry_output_tokens', limits[0])
                if min(expanded, available) > min(limits[0], available):
                    limits.append(expanded)
                for number, limit in enumerate(limits):
                    attempt = dict(event, call_id=str(uuid.uuid4()), logical_call_id=logical_id,
                                   attempt_number=number+1, started_unix=time.time(), response_source='live',
                                   prompt_tokens_preflight=tokens, max_tokens=min(limit, available))
                    values['max_tokens'] = attempt['max_tokens']
                    append_jsonl(private / 'requests.jsonl', attempt)
                    attempt_started = time.monotonic()
                    try:
                        result = original_create(self, **values)
                        attempt.update(status='succeeded', model_reported=result.model, response_id=result.id,
                                       choices=[dict(finish_reason=c.finish_reason, content=c.message.content) for c in result.choices],
                                       usage=result.usage.model_dump() if result.usage else {})
                        if result.model != profile['model']:
                            raise RuntimeError('The server reported a different model')
                        if any(c.finish_reason == 'length' or not c.message.content for c in result.choices):
                            raise RuntimeError('Truncated or empty model response; not accepted as a completed call')
                        delivered = True
                        return result
                    except Exception as exc:
                        attempt.update(status='failed', error_type=type(exc).__name__, error=str(exc),
                                       http_status=getattr(exc, 'status_code', None))
                        truncated = any(c.get('finish_reason') == 'length' for c in attempt.get('choices', []))
                        if not truncated or number == len(limits)-1:
                            raise
                    finally:
                        attempt['elapsed_seconds'] = round(time.monotonic()-attempt_started, 6)
                        append_jsonl(private / 'api_calls.jsonl', attempt)
            except Exception as exc:
                # Tokenization/budget failures occur before a live API attempt.
                if not locals().get('attempt'):
                    event.update(status='failed', response_source='preflight', error_type=type(exc).__name__,
                                 error=str(exc), elapsed_seconds=round(time.monotonic()-started, 6))
                    append_jsonl(private / 'api_calls.jsonl', event)
                raise
            finally:
                append_jsonl(private / 'logical_calls.jsonl', dict(logical_call_id=logical_id,
                    request_key=event['request_key'], delivered=delivered,
                    response_source='replayed' if delivered and saved else 'live',
                    elapsed_seconds=round(time.monotonic()-started, 6)))

    httpx.Client.send = send
    Completions.create = create


try:
    install()
except Exception as exc:
    if os.environ.get('IISA_LOCAL_PROFILE'):
        import sys
        sys.stderr.write('Local transport initialization failed: ' + type(exc).__name__ + '\n')
        os._exit(78)
    raise
