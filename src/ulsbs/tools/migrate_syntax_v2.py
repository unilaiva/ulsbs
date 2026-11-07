#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Migrate named public ULSBS interfaces to syntax v2, with per-file validation."""

from __future__ import annotations

import argparse
import difflib
import os
import re
import stat
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


@dataclass
class Diagnostic:
    line: int
    column: int
    message: str


@dataclass
class Result:
    text: str
    converted: Counter[str] = field(default_factory=Counter)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def safe(self) -> bool:
        return not self.diagnostics


@dataclass
class Token:
    start: int
    end: int
    name: str
    letters: str


VERBATIM_ENVS = {
    "verbatim", "verbatim*", "Verbatim", "Verbatim*", "BVerbatim", "LVerbatim",
    "SaveVerbatim", "lstlisting", "minted", "comment", "filecontents", "filecontents*",
    "lilypond", "lilypond*", "lilypondcode",
}
COUNTER_COMMANDS = {
    "newcounter", "setcounter", "addtocounter", "stepcounter", "refstepcounter",
    "value", "arabic", "roman", "Roman", "alph", "Alph", "fnsymbol",
    "setcounterref", "setcounterpageref", "counterwithin", "counterwithout",
}
DEFINITIONS = {"newcommand", "renewcommand", "providecommand", "DeclareRobustCommand"}
DOCUMENT_DEFINITIONS = {
    "NewDocumentCommand", "RenewDocumentCommand", "ProvideDocumentCommand",
    "DeclareDocumentCommand", "NewExpandableDocumentCommand", "RenewExpandableDocumentCommand",
}
EXECUTION_ARGUMENTS = {
    "AtBeginDocument": {0}, "AtEndDocument": {0}, "AtEndOfClass": {0},
    "AtEndOfPackage": {0}, "AddToHook": {1}, "AtBeginEnvironment": {1},
    "AtEndEnvironment": {1}, "AfterEndEnvironment": {1}, "BeforeBeginEnvironment": {1},
    "textcolor": {1}, "colorbox": {1}, "fcolorbox": {2}, "href": {1},
}
URL_COMMANDS = {"url", "nolinkurl", "path", "href"}
SOURCE_SUFFIXES = {".tex", ".cls", ".sty", ".sbx"}
REFERENCE_OPERANDS = {
    "let": 2, "futurelet": 3, "string": 1, "meaning": 1, "noexpand": 1,
    "show": 1, "ifx": 2, "ifdefined": 1, "ifcat": 2, "expandafter": 2,
    "global": 1, "long": 1, "outer": 1, "protected": 1,
    "aftergroup": 1, "afterassignment": 1, "chardef": 1, "mathchardef": 1,
}
SKIP_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "__pycache__", "node_modules",
    "build", "dist", "generated", "_generated", "_build", "out", "output",
    "tmp", "temp", ".tmp", ".cache", ".tox", ".mypy_cache", ".pytest_cache",
    "result", "results", "deploy",
}


def _space(text: str, pos: int) -> int:
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
        elif text[pos] == "%":
            end = text.find("\n", pos)
            pos = len(text) if end < 0 else end + 1
        else:
            break
    return pos


def _group(text: str, pos: int, opening: str = "{", closing: str = "}") -> tuple[int, int] | None:
    pos = _space(text, pos)
    if pos >= len(text) or text[pos] != opening:
        return None
    start = pos + 1
    depth = 1
    pos += 1
    braces = 0
    while pos < len(text):
        char = text[pos]
        if char == "\\":
            pos += 2
            continue
        if char == "%":
            end = text.find("\n", pos)
            pos = len(text) if end < 0 else end + 1
            continue
        if opening == "[":
            if char == "{":
                braces += 1
            elif char == "}":
                braces -= 1
        if not braces:
            if char == opening:
                depth += 1
            elif char == closing:
                depth -= 1
                if not depth:
                    return start, pos
        pos += 1
    return None


def _lily_end(text: str, pos: int) -> int | None:
    """Balance LilyPond braces without treating quoted strings as TeX."""
    depth = 1
    quoted = False
    pos += 1
    while pos < len(text):
        if quoted:
            if text[pos] == "\\":
                pos += 2
                continue
            if text[pos] == '"':
                quoted = False
        elif text.startswith("%{", pos):
            end = text.find("%}", pos + 2)
            if end < 0:
                return None
            pos = end + 2
            continue
        elif text[pos] == "%":
            end = text.find("\n", pos)
            pos = len(text) if end < 0 else end + 1
            continue
        elif text[pos] == '"':
            quoted = True
        elif text[pos] == "{":
            depth += 1
        elif text[pos] == "}":
            depth -= 1
            if not depth:
                return pos + 1
        pos += 1
    return None


