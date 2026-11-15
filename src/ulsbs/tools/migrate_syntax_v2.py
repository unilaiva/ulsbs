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
import tomllib
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
class _EditPlan:
    """Collect edits and diagnostics against one unchanged original source."""

    source: str
    edits: dict[tuple[int, int], str] = field(default_factory=dict)
    converted: Counter[str] = field(default_factory=Counter)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def issue(self, pos: int, message: str) -> None:
        """Record a diagnostic in original-source coordinates, including EOF."""
        pos = max(0, min(pos, len(self.source)))
        self.diagnostics.append(Diagnostic(
            self.source.count("\n", 0, pos) + 1,
            pos - self.source.rfind("\n", 0, pos), message))

    def edit(self, start: int, end: int, value: str, label: str) -> None:
        """Count each changed span once; never silently replace a conflicting edit."""
        if not 0 <= start <= end <= len(self.source):
            self.issue(start, "edit range outside original source requires review")
        elif (start, end) in self.edits:
            if self.edits[start, end] != value:
                self.issue(start, "conflicting edits to original source require review")
        elif self.source[start:end] != value:
            self.edits[start, end] = value
            self.converted[label] += 1


def _apply_edit_plans(text: str, *plans: _EditPlan) -> Result:
    """Validate combined original-coordinate plans before a single application.

    Insertions may touch either replacement boundary, but not its interior.
    Two plans claiming the same span (including an insertion point) require
    review even if their replacement text agrees: no plan gets precedence.
    Counts describe collected proposals even when the whole file is rejected.
    """
    combined = _EditPlan(text)
    edits: list[tuple[int, int, str]] = []
    for plan in plans:
        combined.converted.update(plan.converted)
        if plan.source != text:
            combined.issue(0, "edit plan must use the unchanged original source; requires review")
            continue
        combined.diagnostics.extend(plan.diagnostics)
        edits.extend((start, end, value) for (start, end), value in plan.edits.items())
    edits.sort(key=lambda edit: (edit[0], edit[1]))
    previous: tuple[int, int] | None = None
    for start, end, _ in edits:
        if not 0 <= start <= end <= len(text):
            combined.issue(start, "edit range outside original source requires review")
        if previous is not None and (start < previous[1] or (start, end) == previous):
            combined.issue(start, "overlapping edits to original source require review")
        previous = (start, end)
    result = Result(text, combined.converted, combined.diagnostics)
    if result.safe:
        # Reverse original-coordinate order also puts a boundary insertion on
        # the intended side of an adjacent replacement without shifting offsets.
        for start, end, value in reversed(edits):
            result.text = result.text[:start] + value + result.text[end:]
    return result


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
    "let": 2, "futurelet": 3, "newif": 1, "string": 1, "meaning": 1, "noexpand": 1,
    "show": 1, "ifx": 2, "ifdefined": 1, "ifcat": 2, "expandafter": 2,
    "global": 1, "long": 1, "outer": 1, "protected": 1,
    "aftergroup": 1, "afterassignment": 1, "chardef": 1, "mathchardef": 1,
}
# Review fences, not replacement mappings. Both naming generations need review
# even in references/definitions: legacy identity may mean a feature or a variant.
LEGACY_IDENTITY_COMMANDS = {
    "ulSongbookType",
    "ifchorded", "chordedtrue", "chordedfalse", "ifulChorded", "ulChorded",
    "iflyric", "lyrictrue", "lyricfalse", "ifulLyric", "ulLyric",
    "iflyriconly", "lyriconlytrue", "lyriconlyfalse", "ifulLyricOnly", "ulLyricOnly",
    "ifcharangobook", "charangobooktrue", "charangobookfalse", "ifulCharangoBook", "ulCharangoBook",
    "ifbassclefbook", "bassclefbooktrue", "bassclefbookfalse", "ifulBassclefBook", "ulBassclefBook",
}
REMOVED_MEASURE_COMMANDS = {"ifmeasures", "measurestrue", "measuresfalse", "ifulMeasures", "ulMeasures"}
REMOVED_SPACING_COMMANDS = {"baselineadj", "ulBaselineAdjustment", "versesep", "ulVerseSep"}
MEASURE_SETTERS = {"measurestrue": "true", "measuresfalse": "false", "ulMeasures": ""}
# Only frozen display APIs; local keys are not mechanical setter lowercasing.
DISPLAY_FEATURES = {
    "ulShowChords": "chords", "ulShowNotes": "notes", "ulShowBeats": "beats",
    "ulShowMeasures": "measures", "ulShowLilypond": "scores", "ulShowAltChords": "altchords",
    "ulShowTranslation": "translation", "ulShowExplanation": "explanation", "ulShowPassage": "passage",
    "ulShowFeeler": "feeler", "ulShowKey": "key", "ulShowGoodKeys": "goodkeys",
    "ulShowMusicComments": "musiccomments", "ulShowAuthors": "authors", "ulShowOfferedTo": "offeredto",
    "ulShowExtraInfo": "extrainfo", "ulShowTags": "tags", "ulShowPhase": "phase",
    "ulShowPhaseInToc": "phaseintoc", "ulShowImageInChapterName": "imageinchaptername",
    "ulShowImageOnChapterFrontPage": "imageonchapterfrontpage",
}
DISPLAY_SETTERS = set(DISPLAY_FEATURES)
IDENTITY_PREDICATES = {
    "ifcharangobook": "charango", "ifulCharangoBook": "charango",
    "ifbassclefbook": "bassclef", "ifulBassclefBook": "bassclef",
}
LEGACY_AVAILABILITY_MARKER = re.compile(r"(?<![A-Za-z0-9_-])ULSBS-EXTRA-VARIANTS(?![A-Za-z0-9_-])")
AVAILABILITY_COMMANDS = {"documentclass", "LoadClass", "LoadClassWithOptions", "PassOptionsToClass", "ExecuteOptions"}
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


