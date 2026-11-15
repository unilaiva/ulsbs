# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared named-variant records and literal main-source availability discovery.

This is a bounded TeX reader, not an interpreter: declarations must be literal,
top-level preamble statements. It never expands macros or reads custom classes.
The compiler and syntax-v3 migrator use the same validation boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
import re
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class Variant:
    """One registered preset; visibility defaults belong to TeX, not Python."""

    name: str
    preset: str
    score_recipe: str
    filename_marker: str
    presentation: str
    editions: tuple[str, ...]


def _load_registry() -> Mapping[str, Variant]:
    """Read literal TeX records through package resources, including in a wheel."""
    text = (files("ulsbs") / "assets/tex/ulsbs-variants.def.tex").read_text(encoding="utf-8")
    registry: dict[str, Variant] = {}
    record = re.compile(r"\\ulsbsVariantRecord" + r"\{([a-zA-Z0-9_.,-]*)\}" * 6)
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("%"):
            continue
        match = record.fullmatch(line)
        if match is None:
            raise ValueError(f"Malformed ULSBS variant registry record: {line!r}")
        name, preset, recipe, marker, presentation, editions = match.groups()
        if not re.fullmatch(r"[a-z][a-z0-9-]*", name) or name in registry:
            raise ValueError(f"Invalid or duplicate ULSBS variant registry name: {name!r}")
        supported = tuple(editions.split(","))
        if (not recipe or not presentation or "ordinary" not in supported
                or len(set(supported)) != len(supported)
                or set(supported) - {"ordinary", "multikey"}):
            raise ValueError(f"Invalid ULSBS variant registry policy: {name!r}")
        registry[name] = Variant(name, preset, recipe, marker, presentation, supported)
    if "default" not in registry:
        raise ValueError("ULSBS variant registry requires default")
    return MappingProxyType(registry)


VARIANTS = _load_registry()


def validate_variant_names(value: str, *, require_default: bool = False) -> tuple[str, ...]:
    """Validate a literal comma list without expansion, case folding or deduping.

    Preserve declaration order here; job selection owns default-first ordering.
    Availability requires default, while explicit compiler subsets need not.
    """
    names = tuple(item.strip() for item in value.split(","))
    for name in names:
        if not re.fullmatch(r"[a-z][a-z0-9-]*", name):
            raise ValueError(f"Invalid literal variant identifier: {name!r}")
        if name not in VARIANTS:
            raise ValueError(f"Unknown variant: {name!r}")
    if len(set(names)) != len(names):
        raise ValueError("Duplicate variant identifiers")
    if require_default and "default" not in names:
        raise ValueError("Available variants must include default")
    return names


@dataclass(frozen=True)
class DocumentClass:
    """Literal main class and raw options, with source offsets for migration."""

    name: str
    options: str | None
    start: int
    end: int


def _space(text: str, pos: int) -> int:
    """Skip TeX whitespace/comments without interpreting escaped percent signs."""
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
        elif text[pos] == "%":
            end = text.find("\n", pos)
            pos = len(text) if end < 0 else end + 1
        else:
            break
    return pos


_CONTROL_SEQUENCE = re.compile(r"\\(?:[a-zA-Z]+|[^\r\n])")


def _command_end(text: str, pos: int) -> int:
    """Consume one control word or escaped character at a backslash."""
    match = _CONTROL_SEQUENCE.match(text, pos)
    return match.end() if match else pos + 1


def _uncomment(text: str) -> str:
    """Remove comments including their newline, preserving escaped characters."""
    result = []
    pos = 0
    while pos < len(text):
        if text[pos] == "%":
            end = text.find("\n", pos)
            pos = len(text) if end < 0 else end + 1
        elif text[pos] == "\\":
            end = _command_end(text, pos)
            result.append(text[pos:end])
            pos = end
        else:
            result.append(text[pos])
            pos += 1
    return "".join(result)


def _group(text: str, pos: int, opening: str = "{", *, literal: bool = False) -> tuple[str, int]:
    """Read a balanced group or brace-protected class option, returning raw body/end.

    In an optional argument a closing bracket inside braces is not a terminator.
    Literal URL bodies retain percent signs; normal TeX comments hide delimiters.
    """
    pos = _space(text, pos)
    if text[pos:pos + 1] != opening:
        raise ValueError(f"Expected literal {opening!r} at source offset {pos}")
    start = pos + 1
    depth = 0
    pos += 1
    while pos < len(text):
        char = text[pos]
        if char == "\\" and not literal:
            pos = _command_end(text, pos)
            continue
        if char == "%" and not literal:
            end = text.find("\n", pos)
            pos = len(text) if end < 0 else end + 1
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            if depth == 0:
                if opening == "{":
                    return text[start:pos], pos + 1
                raise ValueError(f"Unbalanced class options at source offset {pos}")
            depth -= 1
        elif char == "]" and opening == "[" and depth == 0:
            return text[start:pos], pos + 1
        pos += 1
    raise ValueError(f"Unterminated {opening!r} group at source offset {start - 1}")


