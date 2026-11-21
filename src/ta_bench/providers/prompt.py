"""The generation prompt.

prompts/candidate.txt is always sent. prompts/<feature>.txt explains the input syntax of one
runtime feature and is added only when a requested class lists it in required_features.
"""
import json
from pathlib import Path

from ..errors import ValidationError

PROMPT_FILE = Path(__file__).parent / 'prompts' / 'candidate.txt'
MAX_SOURCE_CHARS = 400_000
SOURCE_SUFFIXES = {'.c', '.h', '.mk'}


def instructions(features=()) -> str:
    text = PROMPT_FILE.read_text(encoding='utf-8')
    for feature in sorted(features):
        section = PROMPT_FILE.with_name(feature + '.txt')
        if not section.is_file():
            raise ValidationError(f'no prompt text for required feature {feature}')
        text += section.read_text(encoding='utf-8')
    return text


def prompt_sources(normal: Path) -> dict[str, str]:
    """C sources and build files of the normal TA, bounded in total size."""
    sources, total = {}, 0
    for path in sorted(normal.rglob('*')):
        if path.is_file() and (path.suffix in SOURCE_SUFFIXES or path.name == 'Makefile'):
            content = path.read_text()
            total += len(content)
            if total > MAX_SOURCE_CHARS:
                raise ValidationError(f'TA source exceeds {MAX_SOURCE_CHARS}-character prompt limit')
            sources[path.relative_to(normal).as_posix()] = content
    return sources


def messages(normal: Path, requested, classes, feedback, existing=()) -> list[dict]:
    request = {'requested': requested, 'classes': classes, 'source': prompt_sources(normal),
               'existing': list(existing), 'previous_failure': feedback}
    features = {feature for name in requested for feature in (classes.get(name) or {}).get('required_features', [])}
    return [{'role': 'system', 'content': instructions(features)},
            {'role': 'user', 'content': json.dumps(request, ensure_ascii=False)}]
