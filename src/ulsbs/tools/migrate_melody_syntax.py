#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Safely migrate legacy ULSBS melody commands inside ``\\[ ... ]``."""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence


PITCH = re.compile(r"(?:[A-G](?:[#&])?|/)\Z")
VERBATIM_ENVS = {"verbatim", "Verbatim", "lstlisting", "minted"}
COMMANDS: dict[str, tuple[str, int]] = {
    "mn": ("primary", 1), "mnc": ("primary", 1), "mncadj": ("primary-adjusted", 2),
    "mncii": ("primary", 2), "mnciii": ("primary", 3), "mnciv": ("primary", 4),
    "mncv": ("primary", 5), "mncvi": ("primary", 6), "mnd": ("low-primary", 1),
    "ma": ("secondary-same", 1), "mac": ("secondary-same", 1),
    "mau": ("secondary-above", 1), "mauc": ("secondary-above", 1),
    "mauii": ("paired-above", 2), "mauiic": ("paired-above", 2),
    "mad": ("low-secondary", 1), "madii": ("paired-below", 2),
    "bm": ("beat", 0), "bmc": ("beat", 0), "bmadj": ("beat-adjusted", 1),
    "bmcadj": ("beat-adjusted", 1),
}


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


def _location(text: str, index: int) -> tuple[int, int]:
    return text.count("\n", 0, index) + 1, index - text.rfind("\n", 0, index)


def _skip_space_comments(text: str, pos: int) -> int:
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
        elif text[pos] == "%" and (pos == 0 or text[pos - 1] != "\\"):
            end = text.find("\n", pos)
            pos = len(text) if end == -1 else end + 1
        else:
            break
    return pos


def _balanced(text: str, pos: int, opening: str = "{", closing: str = "}") -> tuple[str, int] | None:
    if pos >= len(text) or text[pos] != opening:
        return None
    depth = 1
    start = pos + 1
    pos += 1
    while pos < len(text):
        char = text[pos]
        if char == "\\":
            pos += 2
            continue
        if char == "%":
            newline = text.find("\n", pos)
            pos = len(text) if newline == -1 else newline + 1
            continue
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if not depth:
                return text[start:pos], pos + 1
        pos += 1
    return None


def _protected_ranges(text: str) -> list[tuple[int, int]]:
    """Return comments and verbatim-like spans, which must never be rewritten."""
    ranges: list[tuple[int, int]] = []
    pos = 0
    while pos < len(text):
        if text[pos] == "%" and (pos == 0 or text[pos - 1] != "\\"):
            end = text.find("\n", pos)
            ranges.append((pos, len(text) if end == -1 else end))
            pos = len(text) if end == -1 else end + 1
            continue
        if text.startswith("\\verb", pos):
            start = pos
            pos += 5
            if pos < len(text) and text[pos] == "*":
                pos += 1
            if pos < len(text):
                delimiter = text[pos]
                end = text.find(delimiter, pos + 1)
                ranges.append((start, len(text) if end == -1 else end + 1))
                pos = len(text) if end == -1 else end + 1
                continue
        match = re.match(r"\\begin\s*\{([A-Za-z*]+)\}", text[pos:])
        if match and match.group(1) in VERBATIM_ENVS:
            start = pos
            env = match.group(1)
            end_match = re.search(r"\\end\s*\{" + re.escape(env) + r"\}", text[pos + len(match.group(0)):])
            end = len(text) if not end_match else pos + len(match.group(0)) + end_match.end()
            ranges.append((start, end))
            pos = end
            continue
        pos += 1
    return ranges


def _inside(ranges: list[tuple[int, int]], position: int) -> bool:
    return any(start <= position < end for start, end in ranges)


def _argument(text: str, pos: int) -> tuple[str, int] | None:
    return _balanced(text, _skip_space_comments(text, pos))


def _note(value: str, source: str, index: int, diagnostics: list[Diagnostic]) -> str | None:
    value = value.strip()
    if PITCH.fullmatch(value):
        return value
    line, column = _location(source, index)
    diagnostics.append(Diagnostic(line, column, f"unsupported melody marker {value!r}"))
    return None


