# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""ulsbs-bookmeta

CLI helper to:

- dump song/chapter metadata as JSON
- check song id coverage/validity
- interactively create/fix song ids in source files
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
import re
import secrets
import signal
import string
import sys
from pathlib import Path
from typing import Iterable, List

# Test for python version before importing any package modules.
REQUIRED = (3, 11)
if sys.version_info < REQUIRED:
    sys.stderr.write(
        "This script requires Python {}.{}+, but you are running {}.{}.{}\n".format(
            REQUIRED[0], REQUIRED[1], *sys.version_info[:3]
        )
    )
    raise SystemExit(1)


from ..constants import CONTENT_DIRNAME, INCLUDE_DIRNAME  # noqa: E402 (must test Python version first)
from ..songdb import SongInfo, build_song_database  # noqa: E402 (must test Python version first)
from ..ui import UI  # noqa: E402 (must test Python version first)
from ..util import slugify  # noqa: E402 (must test Python version first)


_ID_RE = re.compile(r"^[a-z0-9-]+$")


def _is_valid_song_id(value: str) -> bool:
    return _ID_RE.fullmatch(value) is not None


def _random_id_suffix(length: int = 6) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _flatten_songs_in_order(db) -> list[SongInfo]:
    songs = list(db.songs_without_chapter)
    for chap in db.chapters:
        songs.extend(chap.songs)
    return songs


def _song_location_key(song: SongInfo) -> tuple[str, int, int] | None:
    """Return a key identifying a specific \beginsong definition in a file."""

    if (
        song.source_file_absolute is None
        or song.beginsong_start is None
        or song.beginsong_header_end is None
    ):
        return None

    # Use resolved path string for stable dict keys
    return (
        str(song.source_file_absolute.expanduser().resolve()),
        int(song.beginsong_start),
        int(song.beginsong_header_end),
    )


def _deduplicate_songs_by_location(songs: list[SongInfo]) -> list[SongInfo]:
    """Remove duplicate SongInfo entries that point to the same source location."""

    out: list[SongInfo] = []
    seen: set[tuple[str, int, int]] = set()
    for s in songs:
        k = _song_location_key(s)
        if k is None:
            out.append(s)
            continue
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return out


def _parse_texinputs_env() -> List[Path]:
    """Return directories from the TEXINPUTS environment variable."""

    raw = os.environ.get("TEXINPUTS")
    if not raw:
        return []

    dirs: List[Path] = []
    for part in raw.split(":"):
        part = part.strip()
        if not part:
            continue
        if part.endswith("//"):
            part = part[:-2] or "."
        dirs.append(Path(part).expanduser().resolve())
    return dirs


def _normalise_include_dirs(main_tex: Path, include_dirs: Iterable[str] | None) -> List[Path]:
    """Build the include search path list."""

    main_dir = main_tex.parent.resolve()
    cwd = Path.cwd().resolve()
    dirs: List[Path] = [main_dir]

    cli_dirs: List[Path] = []
    if include_dirs:
        for d in include_dirs:
            if d:
                cli_dirs.append(Path(d).expanduser().resolve())

    auto_dirs: List[Path] = [
        (main_dir / CONTENT_DIRNAME).resolve(),
        (main_dir / INCLUDE_DIRNAME).resolve(),
        (cwd / CONTENT_DIRNAME).resolve(),
        (cwd / INCLUDE_DIRNAME).resolve(),
    ]

    env_dirs = _parse_texinputs_env()

    seen = {main_dir}
    for group in (cli_dirs, auto_dirs, env_dirs):
        for p in group:
            if p not in seen:
                dirs.append(p)
                seen.add(p)

    return dirs


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ulsbs-bookmeta",
        description=(
            "Parse a songbook main TeX file and either output JSON metadata, "
            "check song ids, or interactively create/fix song ids. "
            "Follows \\input / \\include using MAIN_TEX's directory, any -I paths, "
            f"'{CONTENT_DIRNAME}' / '{INCLUDE_DIRNAME}' subdirectories under MAIN_TEX and the current working "
            "directory, and TEXINPUTS."
        ),
    )

    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--json", action="store_true", help="Output SongbookData as JSON")
    mode.add_argument(
        "--check-song-ids",
        action="store_true",
        help="List songs with missing ids and malformed ids, and print a summary",
    )
    mode.add_argument(
        "--create-song-ids",
        action="store_true",
        help="Interactively create/fix song ids in TeX source files",
    )

    p.add_argument(
        "main_tex",
        metavar="MAIN_TEX",
        help="Main songbook TeX file (typically the same one you'd pass to ulsbs-compile)",
    )
    p.add_argument(
        "-I",
        "--include-dir",
        action="append",
        dest="include_dirs",
        default=None,
        help=(
            "Additional directory to search for \\input / \\include files. "
            "Can be given multiple times. Searched after MAIN_TEX's directory but before "
            f"automatic '{CONTENT_DIRNAME}' / '{INCLUDE_DIRNAME}' subdirectories and TEXINPUTS."
        ),
    )

    p.add_argument(
        "-o",
        "--output",
        type=Path,
        help="(json mode only) Write JSON to this file instead of stdout.",
    )

    p.add_argument(
        "--include-plain-lowercase-lyrics",
        action="store_true",
        default=False,
        help=(
            "(json mode only) Include lowercased plain-text lyrics and translations in the JSON output "
            "(lyrics_plain_lowercase fields). Increases JSON size."
        ),
    )

    p.add_argument(
        "--psv",
        type=Path,
        default=None,
        help=(
            "(json mode only) Path to a .ulsbs.psv file containing ID/number/page overrides. "
            "If omitted, uses '<MAIN_TEX_STEM>.ulsbs.psv' from MAIN_TEX's directory if it exists."
        ),
    )

    return p


