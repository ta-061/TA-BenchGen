"""Generation requests, from the command line or a request YAML."""
import yaml

from ..errors import ValidationError

REQUEST_FIELDS = {'ta', 'defects', 'count', 'max_attempts'}
ATTEMPTS_PER_CASE = 3  # default max_attempts = count x 3
# A request holding one of these keys ends: no code fits the class, no further distinct
# defect is left after saved cases, or the provider filtered or refused the request.
STOPPED = {'unsupported', 'exhausted', 'provider_declined'}


def _positive_int(value) -> bool:
    return type(value) is int and value >= 1


def load_request_file(path) -> list:
    data = yaml.safe_load(path.read_text())
    requests = data.get('requests') if isinstance(data, dict) else None
    if not isinstance(requests, list) or not requests:
        raise ValidationError('request YAML requires nonempty requests list')
    return requests


def normalize_requests(requests: list, classes: dict, default_max_attempts=None) -> list[dict]:
    """Validate each request and fill in count and max_attempts."""
    result = []
    for req in requests:
        if not isinstance(req, dict) or set(req) - REQUEST_FIELDS:
            raise ValidationError('invalid request fields')
        if not isinstance(req.get('ta'), str) or not isinstance(req.get('defects'), dict) or not req['defects']:
            raise ValidationError('request needs ta path and defects mapping')
        for name, count in req['defects'].items():
            if name not in classes or not _positive_int(count):
                raise ValidationError(f'unknown class or invalid count: {name}')
        count = req.get('count', 1)
        fallback = default_max_attempts or (count * ATTEMPTS_PER_CASE if type(count) is int else 0)
        limit = req.get('max_attempts', fallback)
        if not _positive_int(count) or not _positive_int(limit):
            raise ValidationError('count and max_attempts must be positive integers')
        result.append({**req, 'count': count, 'max_attempts': limit})
    return result


def is_pending(req: dict, classes: dict) -> bool:
    """True while a request can still start another attempt."""
    return (all(classes[name]['supported'] for name in req['defects'])
            and len(req.get('saved', [])) < req['count']
            and len(req.get('attempts', [])) < req['max_attempts']
            and not STOPPED & set(req))
