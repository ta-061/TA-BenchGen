"""Strict data-only invocation plans. All indexes shown to humans are 1-based."""
import copy
import re
import uuid

from ..errors import ValidationError
from ..runtime.events import SHARED_TYPES, validate_events

TYPES = {'none', 'value_input', 'value_output', 'value_inout',
         'memref_input', 'memref_output', 'memref_inout'} | SHARED_TYPES


def uint(value, name, maximum=0xffffffff):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValidationError(f'{name}: expected integer 0..{maximum}')


# What inserts may copy into and out of. A value parameter counts as eight bytes: a then b, little-endian.
INSERT_TARGETS = {'memref_input', 'memref_inout', 'shared_memref_input', 'shared_memref_inout',
                  'value_input', 'value_inout'}
INSERT_SOURCES = {'memref_output', 'memref_inout', 'shared_memref_output', 'shared_memref_inout',
                  'value_output', 'value_inout'}
VALUE_BYTES = 8
MAX_INSERTS = 8          # per parameter
MAX_KEPT_OUTPUTS = 64    # distinct (step, param) outputs referenced in one sequence


def buffer_size(param):
    if param['type'].startswith('value_'):
        return VALUE_BYTES
    return param.get('size', len(param.get('data', '')) // 2)


def validate_inserts(inserts, size, earlier, where):
    """Copy bytes of an earlier invoke's output into this input (data only)."""
    if not isinstance(inserts, list) or not 1 <= len(inserts) <= MAX_INSERTS:
        raise ValidationError(f'{where}: inserts must contain 1..{MAX_INSERTS} entries')
    for item in inserts:
        source = item.get('from') if isinstance(item, dict) else None
        if (set(item or ()) != {'offset', 'from'} or not isinstance(source, dict)
                or set(source) != {'step', 'param', 'offset', 'length'}):
            raise ValidationError(f'{where}: insert needs offset and from{{step,param,offset,length}}')
        for name in ('step', 'param', 'offset', 'length'):
            uint(source[name], f'{where}: insert from.{name}', 1024 * 1024)
        uint(item['offset'], f'{where}: insert offset', 1024 * 1024)
        if not 1 <= source['step'] <= len(earlier) or earlier[source['step'] - 1].get('op') != 'invoke':
            raise ValidationError(f'{where}: insert must refer to an earlier invoke step (counted from 1)')
        if source['param'] > 3:
            raise ValidationError(f'{where}: insert from.param must be 0..3')
        origin = earlier[source['step'] - 1]['params'][source['param']]
        if origin['type'] not in INSERT_SOURCES:
            raise ValidationError(f'{where}: insert source must be an output or inout parameter')
        if source['length'] < 1 or source['offset'] + source['length'] > buffer_size(origin):
            raise ValidationError(f'{where}: insert source range exceeds the source capacity')
        if item['offset'] + source['length'] > size:
            raise ValidationError(f'{where}: insert exceeds this parameter size')


def kept_outputs(steps):
    """Sorted (step, param) pairs, 1-based step, whose output buffers later steps read."""
    return sorted({(i['from']['step'], i['from']['param']) for s in steps
                   for p in s.get('params', []) for i in p.get('inserts', [])})


def validate_steps(steps):
    if not isinstance(steps, list) or not 1 <= len(steps) <= 256:
        raise ValidationError('steps must contain 1..256 operations')
    sessions = set()
    seen_sessions = set()
    for step_number, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            raise ValidationError('step must be an object')
        op = step.get('op')
        name = step.get('session')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}', name):
            raise ValidationError('invalid session name')
        if op == 'open':
            seen_sessions.add(name)
            if len(seen_sessions) > 32:
                raise ValidationError('at most 32 distinct session names allowed')
            if 'uuid' in step:
                if not isinstance(step['uuid'], str):
                    raise ValidationError('invalid open UUID')
                try:
                    uuid.UUID(step['uuid'])
                except ValueError as exc:
                    raise ValidationError('invalid open UUID') from exc
            if name in sessions or len(sessions) >= 16 or set(step) - {'op', 'session', 'uuid'}:
                raise ValidationError('invalid open operation')
            sessions.add(name)
        elif op == 'close':
            if name not in sessions or set(step) - {'op', 'session'}:
                raise ValidationError('invalid close operation')
            sessions.remove(name)
        elif op == 'invoke':
            if name not in sessions or set(step) - {'op', 'session', 'command_id', 'params', 'events'}:
                raise ValidationError('invalid invoke operation')
            uint(step.get('command_id'), 'command_id')
            params = step.get('params')
            if not isinstance(params, list) or len(params) != 4:
                raise ValidationError('invoke requires exactly four params')
            for param_index, p in enumerate(params):
                if not isinstance(p, dict) or not isinstance(p.get('type'), str) or p['type'] not in TYPES:
                    raise ValidationError('invalid parameter type')
                kind = p['type']
                allowed = {'type'}
                if kind.startswith('value_'):
                    allowed |= {'a', 'b'}
                    uint(p.get('a', 0), 'a')
                    uint(p.get('b', 0), 'b')
                elif kind.startswith('memref_') or kind in SHARED_TYPES:
                    allowed |= {'size', 'data'}
                    data = p.get('data', '')
                    if isinstance(data, str) and ' ' in data:
                        # Spaces only group the bytes for the writer; the stored plan has none.
                        data = p['data'] = data.replace(' ', '')
                    if not isinstance(data, str) or not re.fullmatch(r'(?:[0-9a-fA-F]{2})*', data):
                        raise ValidationError('buffer data must be even-length hex')
                    size = p.get('size', len(data) // 2)
                    uint(size, 'buffer size', 1024 * 1024)
                    if len(data) // 2 > size:
                        raise ValidationError(
                            f'step {step_number}, params[{param_index}]: buffer data exceeds size '
                            f'({len(data) // 2} bytes > {size} bytes)')
                    if kind in {'memref_output', 'shared_memref_output'} and data:
                        raise ValidationError('output buffer cannot contain input data')
                if 'inserts' in p:
                    if kind not in INSERT_TARGETS:
                        raise ValidationError('inserts require an input or inout parameter')
                    allowed |= {'inserts'}
                    validate_inserts(p['inserts'], buffer_size(p), steps[:step_number - 1],
                                     f'step {step_number}, params[{param_index}]')
                if set(p) - allowed:
                    raise ValidationError('unknown parameter fields')
            validate_events(step)
        else:
            raise ValidationError(f'unsupported operation: {op}')
    if len(kept_outputs(steps)) > MAX_KEPT_OUTPUTS:
        raise ValidationError(f'at most {MAX_KEPT_OUTPUTS} distinct outputs may be referenced by inserts')
    return copy.deepcopy(steps)


def validate_plan(tests, defects):
    if not isinstance(tests, list) or not 2 <= len(tests) <= 256:
        raise ValidationError('a plan needs normal and witness tests (maximum 256)')
    if not isinstance(defects, list) or not defects:
        raise ValidationError('defects must be a nonempty list')
    known = set()
    for d in defects:
        if (not isinstance(d, dict) or not isinstance(d.get('id'), str)
                or not re.fullmatch(r'D[1-9][0-9]*', d['id']) or d['id'] in known):
            raise ValidationError('defect IDs must be unique D1, D2, ...')
        refs = d.get('witness_test_ids')
        if not isinstance(refs, list) or not refs or any(not isinstance(t, str) for t in refs):
            raise ValidationError('witness_test_ids must be a nonempty list of IDs')
        known.add(d['id'])
    ids = set()
    normal, covered = 0, set()
    for test in tests:
        if not isinstance(test, dict) or set(test) - {'id', 'purpose', 'targets', 'steps', 'witness_step'}:
            raise ValidationError('invalid test fields (observations must come from the runner)')
        tid = test.get('id')
        if not isinstance(tid, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', tid) or tid in ids:
            raise ValidationError('test IDs must be unique identifiers')
        ids.add(tid)
        targets = test.get('targets')
        if not isinstance(targets, list) or any(not isinstance(t, str) for t in targets):
            raise ValidationError('test targets must be IDs')
        if len(set(targets)) != len(targets) or set(targets) - known:
            raise ValidationError('invalid test targets')
        try:
            validate_steps(test.get('steps'))
        except ValidationError as exc:
            raise ValidationError(f'{tid}: {exc}') from exc
        if not any(s['op'] == 'invoke' for s in test['steps']):
            raise ValidationError('each test must invoke a TA command')
        if test.get('purpose') == 'normal':
            normal += 1
            if targets or 'witness_step' in test:
                raise ValidationError('normal tests cannot target a defect')
        elif test.get('purpose') == 'witness':
            if not targets:
                raise ValidationError('witness test must target a defect')
            uint(test.get('witness_step'), 'witness_step', len(test['steps']))
            if test['witness_step'] == 0 or test['steps'][test['witness_step'] - 1]['op'] != 'invoke':
                raise ValidationError('witness_step must point to an invoke, counted from 1')
            covered.update(targets)
        else:
            raise ValidationError('purpose must be normal or witness')
    if not normal or covered != known:
        raise ValidationError('normal test and witnesses for every defect required')
    for defect in defects:
        actual = {t['id'] for t in tests if defect['id'] in t['targets']}
        if set(defect.get('witness_test_ids', [])) != actual:
            raise ValidationError('witness_test_ids must exactly match test targets')
    return copy.deepcopy(tests)