def _scan(text: str, at_letter: bool, issue) -> tuple[list[Token], str, list[int]]:
    tokens: list[Token] = []
    markers: list[int] = []
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
            # The legacy directive lives in comments. Inspect them only here,
            # never comments inside skipped URL/verbatim/LilyPond payloads.
            for match in LEGACY_AVAILABILITY_MARKER.finditer(text, start, pos):
                markers.append(match.start())
            hide(start, pos)
            continue
        if char == "U" and LEGACY_AVAILABILITY_MARKER.match(text, pos):
            markers.append(pos)
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
    return tokens, "".join(masked), markers


def migrate_text(
    text: str, *, at_letter: bool = False,
    command_renames: dict[str, str] | None = None,
    boolean_setters: dict[str, tuple[str, str]] | None = None,
    name_argument_renames: dict[str, dict[str, str]] | None = None,
) -> Result:
    """Validate a source before applying any edits. No TeX expansion is performed.

    Mapping overrides are useful for isolated scanner tests. Production naming
    defaults come from the pure-data contract; review fences apply independently.
    """
    plan = _plan_naming_edits(
        text, at_letter=at_letter, command_renames=command_renames,
        boolean_setters=boolean_setters, name_argument_renames=name_argument_renames)
    return _apply_edit_plans(text, plan)


def _review_source_availability(text: str, visible: str, token: Token, issue) -> bool | None:
    """Validate one literal class/options invocation, never expanding or editing it.

    The shared reader owns class/list grammar. The migrator additionally rejects
    computed option keys and inherited availability; its caller owns execution scope.
    Diagnostics anchor to the original invocation, not a synthetic reader input.
    """
    from ..variants import available_variants, read_documentclass

    try:
        cursor = _space(visible, token.end)
        if token.name == "LoadClassWithOptions" and visible[cursor:cursor + 1] == "[":
            raise ValueError("LoadClassWithOptions has no leading option argument")
        forwarding = token.name in {"PassOptionsToClass", "ExecuteOptions"}
        option = (_group(visible, cursor) if forwarding else _group(visible, cursor, "[", "]"))
        if option:
            cursor = _space(visible, option[1] + 1)
        elif forwarding or visible[cursor:cursor + 1] == "[":
            raise ValueError("malformed literal class options")
        if token.name == "ExecuteOptions":
            class_name = "{ulsbs-songbook}"
        else:
            group = _group(visible, cursor)
            if group is None:
                raise ValueError("missing balanced literal class name")
            class_name = text[group[0] - 1:group[1] + 1]
        options = text[option[0]:option[1]] if option else ""
        invocation = "\\documentclass[" + options + "]" + class_name
        declaration = read_documentclass(invocation)
        if declaration is None or not declaration.name.startswith("ulsbs-songbook"):
            return
        available_variants(invocation)
        # Only unbraced commas delimit option entries. Do not interpret metadata
        # values, whose commas, equals, brackets and macros remain author data.
        has_variants = False
        if option:
            start, end = option
            cursor = start
            while cursor <= end:
                char = visible[cursor] if cursor < end else ","
                if char == "\\":
                    match = re.match(r"\\(?:[A-Za-z]+|.)", visible[cursor:end])
                    cursor += len(match[0]) if match else 1
                    continue
                if char == "{":
                    group = _group(visible, cursor)
                    if group is None or group[1] >= end:
                        raise ValueError("malformed literal class option group")
                    cursor = group[1] + 1
                    continue
                if char == ",":
                    entry = re.sub(r"%[^\n]*(?:\n|$)", "", text[start:cursor])
                    key = entry.partition("=")[0].strip()
                    if any(c in key for c in "\\#{}") or (key != "variants" and "".join(key.split()) == "variants"):
                        raise ValueError("computed or fragmented class option key")
                    has_variants |= key == "variants"
                    start = cursor + 1
                cursor += 1
        if token.name != "documentclass" and has_variants:
            raise ValueError("inherited/forwarded variants cannot declare main-source availability")
        return has_variants
    except ValueError as error:
        issue(token.start, "source availability requires review: " + str(error)
              + "; use one direct literal main-source variants declaration; no automatic replacement")
    return None


def _plan_source_availability(
    plan: _EditPlan, visible: str, markers: list[int], classes: list[tuple[Token, bool | None]],
) -> None:
    """Convert only a leading standalone directive and one proved direct class.

    Leading comments/whitespace cannot be stored in a TeX group or conditional.
    Existing declarations, later/documentation markers and all unsupported lists
    retain review. The marker's comment prefix/newline and other options survive.
    """
    text = plan.source
    if len(markers) == 1 and len(classes) == 1 and classes[0][1] is False:
        pos = markers[0]
        line_start = text.rfind("\n", 0, pos) + 1
        line_end = text.find("\n", pos)
        line_end = len(text) if line_end < 0 else line_end
        content_end = line_end - (text[line_end - 1:line_end] == "\r")
        match = re.fullmatch(r"[ \t]*%+[ \t]*ULSBS-EXTRA-VARIANTS:[ \t]*([a-z, \t]+?)[ \t]*",
                             text[line_start:content_end])
        token = classes[0][0]
        if match and not visible[:line_start].strip() and pos < token.start:
            extras = [name.strip() for name in match[1].split(",")]
            if extras == ["none"] or (len(set(extras)) == len(extras)
                                      and set(extras) <= {"charango", "bassclef"}):
                names = ["default", "lyric"] + ([] if extras == ["none"] else extras)
                declaration = "variants={" + ",".join(names) + "}"
                option = _group(visible, token.end, "[", "]")
                if option:
                    offset = option[0]
                    value = declaration + ("," if visible[option[0]:option[1]].strip() else "")
                else:
                    offset = token.end
                    value = "[" + declaration + "]"
                plan.edit(offset, offset, value, "availability:declaration")
                plan.edit(pos, content_end, "", "availability:marker")
                return
    for pos in markers:
        plan.issue(pos, "legacy availability marker ULSBS-EXTRA-VARIANTS requires review; "
                   "review literal main-source variants and unknown/repeated/conflicting entries; "
                   "old none removes instruments, not the implicit lyric companion; no automatic replacement")


