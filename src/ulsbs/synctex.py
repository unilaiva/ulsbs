# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Map SyncTeX positions from generated TeX back to editable sources.

When SyncTeX is enabled, the lilypond-book wrapper records the source
path and line for each line of preprocessed TeX. After the final LuaLaTeX
pass, this module uses that map to publish a SyncTeX v1 sidecar beside the
ordinary PDF. It accounts for the compiler's injected preamble, translates
project paths for use outside the build environment, and updates the SyncTeX
byte offsets without changing PDF coordinates.

Copied TeX lines retain their original locations. Generated snippet expansions
can point to the opening line of the snippet, but rendered LilyPond notes and
generated score fragments are not mapped individually. If source mapping is
unavailable, the compiler can still publish the PDF without a sidecar.

This file is part of the 'ulsbs' package.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import tempfile
import zlib
from bisect import bisect_right
from pathlib import Path

MAP_NAME = ".ulsbs-synctex-sources.json"


def track_lilypond_sources(state, active, inputs, destination: Path) -> None:
    """Observe LilyPond 2.24/2.26's resolved inputs and actual output chunks.

    Keep the upstream writer and its output unchanged. If its private hooks
    change, absence of the map disables synchronization, not compilation.
    """
    try:
        note_input = state["note_input_file"]
        write_documents = state["write_output_documents"]
        write_file = state["write_if_updated"]
        types = state["book_snippets"]
        plain, include = types.Substring, types.IncludeSnippet
    except (KeyError, AttributeError):
        return

    def record_input(name, *args, **kwargs):
        if active:
            inputs[active[-1]] = os.path.abspath(name)
        return note_input(name, *args, **kwargs)

    def record_documents(chunks, is_filter):
        if is_filter:
            return write_documents(chunks, is_filter)
        by_path = {}
        maps = {}
        try:
            for chunk in chunks:
                by_path.setdefault(chunk.output_fullpath(), []).append(chunk)
        except (AttributeError, TypeError):
            return write_documents(chunks, is_filter)

        def record_file(name, pieces):
            write_file(name, pieces)
            try:
                lines = _chunk_lines(by_path[name], pieces, plain, include)
                maps[os.path.abspath(name)] = [inputs[os.path.abspath(name)], lines]
            except (AttributeError, KeyError, TypeError, ValueError):
                return

        state["write_if_updated"] = record_file
        try:
            write_documents(chunks, is_filter)
        finally:
            state["write_if_updated"] = write_file
        try:
            destination.write_text(json.dumps(maps), encoding="utf-8")
        except OSError:
            pass

    state["note_input_file"] = record_input
    state["write_output_documents"] = record_documents


def _chunk_lines(chunks, pieces, plain, include) -> list[int]:
    """Return one source line per emitted physical line, using chunk offsets."""
    lines = [0]
    quality = -1
    source = None
    for chunk, text in zip(chunks, pieces, strict=True):
        if isinstance(chunk, plain):
            current, start, end = chunk.source, chunk.start, chunk.end
        else:
            current = chunk.match.string
            start, end = chunk.match.span("match")
        if current is not source:
            source = current
            newlines = [m.end() for m in re.finditer("\n", source)]
        original = source[start:end]
        line = bisect_right(newlines, start) + 1
        exact = text == original or (isinstance(chunk, include)
                                     and text.count("\n") == original.count("\n"))
        # The LaTeX formatter may insert a graphics import before begin-document.
        inserted = set()
        if not exact and isinstance(chunk, plain):
            marker = r"\begin{document}"
            graphics = "\\usepackage{graphics}\n"
            if text != original.replace(marker, graphics + marker):
                raise ValueError("unexpected plain-text transformation by lilypond-book")
            inserted = {original.count("\n", 0, m.start()) + n
                        for n, m in enumerate(re.finditer(re.escape(marker), original))}
            exact = True
        if not text:
            continue
        fragments = text.split("\n")
        for i, fragment in enumerate(fragments):
            last = i == len(fragments) - 1
            if last and not fragment:
                break
            # On a line shared by adjacent chunks, prefer real source text to
            # a LilyPond replacement or whitespace from the preceding chunk.
            rank = (2 if exact and i not in inserted else 0) + bool(fragment.strip())
            if rank > quality:
                lines[-1] = line
                quality = rank
            if not last:
                lines.append(0)
                quality = -1
            if exact and i not in inserted:
                line += 1
    if lines[-1] == 0:
        lines.pop()
    return lines