def _parse_braced_argument(src: str, start: int) -> tuple[str, int]:
    if start >= len(src) or src[start] != "{":
        raise ValueError("Expected '{'")
    depth = 0
    i = start
    out: list[str] = []
    while i < len(src):
        ch = src[i]
        if ch == "{":
            if depth > 0:
                out.append(ch)
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return "".join(out), i + 1
            out.append(ch)
        else:
            out.append(ch)
        i += 1
    raise ValueError("Unterminated '{'")


def _parse_optional_bracket_argument(src: str, start: int) -> tuple[str | None, int]:
    if start >= len(src) or src[start] != "[":
        return None, start
    depth = 0
    i = start
    out: list[str] = []
    while i < len(src):
        ch = src[i]
        if ch == "[":
            if depth > 0:
                out.append(ch)
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return "".join(out), i + 1
            out.append(ch)
        else:
            out.append(ch)
        i += 1
    raise ValueError("Unterminated '['")


def _parse_keyval_options_ordered(raw: str) -> list[tuple[str, str]]:
    """Parse a beginsong key=val option string, preserving order."""

    items: list[tuple[str, str]] = []
    i = 0
    n = len(raw)
    while i < n:
        while i < n and raw[i] in " \t\r\n,":
            i += 1
        if i >= n:
            break

        key_start = i
        while i < n and re.match(r"[A-Za-z0-9_*]", raw[i]):
            i += 1
        key = raw[key_start:i].strip()
        if not key:
            while i < n and raw[i] != ",":
                i += 1
            continue

        while i < n and raw[i].isspace():
            i += 1

        if i >= n or raw[i] != "=":
            items.append((key, ""))
            continue
        i += 1

        while i < n and raw[i].isspace():
            i += 1

        if i < n and raw[i] == "{":
            val, i = _parse_braced_argument(raw, i)
        else:
            val_start = i
            while i < n and raw[i] != ",":
                i += 1
            val = raw[val_start:i].strip()

        items.append((key, val))

    return items


def _format_keyval_options(items: list[tuple[str, str]]) -> str:
    parts: list[str] = []
    for key, val in items:
        if val == "":
            parts.append(key)
        else:
            parts.append(f"{key}={{{val}}}")
    return ",".join(parts)


def _rewrite_beginsong_header(old_header: str, *, new_id: str) -> str:
    """Rewrite a '\\beginsong{..}[..]' header to ensure id={new_id} is first."""

    if not old_header.startswith("\\beginsong"):
        raise ValueError("Expected header to start with \\\\beginsong")

    i = len("\\beginsong")
    while i < len(old_header) and old_header[i].isspace():
        i += 1

    if i >= len(old_header) or old_header[i] != "{":
        raise ValueError("Malformed \\\beginsong: missing {title}")

    _title, i_after_title = _parse_braced_argument(old_header, i)

    j = i_after_title
    while j < len(old_header) and old_header[j].isspace():
        j += 1

    opts_raw: str | None = None
    opts_start = j
    opts_end = j

    if j < len(old_header) and old_header[j] == "[":
        opts_raw, opts_end = _parse_optional_bracket_argument(old_header, j)

    prefix = old_header[:i_after_title]
    between = old_header[i_after_title:opts_start]
    after = old_header[opts_end:]

    opts_items: list[tuple[str, str]] = []
    if opts_raw is not None:
        opts_items = _parse_keyval_options_ordered(opts_raw)
        opts_items = [(k, v) for (k, v) in opts_items if k != "id"]

    new_items = [("id", new_id), *opts_items]
    new_opts = _format_keyval_options(new_items)
    return prefix + between + f"[{new_opts}]" + after