def _identity_pagination_edits(
    text: str, tokens: list[Token], starts: set[int],
) -> dict[int, tuple[int, str]]:
    """Prove balanced instrument-only pagination trees, not arbitrary raw TeX.

    Branches contain only zero-argument page boundaries, nested instrument tests,
    whitespace and comments. Reject prose, groups, opaque payloads, feature tests,
    references and unknown macros. Inserted relax control words retain the raw
    delimiters' whitespace swallowing without adding a TeX group around execution.
    """
    edits: dict[int, tuple[int, str]] = {}
    pages = {"clearpage", "cleardoublepage", "newpage", "sclearpage", "relax"}
    for index, root in enumerate(tokens):
        if root.start not in starts or root.start in edits:
            continue
        stack: list[bool] = []
        proposed: dict[int, tuple[int, str]] = {}
        cursor = root.start
        for token in tokens[index:]:
            if _space(text, cursor) != token.start:
                break
            if token.name in IDENTITY_PREDICATES:
                stack.append(False)
                value = "\\ulIfVariant{" + IDENTITY_PREDICATES[token.name] + "}{\\relax"
            elif token.name == "else" and stack and not stack[-1]:
                stack[-1] = True
                value = "}{\\relax"
            elif token.name == "fi" and stack:
                value = ("}" if stack.pop() else "}{}") + "\\relax"
            elif token.name in pages and stack:
                cursor = token.end
                continue
            else:
                break
            proposed[token.start] = (token.end, value)
            cursor = token.end
            if not stack:
                edits.update(proposed)
                break
    return edits


def _direct_execution_positions(
    visible: str, tokens: list[Token], zero_argument: set[str], invocations: dict[int, int], mutations: set[int],
) -> set[int]:
    """Track positive execution boundaries, never guessing unknown macro arities.

    Known complete invocations skip their recognized arguments; the caller must
    exclude value forms with unproved execution effects. An unknown
    command invalidates proof through EOF, even after a closing group,
    including AFTER its braced arguments: it could still consume unbraced tokens.
    This is intentionally narrower than naming's delayed-body permission.
    """
    token_at = {token.start: token for token in tokens}
    direct: set[int] = set()
    groups: list[bool] = []
    ready = True
    cursor = 0
    while cursor < len(visible):
        token = token_at.get(cursor)
        if token:
            if token.start in mutations:
                ready = False
            if ready:
                direct.add(token.start)
            end = invocations.get(token.start)
            if end is not None:
                cursor = end
                continue
            if token.name in {"begingroup", "bgroup"}:
                groups.append(ready)
            elif token.name in {"endgroup", "egroup"}:
                enclosing = groups.pop() if groups else False
                if not ready:
                    # Unknown code could consume this CONTROL token rather than
                    # close a group. No outer lexical close can repair that proof.
                    groups = [False for _ in groups]
                ready = ready and enclosing
            elif token.name not in zero_argument:
                ready = False
            cursor = token.end
        else:
            if visible[cursor] == "{":
                groups.append(ready)
            elif visible[cursor] == "}":
                # Unknown grouped code can schedule aftergroup tokens or mutate
                # later consumers; a literal brace alone is not execution proof.
                enclosing = groups.pop() if groups else False
                ready = ready and enclosing
            cursor += 1
    return direct