def _url_end(text: str, pos: int) -> int | None:
    """URL readers use literal percent signs/backslashes, not TeX comments."""
    if pos >= len(text):
        return None
    if text[pos] != "{":
        if text[pos] not in "|!+":
            return None
        end = text.find(text[pos], pos + 1)
        return None if end < 0 else end + 1
    depth = 1
    for end in range(pos + 1, len(text)):
        if text[end] == "{":
            depth += 1
        elif text[end] == "}":
            depth -= 1
            if not depth:
                return end + 1
    return None


def _scan(text: str, at_letter: bool, issue) -> tuple[list[Token], str]:
    tokens: list[Token] = []
    masked = list(text)
    mode = (at_letter, False)
    modes: list[tuple[bool, bool]] = []
    pos = 0
    reference_count = 0
    definition_target = False
    let_equals = False
    reference_source = ""

    def hide(start: int, end: int) -> None:
        masked[start:end] = ["\n" if c == "\n" else " " for c in text[start:end]]

    while pos < len(text):
        start = pos
        char = text[pos]
        if char == "%":
            end = text.find("\n", pos)
            pos = len(text) if end < 0 else end
            hide(start, pos)
            continue
        if text.startswith("^^", pos):
            issue(pos, "unsupported TeX ^^ character translation")
        if char == "{":
            modes.append(mode)
        elif char == "}" and modes:
            mode = modes.pop()
        if char != "\\":
            if reference_count and not char.isspace():
                if definition_target and char in "{*":
                    if char == "{":
                        definition_target = False
                elif not (let_equals and char == "="):
                    reference_count -= 1
            pos += 1
            continue
        referenced = reference_count > 0
        if referenced:
            reference_count -= 1
            definition_target = False
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        if mode[0]:
            letters += "@"
        if mode[1]:
            letters += "_:"
        pos += 1
        if pos < len(text) and text[pos] in letters:
            while pos < len(text) and text[pos] in letters:
                pos += 1
        elif pos < len(text):
            pos += 1
        name = text[start + 1:pos]
        if referenced and name in URL_COMMANDS and reference_source in {"expandafter", "noexpand"}:
            issue(start, "expanded URL invocation requires review")
        if not referenced and name in URL_COMMANDS:
            command_end = pos
            body = _space(text, pos)
            if name == "href":
                option = _group(text, body, "[", "]")
                if option:
                    body = _space(text, option[1] + 1)
                end = _url_end(text, body) if text[body:body + 1] == "{" else None
            else:
                end = _url_end(text, body)
            if end is None:
                issue(start, f"unsupported or unterminated \\{name} URL argument")
                hide(start, len(text))
                break
            value = text[body + 1:end - 1]
            if re.search(r"#[0-9]", value) or (name == "href" and ("\\" in value or "{" in value or "^^" in value)):
                issue(body, "computed or expanded URL argument requires review")
            tokens.append(Token(start, command_end, name, letters))
            # Retain argument braces for surrounding definition/body analysis.
            if text[body] == "{":
                hide(body + 1, end - 1)
            else:
                hide(body, end)
            pos = end
            continue
        if not referenced and name in {"verb", "Verb", "lstinline"}:
            if pos < len(text) and text[pos] == "*":
                pos += 1
            if name == "lstinline":
                option = _group(text, pos, "[", "]")
                if option:
                    pos = option[1] + 1
            if pos >= len(text) or text[pos].isspace():
                issue(start, "malformed inline verbatim delimiter")
                hide(start, len(text))
                break
            end = text.find(text[pos], pos + 1)
            if end < 0:
                issue(start, "unterminated inline verbatim")
                end = len(text) - 1
            pos = end + 1
            hide(start, pos)
            continue
        if not referenced and name == "begin":
            group = _group(text, pos)
            if group and text[group[0]:group[1]] in VERBATIM_ENVS:
                env = text[group[0]:group[1]]
                end = re.search(r"\\end\s*\{" + re.escape(env) + r"\}", text[group[1] + 1:])
                if end is None:
                    issue(start, f"unterminated opaque environment {env}")
                pos = len(text) if end is None else group[1] + 1 + end.end()
                hide(start, pos)
                continue
        if not referenced and name == "lilypond":
            body = _space(text, pos)
            option = _group(text, body, "[", "]")
            if option:
                body = _space(text, option[1] + 1)
            end = _lily_end(text, body) if text[body:body + 1] == "{" else None
            if end is None:
                issue(start, "unsupported or unterminated LilyPond body")
            pos = len(text) if end is None else end
            hide(start, pos)
            continue
        tokens.append(Token(start, pos, name, letters))
        if not referenced:
            if name in DEFINITIONS | DOCUMENT_DEFINITIONS | {"def", "gdef", "edef", "xdef"}:
                reference_count = 1
                definition_target = True
                let_equals = False
                reference_source = name
            elif name in REFERENCE_OPERANDS:
                reference_count = REFERENCE_OPERANDS[name]
                let_equals = name == "let"
                reference_source = name
        if name == "makeatletter":
            mode = (True, mode[1])
        elif name == "makeatother":
            mode = (False, mode[1])
        elif name == "ExplSyntaxOn":
            mode = (mode[0], True)
        elif name == "ExplSyntaxOff":
            mode = (mode[0], False)
        elif name in {"begingroup", "bgroup"}:
            modes.append(mode)
        elif name in {"endgroup", "egroup"} and modes:
            mode = modes.pop()
    return tokens, "".join(masked)


