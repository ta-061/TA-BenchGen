"""Shape of what a runner must return: one observation per input step."""
from __future__ import annotations

import copy
from typing import Any

from ..errors import ExecutionError
from .events import validate_receipts


def validate_observations(steps: list[dict[str, Any]], rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) != len(steps):
        raise ExecutionError('runner returned an incomplete observation sequence')
    for row, step in zip(rows, steps):
        if (not isinstance(row, dict) or row.get('op') != step['op']
                or type(row.get('result')) is not int or type(row.get('origin')) is not int
                or type(row.get('ta_crashed')) is not bool or not isinstance(row.get('params'), list)):
            raise ExecutionError('runner returned invalid observations')
        validate_receipts(step, row)
    return rows


def variable_items(first: dict, second: dict) -> list[dict[str, Any]]:
    """Items of one step that two runs of the same TA version did not reproduce.

    Only these items are left out of comparisons; everything else in the step is compared.
    A buffer whose contents differ is left out as a whole (its size is still compared):
    single bytes of a random or time-dependent value agree by chance too often to be trusted.
    """
    items = [{'field': key} for key in sorted(set(first) | set(second))
             if key != 'params' and first.get(key) != second.get(key)]
    a, b = first.get('params'), second.get('params')
    if not isinstance(a, list) or not isinstance(b, list) or len(a) != len(b):
        return items + ([{'field': 'params'}] if a != b else [])
    for index, (p, q) in enumerate(zip(a, b)):
        if not isinstance(p, dict) or not isinstance(q, dict):
            if p != q:
                items.append({'param': index, 'field': 'all'})
            continue
        for key in sorted(set(p) | set(q)):
            if p.get(key) == q.get(key):
                continue
            items.append({'param': index, 'field': key})
    return items


def stable_view(row: dict, items: list[dict[str, Any]]) -> dict:
    """The row without the given variable items; the contents of a variable buffer become '**'."""
    view = copy.deepcopy(row)
    for item in items:
        if 'param' not in item:
            view.pop(item['field'], None)
            continue
        params = view.get('params')
        if not isinstance(params, list) or item['param'] >= len(params):
            continue
        if item['field'] == 'all' or not isinstance(params[item['param']], dict):
            params[item['param']] = None
        elif item['field'] == 'data':
            if 'data' in params[item['param']]:
                params[item['param']]['data'] = '**'
        else:
            params[item['param']].pop(item['field'], None)
    return view


def comparison(*pairs):
    """(variable items per step, function mapping observation rows to their compared form).

    Each pair holds two runs of the same TA version on the same input. An item is variable when
    either pair did not reproduce it: a random value can repeat in one version's two runs and
    still differ in the other's, so the normal runs alone do not show everything that varies.
    """
    variable = []
    for steps in zip(*(zip(first, second) for first, second in pairs)):
        items = []
        for first, second in steps:
            items += [item for item in variable_items(first, second) if item not in items]
        variable.append(items)

    def view(rows):
        if not pairs:
            return rows
        return [stable_view(row, items) for row, items in zip(rows, variable)]
    return variable, view