def _plan_naming_edits(
    text: str, *, at_letter: bool = False,
    command_renames: dict[str, str] | None = None,
    boolean_setters: dict[str, tuple[str, str]] | None = None,
    name_argument_renames: dict[str, dict[str, str]] | None = None,
) -> _EditPlan:
    """Collect naming and proved semantic edits without rewriting the original."""
    from .naming_v2 import BOOLEAN_SETTERS, COMMAND_EXPANSIONS, REMOVED_COMMANDS

    if command_renames is None or boolean_setters is None or name_argument_renames is None:
        from .naming_v2 import COMMAND_RENAMES, NAME_ARGUMENT_RENAMES
        if command_renames is None:
            command_renames = COMMAND_RENAMES
        if boolean_setters is None:
            boolean_setters = BOOLEAN_SETTERS
        if name_argument_renames is None:
            name_argument_renames = NAME_ARGUMENT_RENAMES
    plan = _EditPlan(text)
    issue = plan.issue
    edit = plan.edit

    tokens, visible, markers = _scan(text, at_letter, issue)
    token_at = {token.start: token for token in tokens}
    unsafe: list[tuple[int, int]] = []
    safe_bodies: list[tuple[int, int]] = []
    literal_regions: list[tuple[int, int]] = []
    reference_tokens: set[int] = set()
    definition_bodies: list[tuple[int, int]] = []
    expanded_bodies: list[tuple[int, int]] = []
    chorus_environments: list[tuple[Token, int, int]] = []
    current_option_forwarders: set[int] = set()
    complete_invocations: dict[int, int] = {}
    mutation_targets: dict[int, set[str]] = {}
    display_commands = DISPLAY_SETTERS | {old for old, (setter, _) in BOOLEAN_SETTERS.items()
                                          if setter in DISPLAY_SETTERS}
    scope_commands = display_commands | set(MEASURE_SETTERS)
    review_commands = (LEGACY_IDENTITY_COMMANDS | REMOVED_MEASURE_COMMANDS | display_commands
                       | REMOVED_SPACING_COMMANDS | {"chordsoff"} | AVAILABILITY_COMMANDS)
    known = (set(command_renames) | set(boolean_setters) | set(COMMAND_EXPANSIONS)
             | REMOVED_COMMANDS | review_commands)
    for mapping in name_argument_renames.values():
        known.update(mapping)

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
        if name == "DeclareOption" and visible[_space(visible, pos):].startswith("*"):
            group = _group(visible, _space(visible, pos) + 1)
            # Standard catch-all forwarding relays the main source's options;
            # it does not author a second/inherited availability declaration.
            if group and re.fullmatch(
                    r"\s*\\PassOptionsToClass\s*\{\s*\\CurrentOption\s*\}\s*\{[A-Za-z0-9_./-]+\}\s*",
                    visible[group[0]:group[1]]):
                current_option_forwarders.add(_space(visible, group[0]))
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
                # These APIs construct csnames, whose literal spaces disappear.
                if (value in known or "".join(value.split()) in review_commands
                        or "\\" in value or "#" in value):
                    issue(token.start, "named control-sequence reference requires review")
        if name in REFERENCE_OPERANDS:
            cursor = _space(visible, pos)
            for operand_index in range(REFERENCE_OPERANDS[name]):
                if visible[cursor:cursor + 1] == "=":
                    cursor = _space(visible, cursor + 1)
                operand = token_at.get(cursor)
                end = operand.end if operand else cursor + 1
                if operand:
                    reference_tokens.add(operand.start)
                    if name in {"let", "futurelet"} and operand_index == 0:
                        mutation_targets[token.start] = {operand.name}
                    elif name == "newif":
                        mutation_targets[token.start] = {operand.name}
                        if operand.name.startswith("if"):
                            mutation_targets[token.start].update(
                                operand.name[2:] + value for value in ("true", "false"))
                unsafe.append((cursor, end))
                cursor = _space(visible, end)
            if name in {"let", "newif", "string", "meaning", "show"}:
                complete_invocations[token.start] = cursor
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
                mutation_targets[token.start] = {target.name}
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
                complete_invocations[token.start] = body[1] + 1
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
                if group:
                    environment = visible[group[0]:group[1]].strip()
                    # Environment definitions create BOTH controls, including
                    # names that collide with our trusted direct command arities.
                    mutation_targets[token.start] = {environment, "end" + environment}
                    if environment in {"document", "song", "verse"}:
                        mutation_targets[token.start].add("begin")
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
                complete_invocations[token.start] = cursor
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
        "chordson", "noteson", "notesoff", "beatson", "beatsoff", "measureson", "measuresoff",
        "translationon", "translationoff",
    } | set(boolean_setters) | {"measurestrue", "measuresfalse"}
    zero_argument.update(command_renames[name] for name in tuple(zero_argument)
                         if name in command_renames)
    predicates = {name for name in (*command_renames, *command_renames.values())
                   if name.startswith("if")}
    direct_arities = {name: 1 for name in DISPLAY_SETTERS | {"documentclass", "beginsong"}}
    direct_arities["ulLocalShow"] = 2
    direct_arities["ulMeasures"] = 1
    direct_arities.update({"songcolumns": 1, "ulSongColumns": 1,
                           "LoadClass": 1, "LoadClassWithOptions": 1, "PassOptionsToClass": 2,
                           "ExecuteOptions": 1})

    def direct_arity(token: Token) -> int | None:
        if token.name in {"begin", "end"}:
            group = _group(visible, token.end)
            env = visible[group[0]:group[1]].strip() if group else ""
            if env in {"document", "song", "verse"}:
                return 2 if token.name == "begin" and env == "song" else 1
        return direct_arities.get(token.name)

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
        arity = direct_arity(token)
        if arity is not None:
            # Setters/classes consume one mandatory value, not later standalone
            # groups. Setter arity must agree across a boolean naming edit.
            complete = True
            for _ in range(arity):
                group = _group(visible, cursor)
                if group:
                    unsafe.append(group)
                    cursor = group[1] + 1
                else:
                    complete = False
            if complete and token.name in {"documentclass", "LoadClass", "LoadClassWithOptions"}:
                # The kernel consumes a trailing release date too. Its tokens
                # are argument data, never independent document/song boundaries.
                date = _group(visible, cursor, "[", "]")
                if date:
                    unsafe.append(date)
                    literal_regions.append(date)
                    cursor = date[1] + 1
                elif visible[_space(visible, cursor):].startswith("["):
                    unsafe.append((_space(visible, cursor), len(text)))
                    complete = False
            # Column counts are expanded numeric expressions, not inert storage:
            # visible macros (including Lua) can change later consumers/helpers.
            if token.name in {"songcolumns", "ulSongColumns"} and "\\" in visible[token.end:cursor]:
                complete = False
            if complete:
                complete_invocations[token.start] = cursor
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
            if "\\" in visible[title[0]:title[1]]:
                complete_invocations.pop(token.start, None)
            continue
        option = _group(visible, cursor, "[", "]")
        if option is None:
            issue(cursor, "malformed song metadata option list requires review")
            continue
        song_metadata_regions.append(option)
        if "\\" not in visible[title[0]:option[1]]:
            complete_invocations[token.start] = option[1] + 1
        else:
            # Printed title/attribution macros may execute or schedule code.
            # Their arities/effects are not a safe boundary for later rewrites.
            complete_invocations.pop(token.start, None)
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

    # Naming permits selected executable/delayed bodies; frozen display setters
    # do not. Inspect original tokens without interpreting hooks or TeX branches.
    display_unsafe = [*unsafe, *safe_bodies, *definition_bodies, *literal_regions, *song_metadata_regions]
    for token in tokens:
        if token.name in zero_argument or token.name.startswith("if") or token.name in URL_COMMANDS - {"href"}:
            continue
        cursor = _space(visible, token.end)
        if visible[cursor:cursor + 1] == "*":
            cursor += 1
        # No fixed arity for unknown APIs: a fourth argument is just as ambiguous.
        remaining = direct_arity(token)
        while remaining is None or remaining > 0:
            cursor = _space(visible, cursor)
            group = (_group(visible, cursor, "[", "]") if visible[cursor:cursor + 1] == "["
                     else _group(visible, cursor))
            if group is None:
                if visible[cursor:cursor + 1] in {"{", "["}:
                    display_unsafe.append((cursor, len(text)))
                break
            display_unsafe.append(group)
            cursor = group[1] + 1
            if remaining is not None:
                remaining -= 1
    for previous, token in zip(tokens, tokens[1:], strict=False):
        if (token.name in display_commands and _space(visible, previous.end) == token.start
                and previous.name not in zero_argument | predicates
                and previous.start not in reference_tokens):
            display_unsafe.append((token.start, token.end))
    # A group after intervening data is not provably standalone: numbered
    # writes, token-register assignments and delimited macro arguments store it.
    # Include control-delimited groups, but never interpret referenced delimiters.
    token_ends = {token.end: token for token in tokens}
    invocation_ends = set(complete_invocations.values())
    groups: list[tuple[int, bool]] = []
    grouped_classes: set[int] = set()
    prefixed_classes: set[int] = set()
    prefixed_semantics: set[int] = set()
    unbalanced_groups = False
    cursor = 0
    last = -1
    while cursor < len(visible):
        token = token_at.get(cursor)
        if token and token.name in scope_commands | LEGACY_IDENTITY_COMMANDS:
            previous = token_ends.get(last + 1)
            if (last >= 0 and visible[last] not in "{}"
                    and last + 1 not in invocation_ends and not (previous and previous.name in zero_argument)):
                prefixed_semantics.add(token.start)
        if token and token.name == "documentclass":
            if groups or unbalanced_groups:
                grouped_classes.add(token.start)
            previous = token_ends.get(last + 1)
            if (last >= 0 and visible[last] not in "{}"
                    and not (previous and previous.name in zero_argument)):
                prefixed_classes.add(token.start)
        opening = visible[cursor] == "{" or (token and token.name in {"begingroup", "bgroup"})
        closing = visible[cursor] == "}" or (token and token.name in {"endgroup", "egroup"})
        if not token or token.start not in reference_tokens:
            if opening:
                previous = token_ends.get(last + 1)
                ambiguous = (last >= 0 and visible[last] not in "{}"
                             and not (previous and previous.name in zero_argument))
                groups.append((token.end if token else cursor + 1, ambiguous))
            elif closing and groups:
                start, ambiguous = groups.pop()
                if ambiguous:
                    display_unsafe.append((start, cursor))
            elif closing:
                unbalanced_groups = True
        if token:
            cursor = token.end
            last = cursor - 1
        else:
            if not visible[cursor].isspace():
                last = cursor
            cursor += 1
    display_unsafe.extend((start, len(text)) for start, _ in groups)
    display_reviews: set[int] = set()
    execution_zero_arguments = zero_argument | predicates | {"iftrue", "iffalse"}
    # Mutations also fence inserted destinations, even when their invocations
    # are deliberately NOT trusted as inert input/execution boundaries.
    # Include every complete-invocation parser, not a second partial name list.
    assumed_commands = (execution_zero_arguments | set(direct_arities) | DEFINITIONS | DOCUMENT_DEFINITIONS
                        | {token.name for token in tokens if token.start in complete_invocations}
                        | set(REFERENCE_OPERANDS)
                         | {"begin", "end", "newenvironment", "renewenvironment", "provideenvironment", "ulIfVariant"})
    # Lexical argument storage and a proved execution boundary are different.
    # Class/forwarding macros can expand arguments; ExecuteOptions dispatches
    # named handlers even for a literal list. Do not interpret those effects.
    execution_invocations = {
        start: end for start, end in complete_invocations.items()
        if token_at[start].name != "ExecuteOptions"
        and not (token_at[start].name in AVAILABILITY_COMMANDS and "\\" in visible[token_at[start].end:end])
    }
    direct_positions = _direct_execution_positions(
        visible, tokens, execution_zero_arguments, execution_invocations,
        {pos for pos, names in mutation_targets.items() if names & assumed_commands})
    semantic_edits: dict[int, tuple[int, str]] = {}
    body = False
    local_body = False
    body_contexts: set[str] = set()
    conditional_depth = 0
    ambiguous_branch = False
    option_dispatch = False
    class_count = 0
    direct_classes: list[tuple[Token, bool | None]] = []
    identity_starts: set[int] = set()
    for token in tokens:
        blocked = token.start in reference_tokens or any(a <= token.start < b for a, b in display_unsafe)
        proved = token.start in direct_positions
        direct_class = False
        if token.name == "documentclass":
            class_count += 1
            if (blocked or body or conditional_depth or ambiguous_branch
                    or token.start in grouped_classes | prefixed_classes):
                issue(token.start, "source availability requires review; documentclass must be a direct "
                      "top-level preamble invocation, not grouped, conditional, delayed or referenced; "
                       "no automatic replacement")
            else:
                direct_class = True
            if class_count > 1:
                issue(token.start, "source availability requires review; multiple documentclass declarations; "
                      "no automatic replacement")
        if (token.name in AVAILABILITY_COMMANDS
                and token.start not in current_option_forwarders):
            has_variants = _review_source_availability(text, visible, token, issue)
            if token.name == "documentclass":
                direct_classes.append((token, has_variants if direct_class and proved else None))
        if token.name in scope_commands:
            literal = True
            group = None
            setter, value = BOOLEAN_SETTERS.get(token.name, (token.name, ""))
            if token.name in MEASURE_SETTERS:
                setter, value = "ulShowMeasures", MEASURE_SETTERS[token.name]
            if token.name in DISPLAY_SETTERS | {"ulMeasures"}:
                group = _group(visible, token.end)
                # Comments can disappear, but macro expansion/whitespace trimming
                # must not manufacture the literal boolean the runtime requires.
                value = re.sub(r"%[^\n]*(?:\n|$)", "", text[group[0]:group[1]]) if group else ""
                literal = value in {"true", "false"}
            if (proved and not blocked and local_body and not conditional_depth and not ambiguous_branch and literal
                    and token.start not in prefixed_semantics):
                # Only a direct literal invocation after a proved body start.
                # Rename the command alone for current calls, keeping comments
                # and the literal boolean group byte-for-byte in the argument.
                end = token.end
                replacement = "\\ulLocalShow{" + DISPLAY_FEATURES[setter] + "}"
                if group is None:
                    replacement += "{" + value + "}"
                semantic_edits[token.start] = (end, replacement)
            elif token.name in display_commands and (blocked or body or conditional_depth or ambiguous_branch or not literal):
                display_reviews.add(token.start)
            elif option_dispatch and token.name in display_commands - DISPLAY_SETTERS:
                # An option handler can start the document without a direct
                # source marker. A legacy boolean must not become book policy
                # on an unproved preamble-phase assumption. Current bytes stay.
                display_reviews.add(token.start)
        if (proved and token.name in IDENTITY_PREDICATES and local_body and not blocked
                and not conditional_depth and not ambiguous_branch and token.start not in prefixed_semantics):
            identity_starts.add(token.start)
        if blocked:
            continue
        if token.name == "ExecuteOptions":
            option_dispatch = True
        if token.name.startswith("if"):
            conditional_depth += 1
        elif token.name == "fi":
            if conditional_depth:
                conditional_depth -= 1
            else:
                ambiguous_branch = True
        elif token.name in {"else", "or"} and not conditional_depth:
            ambiguous_branch = True
        # In source fragments, song/verse boundaries also establish body scope.
        # Never reset at an end marker, or let a delayed/reference marker set it.
        if token.name in {"begin", "end", "document", "enddocument", "beginsong", "endsong",
                          "beginverse", "endverse", "beginchorus", "endchorus", "chorus",
                          "beginsongs", "endsongs", "ulSongs", "endulSongs"}:
            body = True
        if proved and not conditional_depth and not ambiguous_branch:
            environment = _group(visible, token.end) if token.name in {"begin", "end"} else None
            env = visible[environment[0]:environment[1]].strip() if environment else ""
            start = {"document": "document", "beginsong": "song", "beginverse": "verse"}.get(token.name)
            end = {"enddocument": "document", "endsong": "song", "endverse": "verse"}.get(token.name)
            if token.name == "begin" and env in {"document", "song", "verse"}:
                start = env
            elif token.name == "end" and env in {"document", "song", "verse"}:
                end = env
            if start:
                body_contexts.add(start)
            if end:
                body_contexts.discard(end)
                if end == "document":
                    body_contexts.clear()
            local_body = bool(body_contexts)

    _plan_source_availability(plan, visible, markers, direct_classes)
    if not conditional_depth and not ambiguous_branch:
        semantic_edits.update(_identity_pagination_edits(text, tokens, identity_starts))

    for token in tokens:
        name = token.name
        if name in REMOVED_SPACING_COMMANDS:
            if any(a <= token.start < b for a, b in (*literal_regions, *song_metadata_regions)):
                continue
            issue(token.start, f"removed spacing API \\{name} requires review; choose "
                  "\\ulVerseBaseline, \\ulVerseSeparation, \\ulVerseMinimumGap or "
                  "\\ulVerseSpacingScale according to intent; no automatic spacing conversion")
        # Still collect naming proposals/counts below; only finalization may apply them.
        if token.start in display_reviews:
            issue(token.start, f"display setter \\{name} requires review; only direct literal preamble "
                  "settings or proved body-local requests are safe; distinguish book permission from scoped requests, references "
                  "and delayed execution; no automatic local replacement")
        if name == "chordsoff":
            issue(token.start, "legacy broad \\chordsoff requires review; chord-only suppression may expose "
                  "pitches or beats and change measures/layout; review independent feature intent and "
                  "scope; no automatic replacement")
        if name in LEGACY_IDENTITY_COMMANDS and token.start not in semantic_edits:
            issue(token.start, f"legacy variant identity \\{name} requires review; distinguish "
                  "immutable \\ulIfVariant tests from effective feature guards and remove mutable type state")
        if name in REMOVED_MEASURE_COMMANDS and token.start not in semantic_edits:
            issue(token.start, f"removed measure API \\{name} requires review; choose preamble "
                  "\\ulShowMeasures, scoped \\ulLocalShow{measures} or effective \\ifulShowMeasures "
                  "according to intent; no automatic replacement")
        if name in URL_COMMANDS and any(a <= token.start < b for a, b in expanded_bodies):
            issue(token.start, "URL in an expansion-time body requires review")
        if (name in {"makeatletter", "makeatother", "ExplSyntaxOn", "ExplSyntaxOff"}
                and any(a <= token.start < b for a, b in (*definition_bodies, *literal_regions))):
            issue(token.start, "tokenization switch in a stored/delayed argument requires review")
        if name in REMOVED_COMMANDS:
            if name in {"songrefs", "ulSongRefs"}:
                issue(token.start, f"removed song-reference accessor \\{name} requires review; "
                      "use tags= metadata or \\ulTagList; no automatic sr conversion")
            else:
                issue(token.start, f"removed no-op setting \\{name} requires review; do not map to active settings")
        elif token.start in semantic_edits:
            end, replacement = semantic_edits[token.start]
            label = "scope:" if name in scope_commands else "identity:"
            edit(token.start, end, replacement, label + name)
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
    return plan


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