def migrate_text(
    text: str, *, at_letter: bool = False,
    command_renames: dict[str, str] | None = None,
    boolean_setters: dict[str, tuple[str, str]] | None = None,
    name_argument_renames: dict[str, dict[str, str]] | None = None,
) -> Result:
    """Validate a source before applying any edits. No TeX expansion is performed.

    Mapping overrides are useful for isolated scanner tests. Production defaults
    come exclusively from the public, pure-data naming contract.
    """
    from .naming_v2 import COMMAND_EXPANSIONS, REMOVED_COMMANDS

    if command_renames is None or boolean_setters is None or name_argument_renames is None:
        from .naming_v2 import BOOLEAN_SETTERS, COMMAND_RENAMES, NAME_ARGUMENT_RENAMES
        if command_renames is None:
            command_renames = COMMAND_RENAMES
        if boolean_setters is None:
            boolean_setters = BOOLEAN_SETTERS
        if name_argument_renames is None:
            name_argument_renames = NAME_ARGUMENT_RENAMES
    result = Result(text)
    edits: dict[tuple[int, int], str] = {}

    def issue(pos: int, message: str) -> None:
        result.diagnostics.append(Diagnostic(
            text.count("\n", 0, pos) + 1, pos - text.rfind("\n", 0, pos), message))

    tokens, visible = _scan(text, at_letter, issue)
    token_at = {token.start: token for token in tokens}
    unsafe: list[tuple[int, int]] = []
    safe_bodies: list[tuple[int, int]] = []
    literal_regions: list[tuple[int, int]] = []
    reference_tokens: set[int] = set()
    definition_bodies: list[tuple[int, int]] = []
    expanded_bodies: list[tuple[int, int]] = []
    chorus_environments: list[tuple[Token, int, int]] = []
    known = set(command_renames) | set(boolean_setters) | set(COMMAND_EXPANSIONS) | REMOVED_COMMANDS
    for mapping in name_argument_renames.values():
        known.update(mapping)

    def edit(start: int, end: int, value: str, label: str) -> None:
        if text[start:end] != value and (start, end) not in edits:
            edits[start, end] = value
            result.converted[label] += 1

    def argument(pos: int, category: str, expression: bool = False) -> int:
        group = _group(visible, pos)
        if group is None:
            issue(pos, f"unsupported {category} argument: expected balanced literal braces")
            return pos
        start, end = group
        literal_regions.append((start, end))
        value = visible[start:end]
        mapping = name_argument_renames.get(category, {})
        stripped = value.strip()
        if category == "environment" and "".join(value.split()) == "chorus":
            issue(start, "chorus environment reference or fragmented name requires review")
        elif "\\" in value or "#" in value or "{" in value:
            issue(start, f"computed {category} identifier requires review")
        elif expression:
            for match in re.finditer(r"[A-Za-z][A-Za-z0-9_.:-]*", value):
                old = match.group()
                if old in mapping:
                    edit(start + match.start(), start + match.end(), mapping[old], category + ":" + old)
        elif stripped in mapping:
            offset = len(value) - len(value.lstrip())
            edit(start + offset, start + offset + len(stripped), mapping[stripped], category + ":" + stripped)
        elif "".join(value.split()) in mapping:
            issue(start, f"fragmented {category} identifier requires review")
        return end + 1

    for index, token in enumerate(tokens):
        name, pos = token.name, token.end
        if token.start in reference_tokens or any(a <= token.start < b for a, b in literal_regions):
            group = _group(visible, pos) if name in {"begin", "end"} else None
            if group and "".join(visible[group[0]:group[1]].split()) == "chorus":
                issue(token.start, "chorus environment in a reference/literal context requires review")
            if name in {"makeatletter", "makeatother", "ExplSyntaxOn", "ExplSyntaxOff"}:
                issue(token.start, "tokenization switch in a reference/literal context requires review")
            continue
        if name in {"catcode", "scantokens", "endlinechar", "obeyspaces"}:
            issue(token.start, f"unsupported tokenization construct \\{name}")
        if name in {"AddToHook", "AddToHookNext", "RemoveFromHook", "UseHook", "DeclareHookRule"}:
            group = _group(visible, pos)
            if group and visible[group[0]:group[1]].strip().startswith("env/chorus/"):
                issue(token.start, "chorus environment hook requires review")
        if name == "expanded":
            group = _group(visible, pos)
            if group:
                expanded_bodies.append(group)
        if name in {"csname", "ifcsname"}:
            close = next((t for t in tokens[index + 1:] if t.name == "endcsname"), None)
            end = close.start if close else len(text)
            value = re.sub(r"\s+", "", visible[pos:end])
            register = value.split("@", 1)[-1] if value.startswith(("c@", "cl@", "p@")) else value
            if not close or "\\" in value or "#" in value or value in known or register in known:
                issue(token.start, "dynamic control-sequence reference requires review")
            unsafe.append((pos, end))
        if name in {"@namedef", "@nameuse", "@ifundefined"}:
            group = _group(visible, pos)
            if group:
                value = visible[group[0]:group[1]].strip()
                if value in known or "\\" in value or "#" in value:
                    issue(token.start, "named control-sequence reference requires review")
        if name in REFERENCE_OPERANDS:
            cursor = _space(visible, pos)
            for _ in range(REFERENCE_OPERANDS[name]):
                if visible[cursor:cursor + 1] == "=":
                    cursor = _space(visible, cursor + 1)
                operand = token_at.get(cursor)
                end = operand.end if operand else cursor + 1
                if operand:
                    reference_tokens.add(operand.start)
                unsafe.append((cursor, end))
                cursor = _space(visible, end)
        if name in {"detokenize", "unexpanded", "write", "message", "errmessage", "pdfstringdef"}:
            group = _group(visible, pos)
            if group:
                unsafe.append(group)
                literal_regions.append(group)
        if name in DEFINITIONS | DOCUMENT_DEFINITIONS | {"def", "gdef", "edef", "xdef"}:
            cursor = _space(visible, pos)
            if visible[cursor:cursor + 1] == "*":
                cursor = _space(visible, cursor + 1)
            target_group = _group(visible, cursor)
            target = token_at.get(_space(visible, target_group[0]) if target_group else cursor)
            if target:
                unsafe.append((target.start, target.end))
                reference_tokens.add(target.start)
            if target_group:
                cursor = target_group[1] + 1
            elif target:
                cursor = target.end
            else:
                issue(token.start, f"unsupported \\{name} target")
                continue
            if name in {"def", "gdef", "edef", "xdef"}:
                opening = visible.find("{", cursor)
                unsafe.append((cursor, len(text) if opening < 0 else opening))
                body = _group(visible, opening) if opening >= 0 else None
            else:
                for _ in range(2):
                    option = _group(visible, cursor, "[", "]")
                    if not option:
                        break
                    unsafe.append(option)
                    cursor = option[1] + 1
                if name in DOCUMENT_DEFINITIONS:
                    spec = _group(visible, cursor)
                    if spec:
                        unsafe.append(spec)
                        cursor = spec[1] + 1
                body = _group(visible, cursor)
            if body:
                definition_bodies.append(body)
                if name in {"edef", "xdef"} or "Expandable" in name:
                    unsafe.append(body)
                    expanded_bodies.append(body)
                else:
                    safe_bodies.append(body)
            else:
                issue(token.start, f"missing balanced \\{name} body")
        if name in COUNTER_COMMANDS:
            cursor = pos
            if visible[_space(visible, cursor):_space(visible, cursor) + 1] == "*":
                cursor = _space(visible, cursor) + 1
            cursor = argument(cursor, "counter")
            if name in {"counterwithin", "counterwithout"}:
                argument(cursor, "counter")
            elif name == "newcounter":
                option = _group(visible, cursor, "[", "]")
                if option:
                    value = visible[option[0]:option[1]]
                    mapping = name_argument_renames.get("counter", {})
                    if value.strip() in mapping:
                        offset = len(value) - len(value.lstrip())
                        old = value.strip()
                        edit(option[0] + offset, option[0] + offset + len(old), mapping[old], "counter:" + old)
                    elif "\\" in value or "#" in value:
                        issue(option[0], "computed counter parent requires review")
        if name in {"begin", "end", "newenvironment", "renewenvironment", "provideenvironment",
                    "AtBeginEnvironment", "AtEndEnvironment", "AfterEndEnvironment", "BeforeBeginEnvironment"}:
            cursor = pos
            if visible[_space(visible, cursor):_space(visible, cursor) + 1] == "*":
                cursor = _space(visible, cursor) + 1
            group = _group(visible, cursor)
            if name in {"begin", "end"} and group and visible[group[0]:group[1]] == "chorus":
                literal_regions.append(group)
                chorus_environments.append((token, *group))
                cursor = group[1] + 1
            else:
                cursor = argument(cursor, "environment")
            if name in {"newenvironment", "renewenvironment", "provideenvironment"}:
                for _ in range(2):
                    option = _group(visible, cursor, "[", "]")
                    if option:
                        unsafe.append(option)
                        cursor = option[1] + 1
                for _ in range(2):
                    body = _group(visible, cursor)
                    if body:
                        definition_bodies.append(body)
                        safe_bodies.append(body)
                        cursor = body[1] + 1
        if name in {"color", "textcolor", "pagecolor", "colorbox", "fcolorbox", "definecolor", "providecolor", "colorlet"}:
            cursor = pos
            option = _group(visible, cursor, "[", "]")
            if option:
                cursor = option[1] + 1
            # A model option changes a color argument from a name to numeric data.
            if not option or name in {"definecolor", "providecolor", "colorlet"}:
                cursor = argument(cursor, "color", expression=name not in {"definecolor", "providecolor"})
                if name in {"colorlet", "fcolorbox"}:
                    option = _group(visible, cursor, "[", "]")
                    if option:
                        cursor = option[1] + 1
                    if not option:
                        argument(cursor, "color", expression=True)
        # These option keys have a documented color-expression grammar. Do not
        # globally replace matching words in ordinary prose or arbitrary options.
        cursor = pos
        option = (_group(visible, cursor) if name == "hypersetup"
                  else _group(visible, cursor, "[", "]"))
        if option and name in {"includegraphics", "hypersetup", "tikz", "node", "draw", "path", "fill"}:
            for match in re.finditer(r"(?:^|,)\s*(?:color|draw|fill|text|linkcolor|urlcolor|citecolor)\s*=\s*(\{[^{}]*\}|[^,]*)", visible[option[0]:option[1]]):
                start = option[0] + match.start(1)
                end = option[0] + match.end(1)
                value = visible[start:end]
                if "\\" in value or "#" in value:
                    issue(start, "computed color option requires review")
                else:
                    for word in re.finditer(r"[A-Za-z][A-Za-z0-9_.:-]*", value):
                        old = word.group()
                        new = name_argument_renames.get("color", {}).get(old)
                        if new:
                            edit(start + word.start(), start + word.end(), new, "color:" + old)

    zero_argument = {
        "else", "fi", "relax", "par", "begingroup", "endgroup", "bgroup", "egroup",
        "makeatletter", "makeatother", "ExplSyntaxOn", "ExplSyntaxOff",
        "obeylines", "disobeylines", "sclearpage", "clearpage", "cleardoublepage",
        "newpage", "pagebreak", "nopagebreak", "appendix", "endverse", "endchorus",
        "beginverse", "beginchorus", "chorus", "beginrep", "endrep",
        "endsong", "endsongs", "bigskip", "medskip", "smallskip", "noindent",
        "leavevmode", "null", "strut", "normalfont", "normalsize",
    } | set(boolean_setters)
    zero_argument.update(command_renames[name] for name in tuple(zero_argument)
                         if name in command_renames)
    predicates = {name for name in (*command_renames, *command_renames.values())
                   if name.startswith("if")}
    # Unknown macro arguments may be token references, not executable material.
    # Explicit definition bodies and selected delayed/executable APIs are safe.
    for token in tokens:
        cursor = token.end
        option = _group(visible, cursor, "[", "]")
        if option:
            unsafe.append(option)
            cursor = option[1] + 1
        if token.name in zero_argument | predicates | (URL_COMMANDS - {"href"}):
            continue
        if token.name in EXECUTION_ARGUMENTS:
            for argument_index in range(max(EXECUTION_ARGUMENTS[token.name]) + 1):
                group = _group(visible, cursor)
                if not group:
                    break
                if argument_index in EXECUTION_ARGUMENTS[token.name]:
                    safe_bodies.append(group)
                else:
                    unsafe.append(group)
                cursor = group[1] + 1
                option = _group(visible, cursor, "[", "]")
                if option:
                    unsafe.append(option)
                    cursor = option[1] + 1
        else:
            for _ in range(3):
                group = _group(visible, cursor)
                if not group:
                    break
                if group not in safe_bodies:
                    unsafe.append(group)
                cursor = group[1] + 1

    song_metadata_regions: list[tuple[int, int]] = []
    for token in tokens:
        if (token.name not in {"beginsong", "begin"} or token.start in reference_tokens
                or any(a <= token.start < b for a, b in
                       (*literal_regions, *unsafe, *song_metadata_regions))):
            continue
        cursor = token.end
        if token.name == "begin":
            environment = _group(visible, cursor)
            if environment is None or visible[environment[0]:environment[1]].strip() != "song":
                continue
            cursor = environment[1] + 1
        title = _group(visible, cursor)
        if title is None:
            issue(token.start, "dynamic or malformed song title/metadata requires review")
            continue
        song_metadata_regions.append(title)
        cursor = _space(visible, title[1] + 1)
        if visible[cursor:cursor + 1] != "[":
            legacy = []
            for _ in range(3):
                group = _group(visible, cursor)
                if group is None:
                    break
                legacy.append(group)
                cursor = group[1] + 1
            if len(legacy) == 3:
                song_metadata_regions.extend(legacy)
                issue(token.start, "removed three-braced song metadata requires review; use "
                      "tags=/by=/cr= optional keys; no automatic sr conversion")
            continue
        option = _group(visible, cursor, "[", "]")
        if option is None:
            issue(cursor, "malformed song metadata option list requires review")
            continue
        song_metadata_regions.append(option)
        cursor, end = option
        key_start = cursor
        key_end: int | None = None
        # Only top-level commas and equals delimit keys. Braced/nested values
        # and escaped delimiters are literal data, not additional metadata keys.
        while cursor <= end:
            char = visible[cursor] if cursor < end else ","
            if char == "\\":
                operand = token_at.get(cursor)
                cursor = operand.end if operand else cursor + 2
                continue
            if char in "{[":
                group = (_group(visible, cursor) if char == "{"
                         else _group(visible, cursor, "[", "]"))
                if group is None or group[1] >= end:
                    issue(cursor, "malformed nested song metadata requires review")
                    break
                cursor = group[1] + 1
                continue
            if char == "=" and key_end is None:
                key_end = cursor
            if char == ",":
                key = visible[key_start:key_end if key_end is not None else cursor].strip()
                if "".join(key.split()) == "sr":
                    issue(key_start, "removed sr song metadata requires review; use "
                          "tags=/by=/cr= optional keys; no automatic sr conversion")
                elif ((not key and key_end is not None)
                      or any(marker in key for marker in ("\\", "#", "{", "["))):
                    issue(key_start, "dynamic or empty song metadata key requires review")
                key_start = cursor + 1
                key_end = None
            cursor += 1

    expansion_positions = {token.start for token, _, _ in chorus_environments}
    for previous, token in zip(tokens, tokens[1:], strict=False):
        if ((token.name in set(boolean_setters) | set(COMMAND_EXPANSIONS)
             or token.start in expansion_positions)
                and _space(visible, previous.end) == token.start
                and previous.name not in zero_argument | predicates):
            unsafe.append((token.start, token.end))

    for token in tokens:
        name = token.name
        if name in URL_COMMANDS and any(a <= token.start < b for a, b in expanded_bodies):
            issue(token.start, "URL in an expansion-time body requires review")
        if (name in {"makeatletter", "makeatother", "ExplSyntaxOn", "ExplSyntaxOff"}
                and any(a <= token.start < b for a, b in definition_bodies)):
            issue(token.start, "tokenization switch in a delayed definition requires review")
        if name in REMOVED_COMMANDS:
            if name in {"songrefs", "ulSongRefs"}:
                issue(token.start, f"removed song-reference accessor \\{name} requires review; "
                      "use tags= metadata or \\ulTagList; no automatic sr conversion")
            else:
                issue(token.start, f"removed no-op setting \\{name} requires review; do not map to active settings")
        elif name in COMMAND_EXPANSIONS:
            if any(a <= token.start < b for a, b in unsafe):
                issue(token.start, f"chorus reference \\{name} cannot become executable boundaries safely")
                continue
            edit(token.start, token.end, COMMAND_EXPANSIONS[name], name)
        elif name in boolean_setters:
            in_unsafe = any(a <= token.start < b for a, b in unsafe)
            if in_unsafe:
                issue(token.start, f"boolean reference \\{name} cannot become a setter call safely")
                continue
            setter, value = boolean_setters[name]
            edit(token.start, token.end, f"\\{setter}{{{value}}}", name)
        elif name in command_renames:
            if any(a <= token.start < b for a, b in literal_regions):
                issue(token.start, f"literal/reference use of \\{name} requires review")
                continue
            new = "\\" + command_renames[name]
            if token.end < len(text) and text[token.end] in token.letters and new[-1] in token.letters:
                new += " "
            edit(token.start, token.end, new, name)
    for token, start, end in chorus_environments:
        if any(a <= token.start < b for a, b in unsafe):
            issue(token.start, "chorus environment in a reference/argument context requires review")
            continue
        edit(start, end, "verse", "environment:chorus")
        if token.name == "begin":
            # A space terminates the inserted control word before literal lyrics.
            edit(end + 1, end + 1, "\\beginrep ", "chorus:repeat-start")
        else:
            edit(token.start, token.start, "\\endrep", "chorus:repeat-end")
    if result.diagnostics:
        return result
    for (start, end), value in sorted(edits.items(), reverse=True):
        result.text = result.text[:start] + value + result.text[end:]
    return result