def _migrate_alternate_chords(text: str, converted: Counter[str]) -> tuple[str, list[Diagnostic]]:
    r"""Convert legacy ``\ac<n>{Chord}`` selectors outside protected regions."""
    protected = _protected_ranges(text)
    diagnostics: list[Diagnostic] = []
    replacements: list[tuple[int, int, str]] = []
    for match in re.finditer(r"\\ac<([^<>\r\n]+)>", text):
        if _inside(protected, match.start()):
            continue
        selector = match.group(1).strip()
        if not selector.isdigit():
            line, column = _location(text, match.start())
            diagnostics.append(Diagnostic(line, column, f"unsupported \\ac selector {selector!r}"))
            continue
        pos = match.end()
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text) or text[pos] == "%":
            line, column = _location(text, match.start())
            diagnostics.append(Diagnostic(line, column, "malformed \\ac: missing chord argument"))
            continue
        if text[pos] == "{":
            argument = _balanced(text, pos)
            if argument is None:
                line, column = _location(text, match.start())
                diagnostics.append(Diagnostic(line, column, "malformed \\ac: unbalanced chord argument"))
                continue
            chord, end = argument
        else:
            # Legacy xparse accepted one unbraced token. Consume the contiguous
            # chord spelling to preserve the intent of sources such as
            # \ac<1>Em.
            end = pos
            while end < len(text) and not text[end].isspace() and text[end] not in r"\]}{%":
                end += 1
            chord = text[pos:end]
            if not chord:
                line, column = _location(text, match.start())
                diagnostics.append(Diagnostic(line, column, "malformed \\ac: unsupported unbraced chord argument"))
                continue
        replacements.append((match.start(), end, f"\\ac{{{selector}}}{{{chord}}}"))
        converted["ac"] += 1
    if diagnostics:
        return text, diagnostics
    for start, end, replacement in reversed(replacements):
        text = text[:start] + replacement + text[end:]
    return text, []


def _convert_annotation(body: str, source: str, body_start: int, allow_low: bool) -> tuple[str, Counter[str], list[Diagnostic], str | None]:
    """Convert a leading legacy layer while leaving the chord remainder intact."""
    diagnostics: list[Diagnostic] = []
    converted: Counter[str] = Counter()
    primary: list[str] = []
    secondary: list[str] = []
    sequence: list[str] = []
    offset: str | None = None
    placement: str | None = None
    pos = 0
    saw = False
    replay: list[str] = []
    while pos < len(body):
        if body[pos].isspace():
            candidate = _skip_space_comments(body, pos)
            if candidate < len(body) and (body[candidate] == "^" or body[candidate] == "\\"):
                pos = candidate
                continue
            break
        if body[pos] == "^":
            replay.append("^")
            pos += 1
            continue
        if body[pos] != "\\":
            break
        match = re.match(r"\\([A-Za-z]+)", body[pos:])
        if not match or match.group(1) not in COMMANDS:
            break
        name = match.group(1)
        kind, count = COMMANDS[name]
        command_at = body_start + pos
        end = pos + len(match.group(0))
        args: list[str] = []
        for _ in range(count):
            argument = _argument(body, end)
            if argument is None:
                line, column = _location(source, command_at)
                diagnostics.append(Diagnostic(line, column, f"malformed \\{name}: missing balanced argument"))
                return body, converted, diagnostics, None
            value, end = argument
            args.append(value)
        saw = True
        converted[name] += 1
        if kind.startswith("low-") and not allow_low:
            line, column = _location(source, command_at)
            diagnostics.append(Diagnostic(line, column, f"\\{name} is low-position and requires --normalize-low"))
            pos = end
            continue
        if kind in {"beat", "beat-adjusted"}:
            if kind == "beat-adjusted":
                value = args[0].strip()
                if not value:
                    line, column = _location(source, command_at)
                    diagnostics.append(Diagnostic(line, column, f"\\{name} has an empty offset"))
                elif offset is None and not sequence and not primary and not secondary:
                    offset = value
                elif offset != value:
                    line, column = _location(source, command_at)
                    diagnostics.append(Diagnostic(line, column, "incompatible offsets in one chord annotation"))
            sequence.append("*")
        elif kind == "primary-adjusted":
            value = args[0].strip()
            note = _note(args[1], source, command_at, diagnostics)
            if offset is None and not sequence and not primary and not secondary:
                offset = value
            elif offset != value:
                line, column = _location(source, command_at)
                diagnostics.append(Diagnostic(line, column, "incompatible offsets in one chord annotation"))
            if note:
                primary.append(note)
                sequence.append(note)
        elif kind == "primary" or kind == "low-primary":
            notes = [_note(arg, source, command_at, diagnostics) for arg in args]
            primary.extend(note for note in notes if note)
            sequence.extend(note for note in notes if note)
        elif kind.startswith("secondary") or kind == "low-secondary":
            note = _note(args[0], source, command_at, diagnostics)
            if note:
                secondary.append(note)
            if kind == "secondary-above":
                placement = "above"
            elif kind == "secondary-same":
                placement = "same"
        elif kind.startswith("paired"):
            alternate = _note(args[0], source, command_at, diagnostics)
            normal = _note(args[1], source, command_at, diagnostics)
            if alternate and normal:
                if primary or secondary:
                    line, column = _location(source, command_at)
                    diagnostics.append(Diagnostic(line, column, "paired command cannot be combined safely with other melody commands"))
                primary.append(normal)
                secondary.append(alternate)
                sequence.append(normal)
            placement = "above" if kind == "paired-above" else "below"
        pos = end
    remaining = body[pos:]
    # A legacy command after chord content cannot be moved into <...> without
    # changing TeX execution order. Chord macros themselves are otherwise safe.
    for later in re.finditer(r"\\([A-Za-z]+)\b", remaining):
        if later.group(1) in COMMANDS and not _inside(_protected_ranges(remaining), later.start()):
            command_at = body_start + pos + later.start()
            line, column = _location(source, command_at)
            diagnostics.append(
                Diagnostic(line, column, f"\\{later.group(1)} follows chord content and cannot be hoisted")
            )
    if not saw:
        return body, converted, diagnostics, None
    if secondary and len(primary) > 1:
        line, column = _location(source, body_start)
        diagnostics.append(Diagnostic(line, column, "cannot infer gaps/alignment for multiple primary and secondary notes"))
    if secondary and len(secondary) > 1:
        line, column = _location(source, body_start)
        diagnostics.append(Diagnostic(line, column, "cannot infer gaps/alignment for multiple secondary notes"))
    melody = " ".join(sequence) if not secondary else f"{' '.join(sequence)};{' '.join(secondary)}"
    if not melody:
        return body, converted, diagnostics, placement
    if offset:
        melody += f" @ {offset}"
    # The melody-block syntax accepts one optional leading songs replay token:
    # \[^\mn{C}] becomes \[^<C>], retaining songs' no-track semantics.
    return "".join(replay) + f"<{melody}>" + remaining, converted, diagnostics, placement