def _config_key_positions(text: str) -> dict[tuple[str, ...], int]:
    """Locate keys in VALID TOML, not values, retaining original offsets/newlines.

    tomllib owns grammar and value decoding. This lexical pass only attributes
    table/dotted/inline keys; strings and comments are opaque. Arrays of tables
    need only their container position: they are not compiler profile mappings.
    """
    tokens: list[tuple[str, int]] = []
    pos = 0
    while pos < len(text):
        start, char = pos, text[pos]
        if char in " \t\r":
            pos += 1
            continue
        if char == "#":
            end = text.find("\n", pos)
            pos = len(text) if end < 0 else end
            continue
        if char in "\"'":
            delimiter = char * (3 if text.startswith(char * 3, pos) else 1)
            pos += len(delimiter)
            while pos < len(text):
                if char == '"' and text[pos] == "\\":
                    pos += 2
                elif text.startswith(delimiter, pos):
                    pos += len(delimiter)
                    if len(delimiter) == 3:
                        # TOML permits one or two literal quotes at a triple end.
                        for _ in range(2):
                            if pos < len(text) and text[pos] == char:
                                pos += 1
                    break
                else:
                    pos += 1
        elif char in "\n[]=.,{}":
            pos += 1
        else:
            while pos < len(text) and text[pos] not in " \t\r\n#\"'[]=.,{}":
                pos += 1
        tokens.append((text[start:pos], start))
    tokens.append(("\n", len(text)))
    positions: dict[tuple[str, ...], int] = {}
    index = 0

    def key(prefix: tuple[str, ...]) -> tuple[str, ...]:
        """Read a previously validated dotted key and retain each prefix anchor."""
        nonlocal index
        while True:
            raw, start = tokens[index]
            name = tomllib.loads("key = " + raw)["key"] if raw.startswith(('"', "'")) else raw
            prefix += (name,)
            positions.setdefault(prefix, start)
            index += 1
            if tokens[index][0] != ".":
                return prefix
            index += 1

    def value(prefix: tuple[str, ...]) -> None:
        """Visit inline mappings, but never attribute keys inside array values."""
        nonlocal index
        if tokens[index][0] == "{":
            index += 1
            while tokens[index][0] != "}":
                path = key(prefix)
                index += 1  # equals
                value(path)
                if tokens[index][0] == ",":
                    index += 1
            index += 1
        elif tokens[index][0] == "[":
            depth = 1
            index += 1
            while depth:
                raw = tokens[index][0]
                depth += (raw == "[") - (raw == "]")
                index += 1
        else:
            while tokens[index][0] not in {"\n", ",", "}"}:
                index += 1

    table: tuple[str, ...] = ()
    while index < len(tokens) - 1:
        if tokens[index][0] == "\n":
            index += 1
        elif tokens[index][0] == "[":
            index += 1
            array = tokens[index][0] == "["
            index += int(array)
            table = key(())
            index += 2 if array else 1
        else:
            path = key(table)
            index += 1  # equals
            value(path)
    return positions