_INPUT = re.compile(rb"Input:([0-9]+):(.*)\n")
_POSITION = re.compile(rb"[\[(vhxkg$r?]([0-9]+),(-?[0-9]+)(?=[:,])")


def publish_sidecar(raw: Path, destination: Path, *, compile_dir: Path,
                    staged_main: Path, original_main: Path, project_root: Path,
                    host_root: Path) -> None:
    """Write a SyncTeX v1 gzip sidecar, changing only inputs, lines and anchors."""
    map_file = compile_dir / "_lp-source" / MAP_NAME
    recorded = json.loads(map_file.read_text(encoding="utf-8"))
    if not recorded:
        raise ValueError("lilypond-book did not record source mappings")
    real_compile_dir = compile_dir.resolve()
    lp_output = real_compile_dir / "_lp"
    maps = {}
    source = original_main.read_text(encoding="utf-8")
    staged_main = staged_main.resolve()
    for output, (input_path, lines) in recorded.items():
        relative_output = Path(output).resolve().relative_to(lp_output)
        authored = Path(input_path)
        if authored == staged_main:
            staged = authored.read_text(encoding="utf-8")
            if not staged.endswith(source):
                raise ValueError("staged main file does not match its source")
            prefix = staged[:len(staged) - len(source)].count("\n")
            authored = original_main
            lines = [max(0, line - prefix) for line in lines]
        # Kpathsea can spell a path using the project temp symlink even when
        # the process's actual working directory is the target of that link.
        maps[compile_dir / relative_output] = (authored, lines)
        maps[real_compile_dir / relative_output] = (authored, lines)
    if not any(path == original_main for path, _ in maps.values()):
        raise ValueError("no mapping for the main source")

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as target:
            temporary = Path(target.name)
            with (gzip.open(raw, "rb") as incoming,
                  gzip.GzipFile(fileobj=target, mode="wb", filename="", mtime=0) as outgoing):
                _rewrite(incoming, outgoing, maps, compile_dir, original_main, project_root,
                         host_root)
        os.replace(temporary, destination)
    except zlib.error as error:
        raise ValueError("invalid compressed SyncTeX data") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _rewrite(incoming, outgoing, maps, compile_dir, original_main, project_root, host_root):
    header = incoming.readline()
    if header != b"SyncTeX Version:1\n":
        raise ValueError("unsupported SyncTeX format")

    # Reopened inputs get multiple tags. The SyncTeX scanner searches only one
    # tag per filename, so coalesce them, including declarations between pages.
    names = {}
    tags = {}
    mapped_main = False
    for line in incoming:
        if not (match := _INPUT.fullmatch(line)):
            continue
        tag, name = match.groups()
        path = Path(os.path.abspath(compile_dir / os.fsdecode(name)))
        authored, lines = maps.get(path, (path, None))
        mapped_main |= authored == original_main and lines is not None
        if authored.is_relative_to(project_root):
            relative = authored.relative_to(project_root)
            # Native Windows host paths aren't absolute inside a Linux container.
            name = os.fsencode(host_root / relative if host_root.is_absolute()
                               else "../" + relative.as_posix())
        else:
            name = os.fsencode(authored)
        if b"\n" in name or b"\r" in name:
            raise ValueError("a source path contains a newline")
        tags[tag] = (names.setdefault(name, tag), name, lines)
    if not mapped_main:
        raise ValueError("SyncTeX does not reference the mapped main source")

    incoming.seek(len(header))
    outgoing.write(header)
    previous = distance = len(header)
    for line in incoming:
        original_size = len(line)
        if line.startswith(b"!"):
            if line != f"!{previous}\n".encode("ascii"):
                raise ValueError("invalid SyncTeX anchor")
            line = f"!{distance}\n".encode("ascii")
            previous = distance = 0
        elif match := _INPUT.fullmatch(line):
            tag = match[1]
            canonical, name, _ = tags[tag]
            line = b"Input:" + tag + b":" + name + b"\n" if canonical == tag else b""
        elif (match := _POSITION.match(line)) and match[1] in tags:
            canonical, _, values = tags[match[1]]
            number = int(match[2])
            if values is not None and number > 0:
                number = values[number - 1] if number <= len(values) else 0
            line = line[:1] + canonical + b"," + str(number).encode("ascii") + line[match.end(2):]
        outgoing.write(line)
        previous += original_size
        distance += len(line)
