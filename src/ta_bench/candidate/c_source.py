"""Lexical C helpers. These locate text; they do not interpret C semantics."""
from __future__ import annotations

import re


def mask_c(source: str, *, keep_literals: bool = False) -> str:
    """Mask comments and, by default, literals without disturbing offsets or line numbers."""
    token = re.compile(r'/\*.*?\*/|//(?:\\\n|[^\n])*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.DOTALL)

    def replace(match):
        text = match.group()
        if keep_literals and text[0] in {"'", '"'}:
            return text
        return "".join("\n" if c == "\n" else " " for c in text)

    return token.sub(replace, source)


def function_ranges(source: str) -> dict[str, list[tuple[int, int]]]:
    """Locate C function bodies conservatively, ignoring braces in comments/literals.

    This checks lexical existence, not C semantics. Unsupported macro-generated
    functions are rejected instead of claiming their locations were verified.
    """
    masked = mask_c(source)
    ranges: dict[str, list[tuple[int, int]]] = {}
    # OP-TEE entry points and ordinary C definitions. Balanced parameter parsing
    # supports pointer parameters; attributes between ')' and '{' are tolerated.
    for match in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", masked):
        name = match.group(1)
        if name in {"if", "for", "while", "switch", "sizeof", "_Alignof", "__attribute__"}:
            continue
        depth = 1
        cursor = match.end()
        while cursor < len(masked) and depth:
            depth += (masked[cursor] == "(") - (masked[cursor] == ")")
            cursor += 1
        if depth:
            continue
        rest = masked[cursor:]
        attr = re.match(r"\s*(?:__attribute__\s*\(\([^;{}]*\)\)\s*)*\{", rest)
        if not attr:
            continue
        brace = cursor + attr.end() - 1
        depth = 1
        end = brace + 1
        while end < len(masked) and depth:
            depth += (masked[end] == "{") - (masked[end] == "}")
            end += 1
        if depth:
            continue
        start_line = source.count("\n", 0, match.start()) + 1
        end_line = source.count("\n", 0, end - 1) + 1
        ranges.setdefault(name, []).append((start_line, end_line))
    return ranges