def review_config_text(text: str) -> Result:
    """Review explicitly selected TOML without edits, path expansion or compilation.

    Check every root/profile selector before overrides. Reuse compiler profile
    resolution for inheritance/array conflicts, not build_config (which follows
    paths and creates runtime state). This is not general config validation and
    never infers selection from songbooks or converts removed category settings.
    """
    from ..config import _resolve_profile_data
    from ..variants import validate_variant_names

    plan = _EditPlan(text)
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        # Python 3.11 lacks the public position attributes added in 3.14.
        location = re.search(r"\(at line (\d+), column (\d+)\)$", str(exc))
        line = getattr(exc, "lineno", int(location[1]) if location else None)
        column = getattr(exc, "colno", int(location[2]) if location else None)
        if line is not None and column is not None:
            plan.diagnostics.append(Diagnostic(line, column, f"invalid TOML requires review: {exc}"))
        else:
            plan.issue(len(text), f"invalid TOML requires review: {exc}")
        return Result(text, diagnostics=plan.diagnostics)
    positions = _config_key_positions(text)
    normalized_positions: dict[tuple[str, ...], int] = {}

    def normalize(data: dict, path: tuple[str, ...] = (), original: tuple[str, ...] = ()) -> dict:
        """Mirror recursive compiler key normalization, preserving collision evidence."""
        output: dict = {}
        for key, value in data.items():
            name = key.replace("-", "_")
            target, source = path + (name,), original + (key,)
            pos = positions[source]
            normalized_positions.setdefault(target, pos)
            if name in output:
                plan.issue(pos, f"conflicting config keys after normalization: {name!r}; requires review")
            output[name] = normalize(value, target, source) if isinstance(value, dict) else value
        return output

    config = normalize(raw)
    profiles = config.pop("profiles", {})
    if not isinstance(profiles, dict):
        plan.issue(normalized_positions["profiles",], "compiler profiles must be a table; requires review")
        profiles = {}
    scopes = [((), config)]
    for name, data in profiles.items():
        path = ("profiles", name)
        if not isinstance(data, dict):
            plan.issue(normalized_positions[path], "compiler profile must be a table; requires review")
        else:
            scopes.append((path, data))
    removed = {"lyricbooks", "extrainstrumentbooks", "no_lyricbooks", "no_extrainstrumentbooks"}
    for path, data in scopes:
        for key in data:
            pos = normalized_positions[path + (key,)]
            if key in removed:
                plan.issue(pos, f"removed variant-category setting {key!r} requires review; inspect source "
                           "availability and choose a generic variants selector; no automatic conversion")
            elif key == "no_variants":
                plan.issue(pos, "unsafe/conflicting negated variants selector requires review; "
                           "use variants = 'all' or an explicit nonempty array, not boolean negation")
            elif key == "variants":
                value = data[key]
                try:
                    if value == "all":
                        continue
                    if not isinstance(value, list) or not value or any(
                        not isinstance(name, str) or not name or name.strip() != name or "," in name
                        for name in value
                    ):
                        raise ValueError("expected 'all' or a nonempty array of literal variant names")
                    validate_variant_names(",".join(value))
                except ValueError as exc:
                    plan.issue(pos, f"unsafe variants selector requires review: {exc}")
    if not plan.diagnostics:
        for name in profiles:
            try:
                _resolve_profile_data(profile=name, flat=config, profiles=profiles)
            except (TypeError, ValueError, RecursionError) as exc:
                path = ("profiles", name)
                anchor = path + ("merge_keys",) if "merge_keys" in profiles[name] else path + ("inherit_from",)
                plan.issue(normalized_positions.get(anchor, normalized_positions[path]),
                           f"unsafe/conflicting profile selector composition requires review: {exc}")
    return Result(text, diagnostics=plan.diagnostics)