def migrate_text(text: str, *, normalize_low: bool = False) -> Result:
    """Migrate one TeX document in memory; unsafe input returns original text."""
    original_text = text
    protected = _protected_ranges(text)
    diagnostics: list[Diagnostic] = []
    converted: Counter[str] = Counter()
    replacements: list[tuple[int, int, str, str | None]] = []
    annotation_spans: list[tuple[int, int]] = []
    pos = 0
    while pos < len(text):
        start = text.find("\\[", pos)
        if start == -1:
            break
        pos = start + 2
        if _inside(protected, start):
            continue
        annotation = _balanced(text, start + 1, "[", "]")
        if annotation is None:
            line, column = _location(text, start)
            diagnostics.append(Diagnostic(line, column, "malformed chord annotation: missing ]"))
            annotation_spans.append((start, len(text)))
            continue
        body, end = annotation
        annotation_spans.append((start, end))
        converted_body, counts, issues, placement = _convert_annotation(
            body, text, start + 2, normalize_low
        )
        converted.update(counts)
        diagnostics.extend(issues)
        if converted_body != body:
            replacements.append((start + 2, end - 1, converted_body, placement))
        pos = end
    # Legacy commands outside a chord annotation are never safe to rewrite.
    for match in re.finditer(r"\\([A-Za-z]+)", text):
        if match.group(1) in COMMANDS and not _inside(protected, match.start()):
            if not _inside(annotation_spans, match.start()):
                line, column = _location(text, match.start())
                diagnostics.append(Diagnostic(line, column, f"\\{match.group(1)} outside a chord annotation"))
    if diagnostics:
        return Result(text, converted, diagnostics)
    # Placement is scoped to a uniform verse where possible. A non-uniform
    # same-position run is enclosed in an explicit local TeX group instead.
    scoped_placements = [item for item in replacements if item[3] in {"below", "same"}]
    insertions: list[tuple[int, str]] = []
    for start, annotation_end, _, policy in scoped_placements:
        begin = list(re.finditer(r"\\(?:mn)?beginverse\*?(?:\s*\[[^]]*\])?", text[:start]))
        verse_ends = list(re.finditer(r"\\endverse\b", text[:start]))
        if not begin or len(begin) <= len(verse_ends):
            if policy == "same":
                insertions.extend(
                    [(start - 2, "{\\melodySecondaryPosition{same}"), (annotation_end + 1, "}")]
                )
                continue
            line, column = _location(text, start)
            diagnostics.append(Diagnostic(line, column, "secondary-below has no safe verse scope"))
            continue
        scope = begin[-1]
        close = re.search(r"\\endverse\b", text[start:])
        if close is None:
            if policy == "same":
                insertions.extend(
                    [(start - 2, "{\\melodySecondaryPosition{same}"), (annotation_end + 1, "}")]
                )
                continue
            line, column = _location(text, start)
            diagnostics.append(Diagnostic(line, column, "secondary-below verse is not closed"))
            continue
        scope_end = start + close.start()
        placements = [placement for item_start, _, _, placement in replacements if scope.end() <= item_start < scope_end]
        if any(placement not in {None, policy} for placement in placements):
            if policy == "same":
                insertions.extend(
                    [(start - 2, "{\\melodySecondaryPosition{same}"), (annotation_end + 1, "}")]
                )
                continue
            line, column = _location(text, start)
            diagnostics.append(Diagnostic(line, column, "mixed secondary placement has no safe verse scope"))
            continue
        insertion = (scope.end(), f"\n\\melodySecondaryPosition{{{policy}}}")
        if insertion not in insertions:
            insertions.append(insertion)
    if diagnostics:
        return Result(text, converted, diagnostics)
    # Style switches are unambiguous, but comments and verbatim remain opaque.
    for match in re.finditer(r"\\usealtmnstyle(true|false)\b", text):
        if not _inside(protected, match.start()):
            mapping = "swapped" if match.group(1) == "true" else "normal"
            replacements.append((match.start(), match.end(), f"\\melodyStyleMapping{{{mapping}}}", None))
    replacements.extend((position, position, value, None) for position, value in insertions)
    for start, end, replacement, _ in sorted(replacements, key=lambda item: item[:2], reverse=True):
        text = text[:start] + replacement + text[end:]
    text, ac_diagnostics = _migrate_alternate_chords(text, converted)
    if ac_diagnostics:
        return Result(original_text, converted, ac_diagnostics)
    return Result(text, converted, [])


