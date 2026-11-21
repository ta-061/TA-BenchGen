"""Defect class definitions (config/classes.yaml)."""
import re
from pathlib import Path

import yaml

from ..errors import ValidationError
from ..runtime.events import FEATURES
from ..verification.conditions import WITNESS_CONDITIONS, condition_names

NORMAL_ERROR_AT_WITNESS = 'normal_error_at_witness'
EXTRA_CONDITIONS = (None, *WITNESS_CONDITIONS)


def load_classes(path):
    data = yaml.safe_load(Path(path).read_text())
    classes = data.get('classes', data) if isinstance(data, dict) else None
    if not isinstance(classes, dict) or not classes:
        raise ValidationError('classes must be a nonempty mapping')
    for name, value in classes.items():
        if (not isinstance(name, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]*', name)
                or not isinstance(value, dict) or not isinstance(value.get('description'), str)
                or type(value.get('supported')) is not bool):
            raise ValidationError('each class requires description and boolean supported')
        predicates = value.get('witness_conditions', [])
        required = value.get('required_features', [])
        if (not isinstance(predicates, list) or any(not isinstance(p, str) for p in predicates)
                or not isinstance(required, list) or any(not isinstance(p, str) for p in required)):
            raise ValidationError('witness_conditions and required_features must be lists of names')
        legacy = value.get('extra_condition')
        if legacy is not None and (not isinstance(legacy, str) or legacy not in WITNESS_CONDITIONS):
            raise ValidationError('unsupported extra_condition')
        names = condition_names(value)
        if len(names) != len(set(names)) or any(p not in WITNESS_CONDITIONS for p in names):
            raise ValidationError('unknown or duplicate witness_conditions')
        if len(required) != len(set(required)) or any(p not in FEATURES for p in required):
            raise ValidationError('unknown or duplicate required_features')
    return classes


def class_definitions(classes: dict) -> dict:
    """Accept the loaded mapping, a {'classes': ...} wrapper, or a list of named classes."""
    if not isinstance(classes, dict):
        raise ValidationError("classes configuration must be a mapping")
    value = classes.get("classes", classes)
    if isinstance(value, list):
        value = {c["name"]: c for c in value}
    if not isinstance(value, dict) or not value:
        raise ValidationError("classes configuration must not be empty")
    return value


def japanese_descriptions(path) -> dict:
    """Class name -> the comment line directly above its description (the Japanese wording).

    The comment is for people: it is shown in the review screen and never sent to a model.
    """
    result, name, comment = {}, None, None
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        text = line.strip()
        heading = re.fullmatch(r'([A-Z][A-Z0-9_]*):', text)
        if heading:
            name = heading[1]
        elif text.startswith('description:') and name and comment:
            result[name] = comment
        comment = text[1:].strip() if text.startswith('#') else None
    return result