def _tag_source(path: Path, *, kind: str = "tag") -> tuple[str, os.stat_result]:
    """Reject symlink components/unsafe leaves on explicit auxiliary reads.

    Component checks are not a descriptor-anchored sandbox against ancestor races.
    """
    # Reject symlink components as well as the leaf, including dangling links.
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError(f"symlink {kind} path requires an explicit resolved path")
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError(f"{kind} source must be a regular file")
    # Nonblocking open lets the descriptor check reject a newly substituted FIFO.
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK),
                   encoding="utf-8", newline="") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"{kind} source must be a regular file")
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


def _has_symlink_component(path: Path) -> bool:
    """Check lexical components from the root, without resolving away '..'."""
    path = path.absolute()
    return any(part.is_symlink() for part in reversed((path, *path.parents)))


def _is_engine_tree(path: Path) -> bool:
    """Recognize ULSBS source roots by layout, not basename or Git metadata.

    Copied trees are protected too. No marker content or symlink target is read.
    Explicit files or subdirectories below a root remain intentional selections.
    """
    return all(not _has_symlink_component(marker) and marker.is_file() for marker in (
        path / "pyproject.toml", path / "src/ulsbs/tools/migrate_syntax_v2.py",
        path / "src/ulsbs/assets/tex/ulsbs.sty"))


