"""Reusable witness predicates; class definitions select names, never executable code."""


def normal_error(test):
    return (test['observed']['normal'][test['witness_step'] - 1]['result'] != 0,
            'normal TA did not return an error at witness')


def shared_memory_changed(test):
    index = test['witness_step'] - 1
    valid = all(any(e['before'] != e['after'] for e in test['observed'][variant][index].get('events', []))
                for variant in ('normal', 'defective'))
    return valid, 'witness requires a measured shared-memory change in both variants'


WITNESS_CONDITIONS = {'normal_error_at_witness': normal_error, 'shared_memory_changed': shared_memory_changed}


def condition_names(definition):
    names = list(definition.get('witness_conditions', []))
    if definition.get('extra_condition') is not None:
        names.append(definition['extra_condition'])
    return names