@dataclass(frozen=True)
class _PlannedChange:
    path: Path
    line: int | None
    start: int
    end: int
    old_header: str
    new_header: str


def _plan_id_fixes(songs: list[SongInfo]) -> list[_PlannedChange]:
    changes: list[_PlannedChange] = []

    # If the same song definition is encountered multiple times (same file and
    # same beginsong span), only plan a single change for it.
    planned_locations: set[tuple[str, int, int]] = set()

    for song in songs:
        missing = song.id is None
        malformed = song.id is not None and not _is_valid_song_id(song.id)
        if not (missing or malformed):
            continue

        loc_key = _song_location_key(song)
        if loc_key is None:
            raise RuntimeError(
                f"Song '{song.title}' is missing internal source location info; rebuild db with updated ulsbs"
            )
        if loc_key in planned_locations:
            continue
        planned_locations.add(loc_key)

        # Create new id
        title_for_slug = song.title if song.title else ""
        base = slugify(title_for_slug, default="unknown")
        new_id = f"{base}-{_random_id_suffix(6)}"

        src = song.source_file_absolute.read_text(encoding="utf-8", errors="replace")
        old_header = src[song.beginsong_start : song.beginsong_header_end]
        new_header = _rewrite_beginsong_header(old_header, new_id=new_id)

        changes.append(
            _PlannedChange(
                path=song.source_file_absolute,
                line=song.beginsong_line,
                start=song.beginsong_start,
                end=song.beginsong_header_end,
                old_header=old_header,
                new_header=new_header,
            )
        )

    return changes


def _apply_changes(changes: list[_PlannedChange]) -> None:
    """Apply changes transactionally (best-effort).

    If interrupted (Ctrl-C / KeyboardInterrupt) while writing, attempts to
    restore any files already written back to their original contents.
    """

    by_file: dict[Path, list[_PlannedChange]] = {}
    for ch in changes:
        by_file.setdefault(ch.path, []).append(ch)

    # Pre-compute new contents for all files first.
    original_by_file: dict[Path, str] = {}
    new_by_file: dict[Path, str] = {}

    for path, items in by_file.items():
        original = path.read_text(encoding="utf-8", errors="replace")
        txt = original

        # Apply from bottom to top so indices remain valid
        items_sorted = sorted(items, key=lambda c: c.start, reverse=True)
        for ch in items_sorted:
            if txt[ch.start : ch.end] != ch.old_header:
                raise RuntimeError(
                    f"Refusing to apply change: file content changed unexpectedly: {path}"
                )
            txt = txt[: ch.start] + ch.new_header + txt[ch.end :]

        original_by_file[path] = original
        new_by_file[path] = txt

    written: list[Path] = []
    try:
        for path in sorted(new_by_file.keys(), key=lambda p: str(p)):
            path.write_text(new_by_file[path], encoding="utf-8")
            written.append(path)
    except KeyboardInterrupt:
        # Prevent nested Ctrl-C while restoring.
        old_handler = signal.getsignal(signal.SIGINT)
        try:
            signal.signal(signal.SIGINT, signal.SIG_IGN)
        except Exception:
            old_handler = None

        try:
            for path in reversed(written):
                try:
                    path.write_text(original_by_file[path], encoding="utf-8")
                except Exception:
                    # Best-effort rollback.
                    pass
        finally:
            if old_handler is not None:
                try:
                    signal.signal(signal.SIGINT, old_handler)
                except Exception:
                    pass
        raise


def _run_json_mode(ns, db) -> int:
    if ns.output:
        db.to_json_file(ns.output)
    else:
        sys.stdout.write(db.to_json())
    return 0