def _paths(values: Sequence[str], *, errors: list[OSError] | None = None) -> list[Path]:
    """Collect sources, retaining traversal errors separately from readable files."""
    paths: set[Path] = set()

    def onerror(error: OSError) -> None:
        # Never silently certify an incomplete scan; the CLI can still process
        # independently readable inputs before returning a review failure.
        if errors is None:
            raise error
        errors.append(error)

    for value in values:
        path = Path(value)
        if _has_symlink_component(path):
            # Keep invalid explicit inputs for per-path review in main, without
            # traversing them or preventing other safe inputs from proceeding.
            paths.add(path)
        elif path.is_file():
            if path.suffix not in SOURCE_SUFFIXES:
                raise ValueError(f"not a .tex, .cls, .sty or .sbx source: {path}")
            paths.add(path)
        elif path.is_dir():
            if _is_engine_tree(path):
                continue
            for root, dirs, files in os.walk(path, followlinks=False, onerror=onerror):
                if _has_symlink_component(Path(root)):
                    paths.add(Path(root))
                    dirs.clear()
                    continue
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS
                           and not d.startswith((".", "temp.", "tmp."))
                           and not (Path(root) / d).is_symlink()
                           and not _is_engine_tree(Path(root) / d)]
                paths.update(Path(root) / f for f in files
                             if Path(f).suffix in SOURCE_SUFFIXES
                             and not f.startswith((".", "~")) and not (Path(root) / f).is_symlink())
        else:
            raise ValueError(f"path does not exist: {path}")
    return sorted(paths)


def _atomic_write(path: Path, text: str) -> None:
    if _has_symlink_component(path):
        raise ValueError("symlink source requires an explicit resolved path")
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent,
                                         prefix="." + path.name + "-", delete=False) as stream:
            temporary = stream.name
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if _has_symlink_component(path):
            raise ValueError("symlink source requires an explicit resolved path")
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
    parser.add_argument("--config-file", metavar="FILE", action="append", default=[],
                        help="review explicit compiler TOML (repeatable; never rewritten, even with --write)")
    parser.add_argument("paths", nargs="*", metavar="PATH")
    args = parser.parse_intermixed_args(argv)
    if not args.paths and not args.tags_file and not args.config_file:
        parser.error("provide at least one PATH, --tags-file FILE or --config-file FILE")
    path_errors: list[OSError] = []
    try:
        paths = _paths(args.paths, errors=path_errors)
    except ValueError as exc:
        parser.error(str(exc))
    changed = 0
    review = len(path_errors)
    for error in path_errors:
        print(f"source traversal requires review: {error}", file=sys.stderr)
    total: Counter[str] = Counter()
    configs = list(dict.fromkeys(Path(value) for value in args.config_file))

    def config_input(path: Path) -> bool:
        """Do not let another input role rewrite a selected config or hard-link alias."""
        for config in configs:
            if path.absolute() == config.absolute():
                return True
            try:
                # Metadata comparison must include rejected config symlinks: a
                # different input role must not rewrite their target's bytes.
                if path.samefile(config):
                    return True
            except OSError:
                pass  # Each missing/unreadable input reports its own failure.
        return False

    for path in configs:
        try:
            source, _ = _tag_source(path, kind="config")
            result = review_config_text(source)
            for diagnostic in result.diagnostics:
                print(f"{path}:{diagnostic.line}:{diagnostic.column}: {diagnostic.message}", file=sys.stderr)
            review += int(not result.safe)
        except (OSError, UnicodeError, ValueError, ImportError, RecursionError) as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            review += 1
    if args.tags_file:
        path = Path(args.tags_file)
        destination = path.with_suffix(".txt")
        try:
            if config_input(path) or config_input(destination):
                raise ValueError("config review input cannot also be a tag migration source or destination")
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
            if _has_symlink_component(path):
                raise ValueError("symlink source requires an explicit resolved path")
            if not stat.S_ISREG(path.stat().st_mode):
                raise ValueError("source must be a regular file")
            if config_input(path):
                raise ValueError("config review input cannot also be a source migration input")
            # A checked regular leaf may have become a FIFO before open.
            with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK),
                           encoding="utf-8", newline="") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError("source must be a regular file")
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
    print(f"Scanned {len(paths) + len(path_errors) + bool(args.tags_file) + len(configs)} files; "
          f"{changed} would change; {review} need review.",
          file=sys.stderr)
    for name, count in sorted(total.items()):
        print(f"  {name}: {count}", file=sys.stderr)
    return int(bool(review or (args.check and changed)))


if __name__ == "__main__":
    raise SystemExit(main())
