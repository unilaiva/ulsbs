# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Standalone, record-based compiler warning parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class Diagnostic:
    source: str
    category: str
    message: str
    log_path: Path | None = None
    occurrences: int = 1
    affected_count: int | None = None


_TEX_HEADER = re.compile(
    r"^(?:LaTeX(?: Font)? Warning\b|(?:Package|Class) \S+ Warning\b|"
    r"(?:pdfTeX|LuaTeX|LuaHBTeX|XeTeX|TeX|dvipdfmx|Fontconfig) warning\b|"
    r"warning\s+\([^\n)]+\)\s*:|"
    r"Missing character:|Overfull \\[hv]box\b)", re.IGNORECASE,
)
_CONTINUATION = re.compile(r"^\((?:[^()\s]+)\)\s+")
_REF_RECAP = re.compile(r"\bThere were undefined (?:references|citations)\b", re.IGNORECASE)
_FONT_RECAP = re.compile(
    r"\bSome font shapes were not available,? defaults substituted\b", re.IGNORECASE,
)


def _category(message: str) -> str:
    if re.search(r"\bbarcheck\b", message, re.I):
        return "barcheck"
    if re.search(r"missing character:|missing[- ]glyph|no glyph|glyph .+ (?:missing|not found)", message, re.I):
        return "missing-glyph"
    if re.search(r"\bfont\b|\bfonts\b|font shapes?", message, re.I):
        return "fonts"
    if re.search(r"\b(?:references?|citations?|labels?|hyperreferences?)\b", message, re.I):
        return "references"
    if re.search(r"Overfull \\[hv]box|\b(?:layout|page break|line break)\b", message, re.I):
        return "layout"
    if re.match(r"(?:Package|Class) \S+ Warning\b", message, re.I):
        return "package"
    return "other"


def _continues(raw: str, previous: str, source: str) -> bool:
    line = raw.strip()
    return bool(line and (
        _CONTINUATION.match(line)
        or (raw[:1].isspace() and not line.startswith(("[", "[]", "!")))
        or (source == "TeX" and len(previous) >= 70
            and not previous.rstrip().endswith((".", "!", "?")))
    ) and not re.match(r"(?:Underfull|Overfull) \\[hv]box|(?:warning|error|info):", line, re.I))


def strip_tex_warnings(text: str) -> str:
    """Remove TeX warning records from error excerpts, preserving actual errors.

    Warning reporting uses only the last engine invocation; an arbitrary step's
    error log may instead contain a preflight or otherwise superseded run.
    """
    output, skipping, previous = [], False, ""
    for raw in text.splitlines(keepends=True):
        if _TEX_HEADER.match(raw.strip()):
            skipping = True
        elif not (skipping and _continues(raw, previous, "TeX")):
            skipping = False
            output.append(raw)
        previous = raw.rstrip("\r\n")
    return "".join(output)


def parse_tool_warnings(
    text: str, source: str, log_path: Path | None = None,
) -> tuple[Diagnostic, ...]:
    """Parse warnings in encounter order, grouping identical normalized records.

    Underfull boxes are informational. Closing TeX recaps are omitted only
    when their specific warning records are present in this same text.
    ``affected_count`` is reserved for callers with artifact-level knowledge.
    """
    name = source.casefold()
    if name in {"tex", "latex", "pdflatex", "lualatex", "xelatex", "pdftex", "luatex", "xetex"}:
        source = "TeX"
    elif name == "lilypond":
        source = "LilyPond"

    # A location must contain a line number, so a filename containing "warning"
    # is not mistaken for a diagnostic header.
    aliases = {
        "Audio": ("ulsbs-midi2audio", "fluidsynth", "ffmpeg"),
        "Images": ("pdftoppm", "magick", "convert"),
        "Index": ("songidx", "texlua"),
        "ConTeXt": ("context", "contextjit"),
    }
    prefix = "|".join(re.escape(name) for name in (source, *aliases.get(source, ())))
    generic_header = re.compile(
        rf"^(?:(?:{prefix})(?:\s+\([^\n]*\))?\s*:\s*|"
        rf"(?:{prefix})\s+|[^\n]+:\d+(?::\d+)?:\s*)?warning\s*:",
        re.IGNORECASE,
    )
    records: list[str] = []
    parts: list[str] = []
    previous = ""
    for raw in text.splitlines():
        line = raw.strip()
        header = generic_header.match(line) or (source == "TeX" and _TEX_HEADER.match(line))
        if header:
            if parts:
                records.append(" ".join(parts))
            parts = [line]
        elif parts and _continues(raw, previous, source):
            parts.append(_CONTINUATION.sub("", line))
        else:
            if parts:
                records.append(" ".join(parts))
            parts = []
        previous = raw
    if parts:
        records.append(" ".join(parts))

    records = [re.sub(r"\s+", " ", record).strip() for record in records]
    specific_refs = any(
        re.search(r"\b(?:Reference|Citation|Hyper reference)\b.+\bundefined\b", record, re.I)
        and not _REF_RECAP.search(record) for record in records
    )
    specific_fonts = any(
        re.search(r"\bFont shape\b.+\bundefined\b", record, re.I)
        and not _FONT_RECAP.search(record) for record in records
    )
    grouped: dict[str, Diagnostic] = {}
    for record in records:
        if source == "LilyPond":
            body = re.split(r"\bwarning\s*:\s*", record, maxsplit=1, flags=re.I)[-1]
            if body == "Unable to auto-detect default settings":
                continue
        if source == "TeX" and (
            (specific_refs and _REF_RECAP.search(record))
            or (specific_fonts and _FONT_RECAP.search(record))
        ):
            continue
        if record in grouped:
            old = grouped[record]
            grouped[record] = replace(old, occurrences=old.occurrences + 1)
        else:
            grouped[record] = Diagnostic(source, _category(record), record, log_path)
    return tuple(grouped.values())
