"""Reuse complete responses only when their full effective request matches."""
from collections import defaultdict, deque
from hashlib import sha256
import json
from pathlib import Path


def request_key(event):
    fields = {key: event.get(key) for key in
              ['model_requested', 'base_url', 'messages', 'effective_sampling', 'transport_extra_body']}
    fields['response_format'] = (event.get('original_call_parameters') or {}).get('response_format')
    return sha256(json.dumps(fields, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class ResponseReplay:
    def __init__(self, sources, max_output_tokens):
        self.events = defaultdict(deque)
        for source in sources:
            path = Path(source['path'])
            if sha256(path.read_bytes()).hexdigest() != source['sha256']:
                raise RuntimeError('Replay evidence changed after its inventory was pinned')
            for number, line in enumerate(path.read_text().splitlines(), 1):
                event = json.loads(line)
                choices = event.get('choices', [])
                if (event.get('status') != 'succeeded' or not choices or
                        event.get('model_reported') != event.get('model_requested') or
                        any(c.get('finish_reason') != 'stop' or not c.get('content') for c in choices) or
                        event.get('max_tokens', max_output_tokens + 1) > max_output_tokens):
                    continue
                provenance = dict(log=str(path), log_sha256=source['sha256'], line=number,
                                  call_id=event.get('call_id'))
                self.events[request_key(event)].append((event, provenance))

    def take(self, event):
        values = self.events.get(request_key(event))
        return values.popleft() if values else None
