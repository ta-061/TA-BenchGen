"""Discover the TA UUID from its headers."""
from __future__ import annotations

import re
import uuid as uuidlib
from pathlib import Path

from ..errors import ExecutionError


def discover_uuid(source: Path) -> str:
    """Read a UUID initializer/string from headers; ambiguous TAs are rejected.

    Several UUIDs are accepted only when `#define TA_UUID <name>` selects one of them
    (a TA that also names the UUID of another TA it calls).
    """
    values: set[str] = set()
    named: dict[str, str] = {}
    selected: set[str] = set()
    for header in sorted(Path(source).rglob('*.h')):
        if header.is_symlink():
            raise ExecutionError(f'Symbolic-link header: {header}')
        text = header.read_text(encoding='utf-8')
        text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.DOTALL).replace('\\\n', '')
        for name, value in re.findall(r'^\s*#\s*define\s+(\w*UUID\w*)\s+([^\n]+)', text, re.MULTILINE):
            match = re.search(r'"([0-9a-fA-F]{8}-[0-9a-fA-F-]{27})"', value)
            if match:
                named[name] = str(uuidlib.UUID(match.group(1)))
                values.add(named[name])
                continue
            if '{' not in value:
                # Alias such as #define TA_UUID TA_SECURE_KV_UUID.
                if name == 'TA_UUID' and re.fullmatch(r'\w+', value.strip()):
                    selected.add(value.strip())
                continue
            nums = re.findall(r'0x[0-9a-fA-F]+|\b\d+\b', value)
            if len(nums) == 11:
                n = [int(x, 0) for x in nums]
                if n[0] > 0xFFFFFFFF or any(x > 0xFFFF for x in n[1:3]) or any(x > 255 for x in n[3:]):
                    raise ExecutionError(f'Invalid UUID initializer in {header}: {name}')
                hex_value = f'{n[0]:08x}{n[1]:04x}{n[2]:04x}' + ''.join(f'{x:02x}' for x in n[3:])
                named[name] = str(uuidlib.UUID(hex_value))
                values.add(named[name])
    if len(values) > 1 and len(selected) == 1 and next(iter(selected)) in named:
        return named[next(iter(selected))]
    if len(values) != 1:
        raise ExecutionError(f'Expected one TA UUID in headers, found {len(values)}')
    return next(iter(values))