_OPAQUE_ENVIRONMENTS = {
    "verbatim", "verbatim*", "Verbatim", "Verbatim*", "BVerbatim", "LVerbatim",
    "SaveVerbatim", "lstlisting", "minted", "comment", "filecontents", "filecontents*",
    "lilypond", "lilypond*", "lilypondcode",
}


def read_documentclass(text: str) -> DocumentClass | None:
    r"""Find one literal top-level \documentclass before \begin{document}.

    Comments, grouped definitions/arguments and common literal regions are opaque.
    Multiple live declarations and malformed input fail closed, never selecting a
    convenient later match. Conditional execution and custom catcodes are outside
    this reader's contract; availability must not rely on them.
    """
    declaration = None
    pos = 0
    while pos < len(text):
        pos = _space(text, pos)
        if pos == len(text):
            break
        if text[pos] == "{":
            _, pos = _group(text, pos)
            continue
        if text[pos] != "\\":
            pos += 1
            continue
        start = pos
        end = _command_end(text, pos)
        command = text[pos + 1:end]
        pos = end
        if command in {"verb", "Verb", "lstinline"}:
            if text[pos:pos + 1] == "*":
                pos += 1
            # Percent can itself be the verbatim delimiter, not a TeX comment.
            while text[pos:pos + 1] in {" ", "\t"}:
                pos += 1
            if command == "lstinline" and text[pos:pos + 1] == "[":
                _, pos = _group(text, pos, "[")
                while text[pos:pos + 1] in {" ", "\t"}:
                    pos += 1
            if pos >= len(text) or text[pos].isspace():
                raise ValueError(f"Missing literal delimiter for \\{command}")
            end = text.find(text[pos], pos + 1)
            if end < 0:
                raise ValueError(f"Unterminated \\{command} literal")
            pos = end + 1
        elif command in {"url", "nolinkurl", "path", "href", "detokenize"}:
            pos = _space(text, pos)
            if command == "href" and text[pos:pos + 1] == "[":
                _, pos = _group(text, pos, "[")
                pos = _space(text, pos)
            if command in {"url", "nolinkurl", "path"} and text[pos:pos + 1] in {"|", "!", "+"}:
                end = text.find(text[pos], pos + 1)
                if end < 0:
                    raise ValueError(f"Unterminated \\{command} literal")
                pos = end + 1
            else:
                _, pos = _group(text, pos, literal=command != "detokenize")
        elif command == "string":
            pos = _space(text, pos)
            pos = _command_end(text, pos) if text[pos:pos + 1] == "\\" else pos + 1
        elif command == "begin":
            name, pos = _group(text, pos)
            name = _uncomment(name).strip()
            if name == "document":
                break
            if name in _OPAQUE_ENVIRONMENTS:
                marker = rf"\end{{{name}}}"
                end = text.find(marker, pos)
                if end < 0:
                    raise ValueError(f"Unterminated {name!r} literal environment")
                pos = end + len(marker)
        elif command == "documentclass":
            if declaration is not None:
                raise ValueError("Multiple documentclass declarations")
            pos = _space(text, pos)
            options = None
            if text[pos:pos + 1] == "[":
                options, pos = _group(text, pos, "[")
            name, pos = _group(text, pos)
            name = _uncomment(name).strip()
            if not re.fullmatch(r"[a-zA-Z0-9_./-]+", name):
                raise ValueError("The document class name must be literal")
            declaration = DocumentClass(name, options, start, pos)
    return declaration


def available_variants(text: str) -> tuple[str, ...]:
    """Return declared songbook availability; omission/unrelated inputs mean default.

    Only a braced literal variants option in the main class invocation declares
    availability. Reject repeated options even if identical. Unrelated options
    are split only at unbraced commas, never interpreted or expanded.
    """
    declaration = read_documentclass(text)
    if declaration is None or not declaration.name.startswith("ulsbs-songbook"):
        return ("default",)
    options = _uncomment(declaration.options or "")
    entries = []
    start = depth = pos = 0
    while pos < len(options):
        char = options[pos]
        if char == "\\":
            pos = _command_end(options, pos)
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif char == "," and depth == 0:
            entries.append(options[start:pos])
            start = pos + 1
        pos += 1
    entries.append(options[start:])
    selected = None
    for entry in entries:
        key, separator, value = entry.partition("=")
        if key.strip() != "variants":
            continue
        if selected is not None:
            raise ValueError("Multiple variants declarations")
        value = value.strip()
        if not separator or not value.startswith("{"):
            raise ValueError("variants requires a braced literal list")
        body, end = _group(value, 0)
        if end != len(value):
            raise ValueError("Unexpected tokens after variants list")
        selected = validate_variant_names(body, require_default=True)
    return selected if selected is not None else ("default",)