def migrate_tags_text(text: str, *, legacy: bool) -> Result:
    """Validate all definitions before removing legacy literal-one count lines."""
    result = Result(text)
    output: list[str] = []
    pending: int | None = None
    definitions = 0
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        value = line.strip()
        if not value or value.startswith(("#", "%")):
            output.append(line)
            continue
        if legacy and pending is not None:
            if value != "1":
                result.diagnostics.append(Diagnostic(
                    number, 1, "legacy tag count must be literal 1; scripture counts require review"))
            pending = None
            if (not line.endswith(("\r", "\n")) and output
                    and output[-1].strip() and not output[-1].lstrip().startswith(("#", "%"))):
                output[-1] = output[-1].rstrip("\r\n")
            continue
        names = [name.strip() for name in value.split("|")]
        definitions += 1
        if re.fullmatch(r"[\d\s]+", value):
            result.diagnostics.append(Diagnostic(
                number, 1, "tag definitions must not be numeric-only"))
        if any(not name or "," in name or ";" in name for name in names):
            result.diagnostics.append(Diagnostic(
                number, 1, "tag names and aliases must be nonempty and contain no comma or semicolon"))
        ending = line[len(line.rstrip("\r\n")):]
        output.append("|".join(names) + ending)
        if legacy:
            pending = number
    if pending is not None:
        result.diagnostics.append(Diagnostic(pending, 1, "incomplete legacy tag definition: missing count"))
    if not definitions:
        result.diagnostics.append(Diagnostic(1, 1, "tag file contains no definitions"))
    if result.safe:
        result.text = "".join(output)
        if legacy or result.text != text:
            result.converted["tag definitions"] += 1
    return result


