"""Bounded, data-only events, independent of defect classification names."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..candidate.c_source import function_ranges, mask_c
from ..candidate.paths import safe_relative_path
from ..common.jsonio import canonical_hash
from ..common.sources import source_digest
from ..errors import ExecutionError, ValidationError

SHARED_TYPES = {'shared_memref_input', 'shared_memref_output', 'shared_memref_inout'}
FEATURE = 'shared_memory_events_v1'
OUTPUT_REFERENCE = 'output_reference_v1'
FEATURES = {FEATURE, OUTPUT_REFERENCE}
MAX_EVENTS = 16
MAX_EVENT_BYTES = 4096
INSTRUMENTATION = 'statement-checkpoint-v1'


def _require(value, message):
    if not value:
        raise ValidationError(message)


def _uint(value, maximum):
    return type(value) is int and 0 <= value <= maximum


def _hex(value):
    return isinstance(value, str) and bool(re.fullmatch(r'(?:[0-9a-fA-F]{2})+', value))


def validate_checkpoint(trigger):
    _require(isinstance(trigger, dict) and set(trigger) ==
             {'kind', 'path', 'function', 'before', 'occurrence'}, 'invalid checkpoint trigger fields')
    _require(trigger['kind'] == 'checkpoint', 'unsupported event trigger')
    path = safe_relative_path(trigger['path'])
    _require(path.startswith('ta/') and path.endswith('.c'), 'checkpoint must refer to TA C source')
    _require(isinstance(trigger['function'], str) and
             bool(re.fullmatch(r'[A-Za-z_]\w{0,127}', trigger['function'])), 'invalid checkpoint function')
    statement = trigger['before']
    _require(isinstance(statement, str) and 1 <= len(statement) <= 1024 and
             statement == statement.strip() and not any(c in statement for c in '\n\r\\'),
             'checkpoint before must be one complete source line')
    # Wrap one expression statement so an unbraced if/else retains its scope.
    # Declarations, labels, returns, control statements and macros are not anchors.
    code = mask_c(statement).strip()
    _require(statement.endswith(';') and code.endswith(';') and code.count(';') == 1 and
             not any(c in code for c in '{}#'),
             'checkpoint requires a single expression statement')
    identifier = r'[A-Za-z_]\w*'
    lvalue = identifier + r'(?:\s*(?:->|\.)\s*' + identifier + r'|\s*\[[^\[\];{}]+\])*'
    _require(bool(re.match(r'^(?:' + lvalue + r'\s*(?:[+*/%&|^-]?=)(?!=)|' + identifier + r'\s*\()', code)),
             'checkpoint requires an assignment or function call')
    _require(not re.match(r'^(?:if|while|for|switch|return|sizeof|_Alignof|do)\b', code),
             'checkpoint cannot wrap a control statement')
    depth = 0
    for char in code:
        depth += (char == '(') - (char == ')')
        _require(depth >= 0, 'checkpoint must not split a multiline statement')
    _require(depth == 0, 'checkpoint must not split a multiline statement')
    _require(_uint(trigger['occurrence'], 1024) and trigger['occurrence'] >= 1,
             'checkpoint occurrence must be 1..1024')


def validate_write(action, params):
    _require(isinstance(action, dict) and set(action) == {'kind', 'param', 'offset', 'expect', 'data'},
             'invalid write_memory action fields')
    _require(action['kind'] == 'write_memory', 'unsupported event action')
    index = action['param']
    _require(_uint(index, 3) and params[index]['type'] in {'shared_memref_input', 'shared_memref_inout'},
             'write_memory requires a shared input or inout parameter')
    _require(_hex(action['data']) and _hex(action['expect']), 'event bytes must be nonempty hexadecimal')
    size = len(action['data']) // 2
    _require(len(action['expect']) == size * 2 and size <= MAX_EVENT_BYTES,
             'event expect/data must have equal lengths, at most 4096 bytes')
    limit = params[index].get('size', len(params[index].get('data', '')) // 2)
    _require(_uint(action['offset'], limit) and action['offset'] + size <= limit,
             'event write exceeds shared buffer')


TRIGGERS = {'checkpoint': validate_checkpoint}
ACTIONS = {'write_memory': validate_write}


def validate_events(step):
    if 'events' not in step:
        return
    events = step['events']
    _require(isinstance(events, list) and 1 <= len(events) <= MAX_EVENTS, 'events must contain 1..16 entries')
    for event in events:
        _require(isinstance(event, dict) and set(event) == {'trigger', 'action'}, 'invalid event fields')
        trigger, action = event['trigger'], event['action']
        _require(isinstance(trigger, dict) and isinstance(trigger.get('kind'), str) and
                 trigger['kind'] in TRIGGERS, 'unsupported event trigger')
        _require(isinstance(action, dict) and isinstance(action.get('kind'), str) and
                 action['kind'] in ACTIONS, 'unsupported event action')
        TRIGGERS[trigger['kind']](trigger)
        ACTIONS[action['kind']](action, step['params'])


def checkpoint_spec(trigger):
    return {key: trigger[key] for key in ('kind', 'path', 'function', 'before')}


def checkpoint_id(trigger):
    return int(canonical_hash(checkpoint_spec(trigger)).split(':')[1][:8], 16)


def required_features(steps):
    features = set()
    for step in steps:
        params = step.get('params', [])
        if step.get('events') or any(p['type'] in SHARED_TYPES for p in params):
            features.add(FEATURE)
        if any(p.get('inserts') for p in params):
            features.add(OUTPUT_REFERENCE)
    return features


def collect_checkpoints(tests):
    by_id = {}
    for test in tests:
        for step in test['steps']:
            for event in step.get('events', []):
                trigger = event['trigger']
                key, spec = checkpoint_id(trigger), checkpoint_spec(trigger)
                _require(key not in by_id or by_id[key] == spec, 'checkpoint ID collision')
                by_id[key] = spec
    _require(len(by_id) <= 64, 'at most 64 distinct checkpoints per plan')
    return [by_id[key] for key in sorted(by_id)]


def expected_receipts(step):
    return [{'checkpoint': checkpoint_id(e['trigger']), 'occurrence': e['trigger']['occurrence'],
             'param': e['action']['param'], 'offset': e['action']['offset'],
             'before': e['action']['expect'].lower(), 'after': e['action']['data'].lower()}
            for e in step.get('events', [])]


def validate_receipts(step, row):
    expected = expected_receipts(step)
    if expected:
        actual = row.get('events')
        if (actual != expected or not isinstance(actual, list) or
                any(not isinstance(event, dict) or
                    any(type(event.get(k)) is not int for k in ('checkpoint', 'occurrence', 'param', 'offset'))
                    for event in actual)):
            raise ExecutionError('missing, out-of-order or mismatched shared-memory event receipts')
    elif row.get('events'):
        raise ExecutionError('unexpected shared-memory event receipts')


def instrument_source(source: Path, destination: Path, checkpoints):
    """Insert identical RPC barriers into build copies, never distributed sources."""
    original = source_digest(source)
    shutil.copytree(source, destination)
    locations = []
    grouped = {}
    for point in checkpoints:
        validate_checkpoint({**point, 'occurrence': 1})
        grouped.setdefault(point['path'], []).append(point)
    for relative, points in grouped.items():
        path = destination / relative
        _require(path.is_file() and not path.is_symlink(), 'checkpoint source missing')
        text = path.read_text()
        _require('_ta_bench_checkpoint' not in text, 'reserved instrumentation symbol in source')
        lines = text.splitlines(keepends=True)
        masked_lines = mask_c(text).splitlines()
        functions = function_ranges(text)
        changes = {}
        for point in points:
            ranges = functions.get(point['function'], [])
            matches = [n for n, line in enumerate(lines, 1) if line.strip() == point['before'] and
                       any(start < n < end for start, end in ranges)]
            _require(len(matches) == 1, f'checkpoint must match exactly one statement: {relative}:{point["function"]}')
            n = matches[0]
            _require(masked_lines[n - 1].strip() == mask_c(point['before']).strip(),
                     'checkpoint cannot occur inside a comment or literal')
            _require(n not in changes and not lines[n - 2].rstrip().endswith('\\'),
                     'checkpoint overlaps or occurs inside a macro')
            indent = lines[n - 1][:len(lines[n - 1]) - len(lines[n - 1].lstrip())]
            ident = checkpoint_id(point)
            changes[n] = (f'{indent}do {{ _ta_bench_checkpoint({ident}U); '
                          f'{point["before"]} }} while (0);\n')
            locations.append({'checkpoint': ident, 'path': relative, 'function': point['function'], 'line': n})
        for n, line in changes.items():
            lines[n - 1] = line
        path.write_text('#include "/opt/ta-bench/invoke/checkpoint.h"\n' + ''.join(lines))
    return {'method': INSTRUMENTATION, 'source_digest': original, 'checkpoints': checkpoints,
            'locations': locations, 'instrumented_digest': source_digest(destination)}