def _run_check_mode(ui: UI, db) -> int:
    songs = _deduplicate_songs_by_location(_flatten_songs_in_order(db))

    missing: list[SongInfo] = []
    bad: list[SongInfo] = []

    for s in songs:
        if s.id is None:
            missing.append(s)
        elif not _is_valid_song_id(s.id):
            bad.append(s)

    for s in missing:
        loc = f"{s.source_file_relative}:{s.beginsong_line or '?'}"
        title = ui.colorize(repr(s.title), ui.C_WHITE)
        ui.line(ui.colorize("NO ID:   ", ui.C_YELLOW), f"{title} ({loc})")

    for s in bad:
        loc = f"{s.source_file_relative}:{s.beginsong_line or '?'}"
        title = ui.colorize(repr(s.title), ui.C_WHITE)
        ui.line(ui.colorize("BAD ID:  ", ui.C_RED), f"{s.id!r} for {title} ({loc})")

    ui.plain("")
    if missing:
      ui.warning_line(f"{len(missing)} missing ids")
    if bad:
      ui.error_line(f"{len(bad)} malformed ids")

    return 1 if (missing or bad) else 0


def _run_create_mode(ui: UI, db) -> int:
    songs = _deduplicate_songs_by_location(_flatten_songs_in_order(db))
    changes = _plan_id_fixes(songs)

    if not changes:
        ui.info_line("No missing/malformed ids found; nothing to do.")
        return 0

    for ch in changes:
        loc = f"{ch.path}:{ch.line or '?'}"
        ui.line(ui.colorize('FILE: ', ui.C_WHITE), loc)
        ui.line(ui.colorize('OLD:  ', ui.C_BROWN), ch.old_header.strip())

        new_header_display = ch.new_header.strip()
        m = re.search(r"id=\{([^}]*)\}", new_header_display)
        if m:
            token = f"id={{{m.group(1)}}}"
            new_header_display = new_header_display.replace(
                token,
                ui.colorize(token, ui.C_YELLOW),
                1,
            )

        ui.line(ui.colorize('NEW:  ', ui.C_LBLUE), new_header_display)
        ui.plain("")

    print(f"Apply these {len(changes)} changes? [y/N]: ", end="", flush=True)
    try:
        resp = input("").strip().lower()
    except KeyboardInterrupt:
        ui.plain("")
        ui.abort_line("Aborted; no files were modified.")
        return 130
    if resp not in ("y", "Y", "yes"):
        ui.plain("")
        ui.abort_line("Aborted; no files were modified.")
        return 0

    _apply_changes(changes)
    ui.plain("")
    ui.success_line(f"Applied {len(changes)} change(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    ns = parser.parse_args(argv)

    ui = UI(use_colors=True)

    try:
        main_tex = Path(ns.main_tex).expanduser().resolve()
        if not main_tex.exists():
            raise FileNotFoundError(f"File not found: {ns.main_tex}")
        if not main_tex.is_file():
            raise RuntimeError(f"Not a regular file: {ns.main_tex}")

        if (ns.check_song_ids or ns.create_song_ids) and ns.output:
            raise RuntimeError("--output is only valid in --json mode")

        include_dirs = _normalise_include_dirs(main_tex, ns.include_dirs)

        # Decide which (optional) .ulsbs.psv file to use.
        # PSV is only applied in --json mode.
        psv_file: Path | None = None
        if ns.json:
            if ns.psv is not None:
                psv_file = ns.psv.expanduser().resolve()
            else:
                default_psv = (main_tex.parent / f"{main_tex.stem}.ulsbs.psv").resolve()
                if default_psv.is_file():
                    psv_file = default_psv
        else:
            if ns.psv is not None:
                ui.warning_line("Note: --psv is ignored unless --json is used")

        try:
            db = build_song_database(
                processed_tex=main_tex,
                include_search_paths=include_dirs,
                plain_lowercase_lyrics=(ns.include_plain_lowercase_lyrics if ns.json else False),
                ulsbs_psv_file=psv_file,
            )
        except Exception as e:
            extra = f" (psv: {psv_file})" if psv_file is not None else ""
            ui.error_line(f"Failed to build song database{extra}: {e}")
            return 1

        if ns.json:
            # JSON output must remain uncolored.
            return _run_json_mode(ns, db)
        if ns.check_song_ids:
            return _run_check_mode(ui, db)
        if ns.create_song_ids:
            return _run_create_mode(ui, db)

        raise RuntimeError("No mode selected")

    except KeyboardInterrupt:
        ui.plain("")
        ui.abort_line("Aborted; no files were modified.")
        return 130
    except Exception as e:
        ui.error_line(str(e))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