def _tag_source(path: Path) -> tuple[str, os.stat_result]:
    # Reject symlink components as well as the leaf, including dangling links.
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("symlink tag path requires an explicit resolved path")
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("tag source must be a regular file")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), encoding="utf-8", newline="") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("tag source must be a regular file")
        return stream.read(), metadata


def _write_tags(path: Path, destination: Path, text: str, metadata: os.stat_result) -> None:
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent,
                                         prefix="." + destination.name + "-", delete=False) as stream:
            temporary = stream.name
            stream.write(text)
            stream.flush()
            os.fchmod(stream.fileno(), stat.S_IMODE(metadata.st_mode))
            os.fsync(stream.fileno())
        current = path.lstat()
        if (current.st_dev, current.st_ino, current.st_mtime_ns, current.st_size) != (
                metadata.st_dev, metadata.st_ino, metadata.st_mtime_ns, metadata.st_size):
            raise ValueError("tag source changed during migration")
        if path == destination:
            os.replace(temporary, path)
        else:
            # Publishing a hard link is atomic and fails if any destination exists.
            os.link(temporary, destination)
            path.unlink()
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def _paths(values: Sequence[str]) -> list[Path]:
    paths: set[Path] = set()
    for value in values:
        path = Path(value)
        if path.is_file():
            if path.suffix not in SOURCE_SUFFIXES:
                raise ValueError(f"not a .tex, .cls, .sty or .sbx source: {path}")
            paths.add(path)
        elif path.is_dir():
            for root, dirs, files in os.walk(path, followlinks=False):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS
                           and not d.startswith((".", "temp.", "tmp."))]
                paths.update(Path(root) / f for f in files
                             if Path(f).suffix in SOURCE_SUFFIXES
                             and not f.startswith((".", "~")) and not (Path(root) / f).is_symlink())
        else:
            raise ValueError(f"path does not exist: {path}")
    return sorted(paths)