def _paths(values: Iterable[str]) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        path = Path(value)
        if path.is_file():
            paths.append(path)
        elif path.is_dir():
            paths.extend(candidate for candidate in path.rglob("*.tex") if candidate.is_file())
        else:
            raise FileNotFoundError(path)
    return sorted(set(paths))


def _diagnostic_category(message: str) -> str:
    if "low-position" in message:
        return "low-position review required"
    if "follows chord content" in message:
        return "legacy command after chord content"
    if "outside a chord annotation" in message:
        return "outside chord annotation"
    if "unsupported melody marker" in message:
        return "unsupported melody marker"
    if "offset" in message:
        return "offset conflict"
    if "placement" in message or "verse scope" in message:
        return "unsafe secondary placement"
    if "malformed" in message or "missing balanced" in message:
        return "malformed TeX construct"
    return "other review required"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="scan without changing files")
    mode.add_argument("--diff", action="store_true", help="show validated unified diffs")
    mode.add_argument("--write", action="store_true", help="write validated conversions")
    parser.add_argument("--normalize-low", action="store_true", help="permit normalizing low mnd/mad forms")
    parser.add_argument("paths", nargs="+", metavar="PATH")
    args = parser.parse_args(argv)
    try:
        paths = _paths(args.paths)
    except FileNotFoundError as exc:
        parser.error(f"path does not exist: {exc}")
    total = Counter[str]()
    review = Counter[str]()
    failures = False
    changed = 0
    unsafe_files = 0
    for path in paths:
        source = path.read_text(encoding="utf-8")
        result = migrate_text(source, normalize_low=args.normalize_low)
        total.update(result.converted)
        for issue in result.diagnostics:
            print(f"{path}:{issue.line}:{issue.column}: {issue.message}", file=sys.stderr)
            review[_diagnostic_category(issue.message)] += 1
        if result.diagnostics:
            failures = True
            unsafe_files += 1
            continue
        if source != result.text:
            changed += 1
            if args.diff:
                sys.stdout.writelines(difflib.unified_diff(source.splitlines(True), result.text.splitlines(True), fromfile=str(path), tofile=str(path)))
            elif args.write:
                path.write_text(result.text, encoding="utf-8")
    print(f"Scanned {len(paths)} files; {changed} would change; {unsafe_files} need review.", file=sys.stderr)
    for name, count in sorted(total.items()):
        print(f"  \\{name}: {count}", file=sys.stderr)
    if review:
        print("Needs review:", file=sys.stderr)
        for category, count in sorted(review.items()):
            print(f"  {category}: {count}", file=sys.stderr)
    return 1 if failures or (args.check and any(total.values())) else 0


if __name__ == "__main__":
    raise SystemExit(main())