def _atomic_write(path: Path, text: str) -> None:
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent,
                                         prefix="." + path.name + "-", delete=False) as stream:
            temporary = stream.name
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true", help="exit 1 for changes or diagnostics")
    modes.add_argument("--diff", action="store_true", help="show validated unified diffs")
    modes.add_argument("--write", action="store_true", help="atomically write validated files")
    parser.add_argument("--tags-file", metavar="FILE", help="validate or migrate explicit tag definitions to .txt")
    parser.add_argument("paths", nargs="*", metavar="PATH")
    args = parser.parse_intermixed_args(argv)
    if not args.paths and not args.tags_file:
        parser.error("provide at least one PATH or --tags-file FILE")
    try:
        paths = _paths(args.paths)
    except ValueError as exc:
        parser.error(str(exc))
    changed = review = 0
    total: Counter[str] = Counter()
    if args.tags_file:
        path = Path(args.tags_file)
        destination = path.with_suffix(".txt")
        try:
            source, metadata = _tag_source(path)
            if destination != path and os.path.lexists(destination):
                raise ValueError(f"tag destination already exists: {destination}")
            result = migrate_tags_text(source, legacy=path.suffix != ".txt")
            total.update(result.converted)
            for diagnostic in result.diagnostics:
                print(f"{path}:{diagnostic.line}:{diagnostic.column}: {diagnostic.message}", file=sys.stderr)
            if not result.safe:
                review += 1
            else:
                if destination.name != "tags.txt":
                    print(f"{destination}: configure \\ulTagFile{{{destination}}} for this nondefault filename.",
                          file=sys.stderr)
                if result.text != source or destination != path:
                    changed += 1
                    print(f"{path} -> {destination}", file=sys.stderr)
                    if args.diff:
                        sys.stdout.writelines(difflib.unified_diff(
                            source.splitlines(True), result.text.splitlines(True),
                            fromfile=str(path), tofile=str(destination)))
                    elif args.write:
                        _write_tags(path, destination, result.text, metadata)
        except (OSError, UnicodeError, ValueError) as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            review += 1
    for path in paths:
        try:
            if path.is_symlink():
                raise ValueError("symlink source requires an explicit resolved path")
            with path.open(encoding="utf-8", newline="") as stream:
                source = stream.read()
            result = migrate_text(source, at_letter=path.suffix in {".cls", ".sty"})
            total.update(result.converted)
            for diagnostic in result.diagnostics:
                print(f"{path}:{diagnostic.line}:{diagnostic.column}: {diagnostic.message}", file=sys.stderr)
            if not result.safe:
                review += 1
                continue
            if result.text != source:
                changed += 1
                if args.diff:
                    sys.stdout.writelines(difflib.unified_diff(
                        source.splitlines(True), result.text.splitlines(True),
                        fromfile=str(path), tofile=str(path)))
                elif args.write:
                    _atomic_write(path, result.text)
        except (OSError, UnicodeError, ValueError, ImportError) as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            review += 1
    if args.paths and not args.tags_file:
        print("Reminder: run --tags-file FILE separately on tag definitions; directories do not scan .can files.",
              file=sys.stderr)
    print(f"Scanned {len(paths) + bool(args.tags_file)} files; {changed} would change; {review} need review.",
          file=sys.stderr)
    for name, count in sorted(total.items()):
        print(f"  {name}: {count}", file=sys.stderr)
    return int(bool(review or (args.check and changed)))


if __name__ == "__main__":
    raise SystemExit(main())
