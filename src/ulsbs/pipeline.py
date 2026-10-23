# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Compilation, output publication, and bounded parallel job orchestration.

Ordinary and MULTIKEY editions compile independently. Ordinary jobs publish
their outputs immediately; MULTIKEY jobs retain an optimized private master.
The coordinator schedules range packaging in the same pool only after both
matching compilations succeed, including ordinary media and JSON exports.
Compilation completion alone therefore does not imply MULTIKEY job success.

This file is part of the 'ulsbs' package.
"""

from __future__ import annotations

import concurrent.futures as cf
import importlib.util
import json
import os
import re
import shlex
import shutil
import signal
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import List
from fnmatch import fnmatch

from .config import Config
from .constants import (
    LUALATEX_MAX_EXTRA_PASSES,
    PAPERA5_FNAMEPART,
    RESULT_TYPE_MAIN_PDF,
    RESULT_TYPE_MULTIKEY_PDF,
    RESULT_TYPE_MULTIKEY_JSON,
    RESULT_TYPE_PRINTOUT_PDF,
    RESULT_TYPE_JSON,
    RESULT_TYPE_IMAGE,
    RESULT_TYPE_MIDIDIR,
    RESULT_TYPE_AUDIODIR,
    RESULT_PRINTOUT_SUBDIRNAME,
    RESULT_MULTIKEY_SUBDIRNAME,
    RESULT_JSON_SUBDIRNAME,
    RESULTLIST_SEPARATOR,
    RESULT_IMAGE_SUBDIRNAME,
    RESULT_MIDI_SUBDIRNAME,
    RESULT_AUDIO_SUBDIRNAME,
    SONG_IDX_SCRIPT_REL,
    SORT_LOCALE,
    COVERIMAGE_MODIFIED_FNAME_POSTFIX,
    SELECTION_FNAME_PREFIX,
    TEMP_DIRNAME,
    CONTENT_DIRNAME,
    INCLUDE_DIRNAME,
    TAG_DEFINITION_FILENAME,
    GENAUDIO_ALBUMTITLE,
    JSON_INCLUDE_PLAIN_LOWERCASE_LYRICS,
)
from .engine_assets import EngineAssets
from .jobs import Job, build_job_basename
from .lock import JobLock
from .songdb import build_song_database, SongbookData
import ulsbs.resultlist as resultlist
from .ui import UI
from .util import (
    ensure_dir,
    ensure_symlink,
    read_text,
    run_cmd,
    safe_rm_tree,
    overlay_tree,
    which,
    write_text,
    append_text,
    regex_documentclass_ulsbs_songbook,
    current_time_human_readable,
    deduplicate_paths_preserve_order,
)

# The subdirectory name into which asset subdirs 'assets/{tex, ly, img}' from
# ulsbs package will be copied under in each job's directory. The subdirs are
# added to TeX/Ly include paths as appropriate.
_JOB_ULSBS_ASSETS_DIRNAME = "ulsbs-assets"

# Placeholder strings found in some files to be replaced when compiling:
_LP_EXTRAINSTR_PLACEHOLDER = "ULSBS-PLACEHOLDER-FOR-EXTRA-INSTRUMENT-VARIANT-CODE"
_PRINTOUT_INPUT_FILE_PLACEHOLDER = "ULSBS-PLACEHOLDER-FOR-INPUT-FILE-PDF"

# Check after the source has loaded its class/style, without executing an
# undefined private conditional (generic classes need not define it at all).
MULTIKEY_DISABLED_FALLBACK_TEX = r"""\AtBeginDocument{%
  \begingroup
  \expandafter\ifx\csname ifUL@pdflayers\endcsname\iftrue
  \else
    \AddToHook{enddocument/afterlastpage}{\directlua{
      ulsbs_multikey = ulsbs_multikey or dofile(assert(kpse.find_file("ulsbs-multikey.lua", "tex")))
      ulsbs_multikey.finish_disabled()
    }}%
  \fi
  \endgroup
}
"""

ABORT_EVENT = threading.Event()


class CompileError(RuntimeError):
    """Error during a compile step; may carry a path to a log file."""

    def __init__(self, message: str, log_path: Path | None = None) -> None:
        """Store the compile error message and optional diagnostic log path."""
        super().__init__(message)
        self.log_path = log_path


# Result containers for parallel runs

@dataclass(frozen=True)
class CompilationResult:
    """Compiler warnings and the next per-job log number for a later phase.

    This immutable handoff carries no PDF objects or manifest payload. A
    MULTIKEY result still needs packaging; it is not a final ``JobSuccess``.
    """

    warning_count: int
    next_step: int


@dataclass(frozen=True)
class JobSuccess:
    """Final job outcome: ordinary publication or completed MULTIKEY packaging.

    An explicitly layer-disabled source is also a completed, skipped companion
    with a warning. Each job's warning count contributes to the run total once.
    """

    job: Job
    warning_count: int


@dataclass(frozen=True)
class JobFailure:
    """One reported failure per job, including a failed ordinary dependency."""

    job: Job
    reason: str


@dataclass
class ParallelRunResult:
    """Final named outcomes; warnings count successful jobs only."""

    successes: List[JobSuccess]
    failures: List[JobFailure]
    total_warnings: int = 0


def die_log(ui: UI, cfg: Config, job: Job, cwd: Path, message: str, log_path: Path | None) -> None:
    """
    Show an error and tail a log (if any), then raise CompileError.
    Intended to be called when a step fails within a job.
    """
    if ABORT_EVENT.is_set():
        # Quiet abort: no log spam
        raise KeyboardInterrupt()

    # While printing multi-line error/log output, temporarily suspend
    # the spinner so that its status line does not get redrawn onto our
    # blank separator lines.
    try:
        ui.suspend_spinner()
    except Exception:
        # Never let spinner issues interfere with error reporting.
        pass

    try:
        txt_doc = ui.fmt_doc(job)
        ui.error_line(f"{txt_doc} {message}")
        if log_path is not None:
            try:
                rel = cwd.relative_to(cfg.runtime.project_paths.project_root)
                ui.see_line(f"{ui.C_YELLOW}{rel}/{log_path.name}{ui.C_RESET}")
            except Exception:
                pass
            if cfg.max_log_lines > 0:
                ui.plain("")
                ui.space_line(
                    ui.colorize(f"Displaying the last {cfg.max_log_lines} lines of log:", ui.C_YELLOW)
                )
                ui.plain("")
                try:
                    from collections import deque

                    with log_path.open("r", encoding="utf-8", errors="replace") as f:
                        tail = deque(f, maxlen=cfg.max_log_lines)
                    ui.space_line("".join(tail))
                    ui.plain("")
                except Exception:
                    ui.warning("(Could not read log)")
        else:
            ui.warning("(No log file available)")
    finally:
        try:
            ui.resume_spinner()
        except Exception:
            pass

    raise CompileError(message, log_path)


def require_tools(*, multikey: bool = False) -> None:
    """Fail early with installation guidance for missing build dependencies.

    qpdf is optional for ordinary builds. When ``multikey`` is true, also check
    its minimum version; semantic qualification still happens for every range.
    """
    for t in ("lualatex", "texlua", "lilypond-book"):
        if which(t) is None:
            raise SystemExit(f"'{t}' binary not found in PATH")
    if importlib.util.find_spec("pikepdf") is None:
        raise SystemExit(
            "Python dependency 'pikepdf' is required for PDF font deduplication. "
            "Install it with pip install 'pikepdf>=8' (or apt install python3-pikepdf), "
            "or rebuild the compiler container."
        )
    if multikey:
        from .multikey_ranges import qpdf_version

        try:
            qpdf_version()
        except (OSError, ValueError) as error:
            raise SystemExit(f"qpdf is required for MULTIKEY range packaging: {error}") from error


def build_include_paths(cfg: Config, job: Job) -> tuple[dict[str, str], list[str], list[Path]]:
    """Construct include paths for the job.

    Returns a triple of:
      - env: environment variables with TEXINPUTS/LUAINPUTS configured
      - lp_args: LilyPond -I arguments as a flat list of strings
      - db_include_paths: search paths for the internal song database builder

    TeX/LuaTeX search order (used for TEXINPUTS/LUAINPUTS):

      1)  job.compile_dir / CONTENT_DIRNAME / "img"
      2)  job.compile_dir / CONTENT_DIRNAME
      3)  job.compile_dir / INCLUDE_DIRNAME / "img"
      4)  job.compile_dir / INCLUDE_DIRNAME
      5)  job.compile_dir / _JOB_ULSBS_ASSETS_DIRNAME / "tex"
      6)  job.compile_dir / _JOB_ULSBS_ASSETS_DIRNAME / "ly"
      7)  job.compile_dir / _JOB_ULSBS_ASSETS_DIRNAME / "img"
      8)  job.compile_dir
      9)  project_root_dir / CONTENT_DIRNAME / "img"
      10) project_root_dir / CONTENT_DIRNAME
      11) project_root_dir / INCLUDE_DIRNAME / "img"
      12) project_root_dir / INCLUDE_DIRNAME
      13) project_root_dir

    LilyPond -I search order:

      1) job.compile_dir / _JOB_ULSBS_ASSETS_DIRNAME / "tex"
      2) job.compile_dir / _JOB_ULSBS_ASSETS_DIRNAME / "ly"
      3) project_root_dir / CONTENT_DIRNAME
      4) project_root_dir / INCLUDE_DIRNAME
      5) project_root_dir

    Song database builder search order follows the Tex/LuaTeX order, but "img"
    subdirectories are removed from it.

    The resulting TEXINPUTS/LUAINPUTS values and LilyPond -I arguments are
    also written to include-paths.txt file in the compile directory for
    debugging.
    """
    env = os.environ.copy()

    project_paths = cfg.runtime.project_paths
    project_root = project_paths.project_root
    project_content = project_paths.content_dir
    project_content_img = project_paths.content_dir / "img"
    project_include = project_paths.include_dir
    project_include_img = project_paths.include_dir / "img"

    job_root = job.compile_dir
    job_ulsbs_tex = job_root / _JOB_ULSBS_ASSETS_DIRNAME / "tex"
    job_ulsbs_lp = job_root / _JOB_ULSBS_ASSETS_DIRNAME / "ly"
    job_ulsbs_img = job_root / _JOB_ULSBS_ASSETS_DIRNAME / "img"
    job_content = job_root / CONTENT_DIRNAME
    job_content_img = job_root / CONTENT_DIRNAME / "img"
    job_include = job_root / INCLUDE_DIRNAME
    job_include_img = job_root / INCLUDE_DIRNAME / "img"

    # TeX/LuaTeX search paths (dedup, order preserved)
    tex_search_paths = [
        job_content_img,
        job_content,
        job_include_img,
        job_include,
        job_ulsbs_tex,
        job_ulsbs_lp,
        job_ulsbs_img,
        job_root,
        project_content_img,
        project_content,
        project_include_img,
        project_include,
        project_root,
    ]
    tex_paths_uniq = deduplicate_paths_preserve_order(tex_search_paths)

    tex_paths_str = ":".join(str(p) for p in tex_paths_uniq)
    existing_tex = env.get("TEXINPUTS", "")
    if existing_tex:
        env["TEXINPUTS"] = f"{tex_paths_str}:{existing_tex}"
    else:
        env["TEXINPUTS"] = f"{tex_paths_str}:"

    existing_lua = env.get("LUAINPUTS", "")
    if existing_lua:
        env["LUAINPUTS"] = f"{tex_paths_str}:{existing_lua}"
    else:
        env["LUAINPUTS"] = f"{tex_paths_str}:"

    # LilyPond -I search paths (dedup, order preserved, no img)
    lp_search_paths = [
        job_ulsbs_tex,
        job_ulsbs_lp,
        project_content,
        project_include,
        project_root,
    ]
    lp_paths_uniq = deduplicate_paths_preserve_order(lp_search_paths)

    lp_args: list[str] = []
    for p in lp_paths_uniq:
        lp_args.extend(["-I", str(p)])

    # Our internal song db search paths, no img dirs (dedup, order preserved)
    db_search_paths = [
        job_content,
        job_include,
        job_ulsbs_tex,
        job_ulsbs_lp,
        job_root,
        project_content,
        project_include,
        project_root,
    ]
    db_paths_uniq = deduplicate_paths_preserve_order(db_search_paths)

    # Create 00_include-paths.log in the job dir to make include paths visible for debugging.
    lines: list[str] = []
    lines.append("# Auto-generated by ulsbs pipeline for debugging include paths.")
    lines.append(f"# Job: {job.doc_stem}:{job.variant}{':multikey' if job.multikey else ''}")
    lines.append(f"# {current_time_human_readable()}")
    lines.append("")
    if cfg.runtime.in_container:
        lines.append(f"# Paths are from within the compiler {cfg.container_engine} container.")
        lines.append("")
    lines.append("# TeX/LuaTeX search path (in order):")
    for idx, p in enumerate(tex_paths_uniq, start=1):
        lines.append(f"#   {idx}: {p}")
    lines.append("")
    lines.append(f"TEXINPUTS={env['TEXINPUTS']}")
    lines.append(f"LUAINPUTS={env['LUAINPUTS']}")
    lines.append("")
    lines.append("# LilyPond include arguments (in order):")
    lp_cmd_preview = "lilypond " + " ".join(shlex.quote(a) for a in lp_args)
    lines.append(f"#   {lp_cmd_preview}")
    for idx, p in enumerate(lp_paths_uniq, start=1):
        lines.append(f"#   {idx}: -I {p}")
    lines.append("")
    lines.append("# Internal Song db builder search path (in order):")
    for idx, p in enumerate(db_paths_uniq, start=1):
        lines.append(f"#   {idx}: {p}")
    lines.append("")

    try:
        write_text(job_root / "00_include-paths.log", "\n".join(lines) + "\n")
    except Exception:
        # Debug aid only; ignore failures.
        pass

    return env, lp_args, db_paths_uniq


def _midi_audio_enabled(cfg: Config, job: Job) -> tuple[bool, bool]:
    """Return effective MIDI/audio export flags, disabling both for multikey jobs."""
    if job.multikey:
        return False, False
    optional = job.variant != "default"
    # Optional opt-ins permit exports; they must not re-enable a global --no-*.
    return (
        cfg.midifiles and (not optional or cfg.midifiles_allow_for_optional_variants),
        cfg.audiofiles and (not optional or cfg.audiofiles_allow_for_optional_variants),
    )


def prepare_compile_dir(ui: UI, assets: EngineAssets, cfg: Config, job: Job) -> None:
    """Create job workdir and populate engine assets and stable aliases.
    """
    ensure_dir(job.compile_dir / _JOB_ULSBS_ASSETS_DIRNAME)

    # tex tree from ulsbs (copied, because variants modify some files)
    ensure_dir(job.compile_dir / _JOB_ULSBS_ASSETS_DIRNAME / "tex")
    with assets.tex_dir() as src_tex:
        shutil.copytree(
            src_tex, job.compile_dir / _JOB_ULSBS_ASSETS_DIRNAME / "tex", dirs_exist_ok=True
        )

    # ly tree from ulsbs (copied, because variants modify some files)
    ensure_dir(job.compile_dir / _JOB_ULSBS_ASSETS_DIRNAME / "ly")
    with assets.ly_dir() as src_ly:
        shutil.copytree(
            src_ly, job.compile_dir / _JOB_ULSBS_ASSETS_DIRNAME / "ly", dirs_exist_ok=True
        )

    # img tree from ulsbs (copied, because variants modify some files)
    ensure_dir(job.compile_dir / _JOB_ULSBS_ASSETS_DIRNAME / "img")
    with assets.img_dir() as src_img:
        shutil.copytree(
            src_img, job.compile_dir / _JOB_ULSBS_ASSETS_DIRNAME / "img", dirs_exist_ok=True
        )

    # Aliases
    ensure_symlink(
        job.compile_dir / "ulsbs" / "assets",
        job.compile_dir / _JOB_ULSBS_ASSETS_DIRNAME,
        fallback_copy=True,
    )
    ensure_symlink(
        job.compile_dir / "ulsbs" / "src" / "ulsbs" / "assets",
        job.compile_dir / _JOB_ULSBS_ASSETS_DIRNAME,
        fallback_copy=True,
    )

    # Audio needs intermediate MIDI even with --no-midi. Suppress only the MIDI
    # score when no optional media output needs it, not LilyPond processing.
    if job.multikey or (job.variant != "default" and not any(_midi_audio_enabled(cfg, job))):
        midi_include = job.compile_dir / _JOB_ULSBS_ASSETS_DIRNAME / "ly" / "ulsbs-internal-score-midi.ly"
        write_text(midi_include, "% MIDI generation is disabled for this edition.\n")


def make_variant_tex(job: Job, cfg: Config) -> Path:
    """Create variant .tex with pre-load configuration and variant post-setup."""
    src = job.doc_tex_abs
    layers = cfg.multikey_books and job.multikey and job.variant != "lyrics"
    layers_value = "true" if layers else "false"
    txt = (
        f"\\newcommand{{\\ulPdfTranspositionLayers}}{{{layers_value}}}\n"
        f"\\newcommand{{\\ulPdfTranspositionLayerUI}}{{{cfg.multikey_layer_ui}}}\n"
        f"\\newcommand{{\\ulPdfTranspositionRequireSongIDs}}{{{'true' if cfg.multikey_require_song_ids else 'false'}}}\n"
        f"\\newcommand{{\\ulPdfTranspositionMinimumScale}}{{{cfg.multikey_min_chordname_scale}}}\n"
        f"\\newcommand{{\\ulMultikeyLilypondScores}}{{{'true' if layers and cfg.multikey_lilypond_scores else 'false'}}}\n"
        + (r"\providecommand{\ulScoreSystem}[3]{\includegraphics{#3}}" + "\n"
           if layers and cfg.multikey_lilypond_scores else "")
        + (MULTIKEY_DISABLED_FALLBACK_TEX if layers else "")
        + read_text(src)
    )
    suffix = src.suffix if job.variant == "default" else ".tex"
    out_path = job.compile_dir / (build_job_basename(job) + suffix)

    if job.variant == "default":
        write_text(out_path, txt)
        return out_path

    if job.variant == "lyrics":
        docclass_re = regex_documentclass_ulsbs_songbook()
        injected = docclass_re.sub(
            lambda m: m.group(0) + "\n\\input{ulsbs-internal-lyricbook-postsetup.tex}",
            txt,
            count=1,
        )
        write_text(out_path, injected)
        return out_path

    if job.variant == "charango":
        docclass_re = regex_documentclass_ulsbs_songbook()
        injected = docclass_re.sub(
            lambda m: m.group(0) + "\n\\input{ulsbs-internal-charangobook-postsetup.tex}",
            txt,
            count=1,
        )
        write_text(out_path, injected)

        head = job.compile_dir / _JOB_ULSBS_ASSETS_DIRNAME / "ly" / "ulsbs-internal-common-head.ly"
        if head.exists():
            head_txt = read_text(head)
            if (
                _LP_EXTRAINSTR_PLACEHOLDER in head_txt
                and "ul-chosen-tuning = #ul-charango-tuning" not in head_txt
            ):
                lines = head_txt.splitlines(keepends=True)
                for idx, line in enumerate(lines):
                    if _LP_EXTRAINSTR_PLACEHOLDER in line:
                        lines.insert(idx + 1, "ul-chosen-tuning = #ul-charango-tuning\n")
                        break
                head_txt = "".join(lines)
            write_text(head, head_txt)
        return out_path

    if job.variant == "bassclef":
        docclass_re = regex_documentclass_ulsbs_songbook()
        injected = docclass_re.sub(
            lambda m: m.group(0) + "\n\\input{ulsbs-internal-bassclefbook-postsetup.tex}",
            txt,
            count=1,
        )
        write_text(out_path, injected)

        for f in (job.compile_dir / _JOB_ULSBS_ASSETS_DIRNAME / "ly").glob(
            "ulsbs-include-tail*_bassclef.ly"
        ):
            newname = f.name.replace("_bassclef", "")
            shutil.copy2(f, job.compile_dir / _JOB_ULSBS_ASSETS_DIRNAME / "ly" / newname)
        return out_path

    raise SystemExit(f"Unknown variant: {job.variant}")


def step_lilypond_book(
    ui: UI,
    job: Job,
    input_tex: Path,
    env: dict[str, str],
    lp_include_args: list[str],
    step: int,
) -> tuple[Path, Path, int]:
    """
    Process original sources, never a previous build's generated TeX imports.
    A private launcher prevents upstream concatenation of repeated imports.

    Returns:
      - Path to the processed .tex in the job root (after overlay-moving _lp)
      - Path to the lilypond-book log
      - Next step number
    """
    txt_doc = ui.fmt_doc(job)
    lp_out = job.compile_dir / "_lp"
    safe_rm_tree(lp_out)
    ensure_dir(lp_out)

    log_path = job.compile_dir / f"{step:02d}_lilypond.log"
    ui.exec_line(f"{txt_doc} {ui.fmt_step(step)} lilypond-book")

    # Generated imports in the job root/content/include shadow real sources on
    # warm builds. Keep job-local engine assets, but resolve imports from source.
    source_env = env.copy()
    generated_paths = {str(job.compile_dir / part) for part in (
        "", CONTENT_DIRNAME, f"{CONTENT_DIRNAME}/img", INCLUDE_DIRNAME, f"{INCLUDE_DIRNAME}/img",
    )}
    # Preserve explicit engine aliases without re-exposing generated song TeX.
    source_aliases = job.compile_dir / "_lp-source"
    safe_rm_tree(source_aliases)
    ensure_dir(source_aliases)
    source_input = source_aliases / input_tex.name
    shutil.copy2(input_tex, source_input)
    for name in ("ulsbs", _JOB_ULSBS_ASSETS_DIRNAME):
        target = job.compile_dir / name
        if target.is_dir():
            ensure_symlink(source_aliases / name, target, fallback_copy=True)
    for variable in ("TEXINPUTS", "LUAINPUTS"):
        source_env[variable] = ":".join([
            str(source_aliases),
            *(part for part in source_env.get(variable, "").split(":") if part not in generated_paths),
        ])

    process_cmd = shlex.join(["lilypond", *lp_include_args, "-I", str(source_aliases), "-dno-point-and-click"])
    args = [
        sys.executable,
        str(Path(__file__).with_name("lilypond_book.py")),
        "-f",
        "latex",
        "--latex-program=lualatex",
        "--pdf",
        f"--process={process_cmd}",
        *lp_include_args,
        "--output",
        str(lp_out),
        str(source_input.resolve()),
    ]

    try:
        run_cmd(args, cwd=source_aliases, stdout_path=log_path,
                stderr_to_stdout=True, check=True, env=source_env)
    except Exception:
        if ABORT_EVENT.is_set():
            raise KeyboardInterrupt() from None
        raise CompileError("lilypond-book failed", log_path) from None

    # lilypond-book produces a processed TeX file into lp_out, typically with the same basename
    produced = lp_out / input_tex.name
    if not produced.exists():
        # Be tolerant if lilypond-book slightly changes naming
        candidates = sorted(lp_out.glob(f"{input_tex.stem}*.*tex"))
        if candidates:
            produced = candidates[0]
        else:
            raise CompileError("lilypond-book did not produce expected .tex", log_path)

    # Record only this run's fragments, so removed snippets cannot become active
    # score candidates merely because their old graphics remain in the job root.
    write_text(job.compile_dir / (input_tex.stem + ".ulsbs-lilypond-systems.json"), json.dumps([
        fragment.relative_to(lp_out).as_posix() for fragment in sorted(lp_out.rglob("*-systems.tex"))
    ]) + "\n")
    # Do not let overlay_tree replace engine directory aliases with empty real
    # directories after moving their children through the symlink.
    for alias in ("ulsbs/assets", "ulsbs/src/ulsbs/assets"):
        generated, target = lp_out / alias, job.compile_dir / alias
        if generated.is_dir() and target.is_symlink():
            overlay_tree(generated, target.resolve(), move=True)
            safe_rm_tree(generated)
    # Overlay-move everything lilypond-book produced in job/_lp into the job root.
    overlay_tree(lp_out, job.compile_dir, move=True)
    try:
        safe_rm_tree(lp_out)
    except Exception:
        pass

    processed_in_jobroot = job.compile_dir / produced.name
    return processed_in_jobroot, log_path, step + 1


def step_lilypond_book_passthrough(
    ui: UI,
    job: Job,
    input_tex: Path,
    step: int,
) -> tuple[Path, Path, int]:
    """Alternative to run_lilypond_book() when no LP processing is run.

    This is a preparation hook for future workflows where LilyPond is used as
    a TeX package instead of via lilypond-book. It simply ensures that the
    main document lives in the job's compile directory and writes a small
    log file for traceability.
    """
    txt_doc = ui.fmt_doc(job)
    cwd = job.compile_dir
    log_path = cwd / f"{step:02d}_lilypond-passthrough.log"

    # Ensure the main TeX file is in the compile directory; copy if needed.
    if input_tex.parent != cwd:
        target = cwd / input_tex.name
        shutil.copy2(input_tex, target)
    else:
        target = input_tex

    write_text(
        log_path,
        "lilypond-book passthrough mode: no lilypond-book processing was run.\n",
    )
    ui.noexec_line(f"{txt_doc} lilypond-book passthrough (no processing)")
    return target, log_path, step + 1


def step_lualatex_pass(
    ui: UI,
    cfg: Config,
    job: Job,
    basename: str,
    env: dict[str, str],
    step: int,
    pass_no: int,
    draftmode: bool,
) -> tuple[Path, int]:
    """Run LuaLaTeX, returning its log path and the next per-job step number.

    Remove any previous manifest sidecar first, even between passes. Packaging
    must observe fresh status and anchors from the final pass, never a stale
    success left behind by an earlier pass or failed build.
    Append measured wall time to each completed pass log so TeX cost can be
    distinguished from between-pass score generation and executor contention.
    """
    cwd = job.compile_dir
    (cwd / f"{basename}.ulsbs-multikey.json").unlink(missing_ok=True)
    txt_doc = ui.fmt_doc(job)
    log_path = cwd / f"{step:02d}_lualatex-pass{pass_no}.log"
    label = f"lualatex (pass {pass_no})"
    ui.exec_line(f"{txt_doc} {ui.fmt_step(step)} {label}")
    args = [
        "lualatex",
        "-file-line-error",
        "-halt-on-error",
        "-interaction=nonstopmode",
    ]
    if draftmode:
        args.append("-draftmode")
    args.append(f"{basename}.tex")

    started = time.perf_counter()
    try:
        run_cmd(args, cwd=cwd, stdout_path=log_path, stderr_to_stdout=True, check=True, env=env)
    except Exception:
        raise CompileError(f"Compilation error running {label}!", log_path) from None

    elapsed = time.perf_counter() - started
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\nULSBS wall time: {elapsed:.3f} seconds "
                  f"(LuaLaTeX pass {pass_no}, {'draft' if draftmode else 'full'})\n")
    return log_path, step + 1


def step_texlua_indices(
    ui: UI, cfg: Config, job: Job, basename: str, env: dict[str, str], step: int
) -> int:
    """Create title and tag indices using texlua scripts."""
    cwd = job.compile_dir
    txt_doc = ui.fmt_doc(job)

    # Find script
    song_idx_script = cwd / SONG_IDX_SCRIPT_REL
    if not song_idx_script.exists():
        song_idx_script = (
            cwd / _JOB_ULSBS_ASSETS_DIRNAME / "tex" / "ext_packages" / "songs" / "songidx.lua"
        )
    if not song_idx_script.exists():
        msg = f"songidx.lua not found at {song_idx_script}"
        logp = cwd / f"{step:02d}_indices-error.log"
        write_text(logp, msg)
        raise CompileError(msg, logp)

    # Title index
    log_title = cwd / f"{step:02d}_titleidx.log"
    ui.exec_line(f"{txt_doc} {ui.fmt_step(step)} texlua (create title index)")
    try:
        run_cmd(
            ["texlua", str(song_idx_script), "-l", SORT_LOCALE, "idx_title.sxd", "idx_title.sbx"],
            cwd=cwd,
            stdout_path=log_title,
            stderr_to_stdout=True,
            check=True,
            env=env,
        )
    except Exception:
        raise CompileError("Error creating song title indices!", log_title) from None
    step += 1

    # Tag index
    project_tag_file = cfg.runtime.project_paths.include_dir / TAG_DEFINITION_FILENAME
    if project_tag_file.exists():
        log_tag = cwd / f"{step:02d}_tagidx.log"
        ui.exec_line(f"{txt_doc} {ui.fmt_step(step)} texlua (create tag index)")
        try:
            run_cmd(
                [
                    "texlua",
                    str(song_idx_script),
                    "-l",
                    SORT_LOCALE,
                    "-b",
                    str(project_tag_file),
                    "idx_tag.sxd",
                    "idx_tag.sbx",
                ],
                cwd=cwd,
                stdout_path=log_tag,
                stderr_to_stdout=True,
                check=True,
                env=env,
            )
        except Exception:
            raise CompileError("Error creating tag indices!", log_tag) from None
        step += 1
    else:
        ui.warning_line("Skipping creating tag index: tag definition file not found!")
    return step


def step_pdf_fonts(ui: UI, cfg: Config, job: Job, basename: str, step: int) -> int:
    """Deduplicate font programs using the optimizer's validated atomic replacement."""
    txt_doc = ui.fmt_doc(job)
    log_path = job.compile_dir / f"{step:02d}_pdf-fonts.log"
    ui.exec_line(f"{txt_doc} {ui.fmt_step(step)} internal: deduplicate PDF fonts")
    try:
        from .pdf_fonts import deduplicate_fonts

        original, final, removed = deduplicate_fonts(job.compile_dir / f"{basename}.pdf")
        summary = (
            f"PDF fonts: {original} -> {final} bytes; saved {original - final} bytes; "
            f"removed {removed} duplicate font-program streams"
        )
        write_text(log_path, summary + "\n")
    except Exception as e:
        write_text(log_path, traceback.format_exc())
        raise CompileError(f"PDF font deduplication failed: {e}", log_path) from e
    if cfg.verbose:
        ui.debug_line(f"{txt_doc} {summary}")
    return step + 1


def step_context_printouts(
    ui: UI, cfg: Config, job: Job, basename: str, env: dict[str, str], step: int
) -> int:
    """Create extra A5-on-A4 printouts with ConTeXt if templates exist."""
    result_dir = cfg.runtime.project_paths.result_dir
    cwd = job.compile_dir
    txt_doc = ui.fmt_doc(job)

    if job.multikey or PAPERA5_FNAMEPART not in basename or not cfg.create_printouts:
        return step

    context_bin = which("context") or which("contextjit")
    if not context_bin:
        ui.noexec_line(f"{txt_doc} Extra printout PDFs not created; no 'context/contextjit'")
        return step

    ui.exec_line(f"{txt_doc} {ui.fmt_step(step)} context (create printouts)")
    ensure_dir(result_dir / RESULT_PRINTOUT_SUBDIRNAME)

    def make_printout(template: Path, out_base: str, step: int) -> int:
        """Render a ConTeXt template and copy result to result/printouts."""
        if not template.exists():
            ui.noexec_line(f"{txt_doc} Printout template missing: {template.name}")
            return step
        ctx_out = cwd / f"{out_base}.context"
        data = read_text(template).replace(_PRINTOUT_INPUT_FILE_PLACEHOLDER, f"{basename}.pdf")
        write_text(ctx_out, data)
        logp = cwd / f"{step:02d}_context-{out_base}.log"
        try:
            run_cmd(
                [context_bin, ctx_out.name],
                cwd=cwd,
                stdout_path=logp,
                stderr_to_stdout=True,
                check=True,
                env=env,
            )
        except Exception:
            raise CompileError(f"context failed for {out_base}", logp) from None
        pdf_out = cwd / f"{out_base}.pdf"
        if pdf_out.exists():
            shutil.copy2(pdf_out, result_dir / RESULT_PRINTOUT_SUBDIRNAME / pdf_out.name)
            resultlist.append_line(RESULT_TYPE_PRINTOUT_PDF, pdf_out.name)
        return step + 1

    tpl1 = (
        cwd
        / _JOB_ULSBS_ASSETS_DIRNAME
        / "tex"
        / "ulsbs-printout-template_BOOKLET-A5-on-A4-doublesided-needs-cutting.context"
    )
    tpl2 = (
        cwd
        / _JOB_ULSBS_ASSETS_DIRNAME
        / "tex"
        / "ulsbs-printout-template_EASY-A5-on-A4-sidebyside-simple.context"
    )

    step = make_printout(tpl1, f"printout-BOOKLET_{basename}-on-A4-doublesided-needs-cutting", step)
    step = make_printout(tpl2, f"printout-EASY_{basename}-on-A4-sidebyside-simple", step)

    return step


def step_coverimage_extraction(
    ui: UI, cfg: Config, job: Job, basename: str, env: dict[str, str], step: int
) -> int:
    """Extract cover image(s) from the compiled PDF using pdftoppm/convert.

    The extracted base PNG is always created. Optionally, a modified/widened
    PNG is created using ImageMagick convert, driven by cfg.modified_cover_png
    rules that match the original TeX filename (job.doc_tex_abs.name).
    """
    result_dir = cfg.runtime.project_paths.result_dir
    cwd = job.compile_dir
    txt_doc = ui.fmt_doc(job)

    if job.multikey or not cfg.coverimage or not which("pdftoppm"):
        return step

    ensure_dir(result_dir / RESULT_IMAGE_SUBDIRNAME)

    # Extract cover as PNG with configurable height
    ui.exec_line(f"{txt_doc} {ui.fmt_step(step)} pdftoppm (extract cover as image)")
    log_extract = cwd / f"{step:02d}_coverimage-extract.log"
    try:
        run_cmd(
            [
                "pdftoppm",
                "-f",
                "1",
                "-singlefile",
                "-png",
                "-scale-to-x",
                "-1",
                "-scale-to-y",
                str(cfg.cover_image_height),
                f"{basename}.pdf",
                basename,
            ],
            cwd=cwd,
            stdout_path=log_extract,
            stderr_to_stdout=True,
            check=True,
            env=env,
        )
    except Exception:
        raise CompileError("pdftoppm failed while extracting cover image", log_extract) from None
    step += 1

    cover_png = cwd / f"{basename}.png"
    if cover_png.exists():
        shutil.copy2(cover_png, result_dir / RESULT_IMAGE_SUBDIRNAME / cover_png.name)
        resultlist.append_line(RESULT_TYPE_IMAGE, cover_png.name)

    # Optional: create auto-wide image via ImageMagick convert
    if which("magick"):
        ui.exec_line(f"{txt_doc} {ui.fmt_step(step)} magick (cover image modified)")
        cover_modified_png = cwd / f"{basename}{COVERIMAGE_MODIFIED_FNAME_POSTFIX}.png"
        log_auto = cwd / f"{step:02d}_coverimage-modified.log"

        # Probe image size using ImageMagick so we can interpret fractional rects
        try:
            run_cmd(
                ["magick", cover_png.name, "-format", "%w %h", "info:"],
                cwd=cwd,
                stdout_path=log_auto,
                stderr_to_stdout=True,
                check=True,
                env=env,
            )
            tokens = read_text(log_auto).split()
            if len(tokens) < 2:
                raise ValueError("Unexpected output from magick -format '%w %h'")
            img_w = int(tokens[0])
            img_h = int(tokens[1])
        except Exception:
            raise CompileError("magick failed while probing cover image size", log_auto) from None

        # Select the last matching rule (if any) based on the original TeX filename
        src_filename = job.doc_tex_abs.name
        selected_rule = None
        for rule in cfg.modified_cover_png:
            if fnmatch(src_filename, rule.songbook_filenames):
                selected_rule = rule

        cmd: list[str] = ["magick", cover_png.name]

        if selected_rule is not None:
            rule = selected_rule
            # Optional painting on the original image before widening
            rects = list(rule.paint_area_rects)
            if rects:
                cmd += ["-fill", rule.color]
                for r in rects:
                    # Bottom-left (0,0) -> ImageMagick's top-left (0,0)
                    x1 = int(round(r.x1 * img_w))
                    x2 = int(round(r.x2 * img_w))
                    y1 = int(round((1.0 - r.y2) * img_h))
                    y2 = int(round((1.0 - r.y1) * img_h))
                    cmd += ["-draw", f"rectangle {x1},{y1} {x2},{y2}"]

            # Width relative to original; 0 means "square" (width = height)
            target_h = img_h
            if rule.width_multiplier == 0:
                target_w = target_h
            else:
                target_w = int(round(img_w * rule.width_multiplier))

            cmd += [
                "-background",
                rule.color,
                "-gravity",
                "center",
                "-extent",
                f"{target_w}x{target_h}",
                cover_modified_png.name,
            ]
        else:
            # No specific rule; make the modified image a square and center
            # the image, without extra painting.
            target_w = target_h = img_h
            cmd += [
                "-gravity",
                "center",
                "-extent",
                f"{target_w}x{target_h}",
                cover_modified_png.name,
            ]

        try:
            run_cmd(
                cmd,
                cwd=cwd,
                stdout_path=log_auto,
                stderr_to_stdout=True,
                check=True,
                env=env,
                append=True,
            )
        except Exception:
            raise CompileError(
                "convert failed while creating modified cover image", log_auto
            ) from None

        if cover_modified_png.exists():
            shutil.copy2(
                cover_modified_png, result_dir / RESULT_IMAGE_SUBDIRNAME / cover_modified_png.name
            )
            resultlist.append_line(RESULT_TYPE_IMAGE, cover_modified_png.name)
        step += 1

    return step


def step_build_song_db(
    ui: UI,
    cfg: Config,
    job: Job,
    processed_tex: Path,
    include_paths: list[Path],
    step: int,
) -> tuple[SongbookData | None, int]:
    """Build the internal song database from the processed TeX tree.

    This step only builds the in-memory database; it does not write JSON.
    JSON is written later (after MIDI/audio steps) so that any derived
    result file paths are included in the JSON output.
    """
    txt_doc = ui.fmt_doc(job)
    log_path = job.compile_dir / f"{step:02d}_songdb-build.log"

    # Audio needs song metadata for routing and tags even when JSON and MIDI
    # export are disabled; JSON is only one consumer of this in-memory database.
    do_midi, do_audio = _midi_audio_enabled(cfg, job)
    want_db = not job.multikey and bool(cfg.json or do_midi or do_audio)
    if not want_db:
        return None, step

    ui.exec_line(f"{txt_doc} {ui.fmt_step(step)} internal: build metadata")

    psv_path = job.compile_dir / f"{processed_tex.stem}.ulsbs.psv"
    ulsbs_psv_file: Path | None = None
    if psv_path.is_file():
        ulsbs_psv_file = psv_path
    else:
        ui.warning_line(f"{txt_doc} PSV file not found: {psv_path.name}")

    try:
        db = build_song_database(
            processed_tex=processed_tex,
            include_search_paths=include_paths,
            variant=job.variant,
            plain_lowercase_lyrics=JSON_INCLUDE_PLAIN_LOWERCASE_LYRICS,
            ulsbs_psv_file=ulsbs_psv_file,
        )

        all_songs = list(db.songs_without_chapter)
        for chap in db.chapters:
            all_songs.extend(chap.songs)
        bad_id_count = sum(
            1 for s in all_songs if s.id is not None and re.fullmatch(r"[a-z0-9-]+", s.id) is None
        )

        write_text(
            log_path,
            "Internal song database built for this book.\n\n"
            f"  - Book title: {'<none>' if db.book_info.maintitle is None else db.book_info.maintitle}\n"
            f"  - Book subtitle: {'<none>' if db.book_info.subtitle is None else db.book_info.subtitle}\n"
            f"  - Book variant: {'<none>' if db.book_info.variant is None else db.book_info.variant}\n"
            f"  - Total songs found: {str(db.total_songs)}\n"
            f"  - Songs with id: {str(db.songs_with_id)}\n"
            f"  - Songs with malformed id: {str(bad_id_count)}\n\n"
        )

        # Warn if missing ids
        if db.songs_with_id < db.total_songs:
            ui.warning_line(
                f"{txt_doc} Warning: only {db.songs_with_id}/{db.total_songs} songs have an id"
            )

        # Also warn about malformed ids (not matching [a-z0-9-]+)
        if bad_id_count > 0:
            ui.warning_line(
                f"{txt_doc} Warning: there were {bad_id_count} malformed song ids. "
                "Run ulsbs-bookmeta --check-song-ids for more info."
            )
    except Exception as e:
        # Do not abort the job: metadata is an optional post-processing step.
        write_text(log_path, f"Song database build failed: {e!r}\n")
        ui.warning_line(f"{txt_doc} Warning: failed to build internal song database: {e}")
        step += 1
        return None, step

    step += 1
    return db, step


def step_write_song_db_json(
    ui: UI,
    cfg: Config,
    job: Job,
    processed_tex: Path,
    db: SongbookData | None,
    step: int,
) -> int:
    """Write SongbookData JSON after post-processing steps.

    This is run after MIDI/audio so that any midi_result_file_relative and
    audio_result_file_relative fields are included in the JSON.
    """

    if job.multikey or not cfg.json:
        return step

    if db is None:
        return step

    txt_doc = ui.fmt_doc(job)
    log_path = job.compile_dir / f"{step:02d}_songdb-json.log"
    ui.exec_line(f"{txt_doc} {ui.fmt_step(step)} internal: write metadata JSON")

    try:
        json_compile_path = job.compile_dir / f"{processed_tex.stem}.json"
        db.to_json_file(json_compile_path)

        result_dir = cfg.runtime.project_paths.result_dir
        ensure_dir(result_dir / RESULT_JSON_SUBDIRNAME)
        shutil.copy2(
            json_compile_path,
            result_dir / RESULT_JSON_SUBDIRNAME / json_compile_path.name,
        )
        resultlist.append_line(RESULT_TYPE_JSON, json_compile_path.name)

        write_text(
            log_path,
            "Internal song database JSON written for this book.\n\n"
            f"  - JSON file written: {json_compile_path.name}\n\n",
        )
    except Exception as e:
        write_text(log_path, f"Song database JSON write failed: {e!r}\n")
        raise CompileError("Failed to write song/chapter JSON", log_path) from None

    return step + 1


def step_midi_audio(
    ui: UI,
    assets: EngineAssets,
    cfg: Config,
    job: Job,
    processed_tex: Path,
    db: SongbookData | None,
    step: int,
) -> int:
    """Create MIDI directories and audio encodes based on the TeX tree."""

    do_midi, do_audio = _midi_audio_enabled(cfg, job)

    # Skip if no midi nor audio is requested
    if not (do_midi or do_audio):
        return step

    txt_doc = ui.fmt_doc(job)

    if db is None:
        ui.warning_line(f"{txt_doc} No internal db; skipping midi/audio")
        return step

    result_dir = cfg.runtime.project_paths.result_dir

    # Flatten songs while keeping document order
    all_songs = list(db.songs_without_chapter)
    for chap in db.chapters:
        all_songs.extend(chap.songs)
    songs_with_midi = [s for s in all_songs if s.midi_compile_file_relative is not None]

    if not songs_with_midi:
        ui.noexec_line(f"{txt_doc} No MIDI files referenced; skipping midi/audio")
        return step

    # MIDI copies
    if do_midi:
        ui.exec_line(f"{txt_doc} {ui.fmt_step(step)} internal: grab MIDI files")
        cur_res_midi = result_dir / RESULT_MIDI_SUBDIRNAME / processed_tex.stem
        safe_rm_tree(cur_res_midi)
        ensure_dir(cur_res_midi)
        log_midi = job.compile_dir / f"{step:02d}_grab-midi.log"
        copy_error_count = 0

        for song in songs_with_midi:
            midi_abs_path = job.compile_dir / song.midi_compile_file_relative
            parent = cur_res_midi
            if song.chapter_slug:
                parent = parent / song.chapter_slug
            ensure_dir(parent)

            if song.number:
                # Zero-pad purely numeric song numbers; keep others as-is.
                if str(song.number).isdigit():
                    num_str = f"{int(song.number):03d}"
                else:
                    num_str = str(song.number)
            else:
                # Fallback to order index if counter is unavailable
                num_str = f"{song.order_index:03d}"
            base = f"{num_str}__{song.title_slug}"
            dest = parent / f"{base}.midi"
            try:
                shutil.copy2(midi_abs_path, dest)
                append_text(log_midi, f"Copied MIDI for '{song.title}' from {midi_abs_path}\n")
                # Store result path relative to the global result directory
                song.set_midi_result_file_relative(dest.relative_to(result_dir))
            except Exception:
                copy_error_count += 1
                append_text(
                    log_midi,
                    f"Warning: Failed to copy MIDI for '{song.title}' from {midi_abs_path}\n",
                )

        if copy_error_count > 0:
            ui.warning_line(f"{txt_doc} Failed to copy {copy_error_count} MIDI files")

        # Copy midi README, if set in config, into midi result dir
        readme_midi = cfg.mididir_readme_file
        if readme_midi:
            if readme_midi.exists():
                shutil.copy2(readme_midi, cur_res_midi / "README.md")
            else:
                append_text(
                    log_midi,
                    f"Warning: Readme for MIDI directories does not exist: {readme_midi}\n",
                )
                ui.warning_line(f"{txt_doc} Readme for MIDI dir does not exist: {readme_midi}")
        resultlist.append_line(RESULT_TYPE_MIDIDIR, cur_res_midi.name)
        step += 1

    # Audio encodes
    if do_audio:
        ui.exec_line(f"{txt_doc} {ui.fmt_step(step)} ulsbs-midi2audio (encode audio)")
        cur_res_audio = result_dir / RESULT_AUDIO_SUBDIRNAME / processed_tex.stem
        safe_rm_tree(cur_res_audio)
        ensure_dir(cur_res_audio)
        log_audio = job.compile_dir / f"{step:02d}_encode-audio.log"

        for song in songs_with_midi:
            midi_abs_path = job.compile_dir / song.midi_compile_file_relative
            parent = cur_res_audio
            if song.chapter_slug:
                parent = parent / song.chapter_slug
            ensure_dir(parent)

            if song.number:
                # Zero-pad purely numeric song numbers; keep others as-is.
                if str(song.number).isdigit():
                    num_str = f"{int(song.number):03d}"
                else:
                    num_str = str(song.number)
            else:
                num_str = f"{song.order_index:03d}"
            base = f"{num_str}__{song.title_slug}__from-midi"
            out_base = parent / base

            args = [
                "python3",
                "-m",
                "ulsbs.tools.midi2audio",
                "--force-overwrite",
                "--verbose",
                "--mp3-vbr-quality",
                "6",  # 0-9, lower is better
                "--mp3",
            ]
            # loudnorm (slow) / limiter (fast)
            if cfg.fast_audio_encode:
                args += ["--enable-loudnorm", "0", "--enable-limiter", "1"]
            else:
                args += ["--enable-loudnorm", "1", "--enable-limiter", "0"]
            # metadata tags
            if song.number:
                args += [
                    "--tag-tracknr",
                    str(song.number),
                ]
            if song.title:
                args += [
                    "--tag-tracktitle",
                    song.title,
                ]
            if song.options and song.options.get("by"):
                args += [
                    "--tag-trackartist",
                    song.options.get("by"),
                ]
            if song.chapter_title:
                args += [
                    "--tag-albumtitle",
                    song.chapter_title,
                ]
            args += [
                "--tag-albumartist",
                GENAUDIO_ALBUMTITLE,
                "--tag-image",
                str(
                    job.compile_dir
                    / _JOB_ULSBS_ASSETS_DIRNAME
                    / "img"
                    / "ulsbs-album-cover-for-generated-audio.png"
                ),
            ]
            # input and output file
            args += [
                "--outfile-basename",
                str(out_base),
                str(midi_abs_path),
            ]
            try:
                run_cmd(
                    args,
                    cwd=job.compile_dir,
                    stdout_path=log_audio,
                    stderr_to_stdout=True,
                    check=True,
                    append=True,
                )
                # Best-effort: record the expected MP3 path relative to the result directory
                audio_out = out_base.with_suffix(".mp3")
                if audio_out.exists():
                    song.set_audio_result_file_relative(audio_out.relative_to(result_dir))
            except Exception:
                raise CompileError(
                    "ulsbs-midi2audio failed while encoding audio", log_audio
                ) from None

        # Copy audio README, if set in config, into audio result dir
        readme_audio = cfg.audiodir_readme_file
        if readme_audio:
            if readme_audio.exists():
                shutil.copy2(readme_audio, cur_res_audio / "README.md")
            else:
                append_text(
                    log_audio,
                    f"Warning: Readme for audio directories does not exist: {readme_audio}\n",
                )
                ui.warning_line(f"{txt_doc} Readme for audio does not exist: {readme_audio}")
        resultlist.append_line(RESULT_TYPE_AUDIODIR, cur_res_audio.name)
        step += 1

    return step


def analyze_warnings(
    ui: UI, cfg: Config, job: Job, lilypond_log: Path, last_lualatex_log: Path
) -> int:
    """Count and summarize warnings from lilypond and LuaLaTeX logs."""
    txt_doc = ui.fmt_doc(job)
    total_warn = 0
    lp_all_warn = 0
    tex_all_warn = 0
    try:
        # LilyPond warnings (skip for lyrics variant)
        if job.variant != "lyrics" and lilypond_log and lilypond_log.exists():
            lp_log_txt = read_text(lilypond_log)
            lp_all_warn = len(re.findall(r"warning", lp_log_txt, flags=re.I))
            lp_bar_warn = len(re.findall(r"warning: barcheck", lp_log_txt, flags=re.I))
            lp_auto_warn = len(
                re.findall(
                    r"warning: Unable to auto-detect default settings", lp_log_txt, flags=re.I
                )
            )
            if lp_all_warn > 0 and lp_auto_warn == 1:
                lp_all_warn -= 1
            if lp_all_warn:
                ui.warning_line(
                    f"{txt_doc} Lilypond warnings - all: {lp_all_warn} (barcheck: {lp_bar_warn})"
                )
            total_warn += lp_all_warn
    except Exception:
        ui.warning_line(f"{txt_doc} Lilypond warnings - failed to read the log file")

    try:
        # TeX warnings (from the last LuaLaTeX pass)
        if last_lualatex_log and last_lualatex_log.exists():
            lt_log_txt = read_text(last_lualatex_log)
            tex_all_warn = len(re.findall(r"warning", lt_log_txt, flags=re.I))
            tex_font_warn = len(re.findall(r"Font Warning", lt_log_txt, flags=re.I))
            if tex_all_warn:
                ui.warning_line(
                    f"{txt_doc} TeX warnings - all: {tex_all_warn} (font: {tex_font_warn})"
                )
            if tex_font_warn > 20:
                ui.space_line(ui.colorize("Concerning amount of font warnings!", ui.C_RED))
            total_warn += tex_all_warn

    except Exception:
        ui.warning_line(f"{txt_doc} TeX warnings - failed to read the log file")

    if total_warn > 0 and not cfg.clean_temp:
        if lp_all_warn:
            ui.see_line(
                TEMP_DIRNAME
                + "/"
                + str(lilypond_log.relative_to(lilypond_log.parent.parent.parent))
            )
        if tex_all_warn:
            ui.see_line(
                TEMP_DIRNAME
                + "/"
                + str(last_lualatex_log.relative_to(last_lualatex_log.parent.parent.parent))
            )

    return total_warn


def step_lualatex_convergence(
    ui: UI, cfg: Config, job: Job, basename: str, env: dict[str, str], last_tex_log: Path, step: int,
) -> tuple[Path, int]:
    """Settle explicit reference requests and MULTIKEY resources before publication.

    Share the fixed ``LUALATEX_MAX_EXTRA_PASSES`` budget between both checks.
    Ordinary jobs inspect only the latest log; MULTIKEY jobs also validate
    pdfbase's cached property references. Unreadable inputs fail immediately;
    ordinary warnings, including undefined references without a rerun request,
    retain their policy.
    Each retry refreshes the manifest through ``step_lualatex_pass``.
    """
    warning_pattern = re.compile(
        r"^(LaTeX|Package (?:rerunfilecheck|hyperref|lastpage)) Warning:"
        r"[^\n]*(?:\n(?![ \t]*$|(?:LaTeX|Package \S+) Warning:)[^\n]+)*",
        re.M,
    )
    requests = {
        "LaTeX": r"Label\(s\)mayhavechanged|Reruntogetcross-referencesright",
        "Package rerunfilecheck": r"File[`'][^`']*\.out['`]haschanged",
        "Package hyperref": r"Reruntoget/?PageLabels(?:right|entry)",
        "Package lastpage": r"Reruntoget(?:the)?referencesright",
    }

    for extra in range(LUALATEX_MAX_EXTRA_PASSES + 1):
        try:
            reasons = []
            for warning in warning_pattern.finditer(read_text(last_tex_log)):
                # TeX wraps filenames/words and prefixes package continuation lines.
                compact = re.sub(r"\((?:rerunfilecheck|hyperref|lastpage)\)", "", warning[0])
                compact = re.sub(r"\s+", "", compact)
                if re.search(requests[warning[1]], compact, re.I):
                    reasons.append(re.sub(r"\s+", " ", warning[0]).strip())
            if job.multikey:
                from .multikey_ranges import check_pdf_property_resources

                try:
                    check_pdf_property_resources(job.compile_dir / f"{basename}.pdf")
                except ValueError as error:
                    reasons.append(str(error))
        except Exception as error:
            log_path = job.compile_dir / f"{step:02d}_lualatex-convergence.log"
            write_text(log_path, traceback.format_exc())
            raise CompileError(f"Cannot inspect LuaLaTeX convergence: {error}", log_path) from error
        if not reasons:
            return last_tex_log, step
        diagnostic = f"Last LuaLaTeX log: {last_tex_log}\n" + "\n".join(reasons) + "\n"
        if extra == LUALATEX_MAX_EXTRA_PASSES:
            log_path = job.compile_dir / f"{step:02d}_lualatex-convergence.log"
            write_text(log_path, diagnostic)
            raise CompileError("LuaLaTeX references/resources did not settle after "
                               f"{LUALATEX_MAX_EXTRA_PASSES} extra passes", log_path)
        pass_no = 4 + extra
        ui.info_line(f"{ui.fmt_doc(job)} Rerunning LuaLaTeX pass {pass_no} "
                     f"to settle references/resources: {'; '.join(reasons)}")
        last_tex_log, step = step_lualatex_pass(ui, cfg, job, basename, env, step, pass_no, False)
    raise AssertionError("Unreachable LuaLaTeX convergence state")


def step_multikey_ranges(
    ui: UI, cfg: Config, job: Job, basename: str, ordinary_job: Job | None, step: int,
) -> tuple[Path | None, int]:
    """Stage, validate, and publish one ready MULTIKEY edition.

    The caller holds this job's lock and has finished both matching compilations.
    ``basename`` identifies the private, font-deduplicated master and final-pass
    sidecar in ``job.compile_dir``. The ordinary source/variant and this run's
    output inventory are checked before using the canonical PDF or book JSON.

    Extract fresh candidates under ``compile_dir/ranges``, publish ranges and
    then their index under ``result/multikey``, retire exact owned legacy names,
    and finally add the completed-package reference to ordinary book metadata.
    This step owns build inventory updates; the lower-level packager does not.

    Return ``(index_path, next_step)``. Explicitly disabled layers instead retire
    the prior owned package, warn, and return ``(None, next_step)``. Validation or
    publication errors are logged in a numbered per-job log and wrapped in
    ``CompileError``. A pre-publication failure invalidates a potentially stale
    index, while a newly completed family survives later bookkeeping failures.
    """
    from .multikey_ranges import package_ranges
    from .multikey_publish import publish_package, remove_legacy_outputs, remove_package

    result_dir = cfg.runtime.project_paths.result_dir
    output_dir = result_dir / RESULT_MULTIKEY_SUBDIRNAME
    output_name = f"{basename}_RANGES.json"
    output_index = output_dir / output_name
    log_path = job.compile_dir / f"{step:02d}_multikey-ranges.log"
    ui.exec_line(f"{ui.fmt_doc(job)} {ui.fmt_step(step)} internal: package MULTIKEY ranges")
    published = False
    try:
        try:
            envelope = json.loads(read_text(job.compile_dir / f"{basename}.ulsbs-multikey.json"))
            enabled = envelope["has_multikey_info"]
            payload = envelope["multikey_info"]
            if not ((enabled is True and isinstance(payload, dict))
                    or (enabled is False and payload is None)):
                raise ValueError("Invalid multikey metadata envelope")
        except Exception as error:
            raise ValueError(f"Failed to capture multikey metadata: {error}") from error

        if enabled is False:
            remove_package(output_index)
            remove_legacy_outputs(output_dir, result_dir / RESULT_JSON_SUBDIRNAME,
                                  basename.removesuffix("_MULTIKEY"))
            write_text(log_path, "Source disables PDF layers; previous package retired.\n")
            ui.warning_line(f"{ui.fmt_doc(job)} Skipping multikey companion: source disables PDF layers")
            return None, step + 1

        if (ordinary_job is None or ordinary_job.multikey
                or (ordinary_job.doc_tex_abs, ordinary_job.variant) != (job.doc_tex_abs, job.variant)):
            raise ValueError("No successful matching ordinary edition in this run")
        canonical = result_dir / f"{build_job_basename(ordinary_job)}.pdf"
        records = set(resultlist.lines()) if resultlist.exists() else set()
        if f"{RESULT_TYPE_MAIN_PDF}{RESULTLIST_SEPARATOR}{canonical.name}" not in records:
            raise ValueError("Ordinary PDF is not in this run's output inventory")

        # Retained debug builds may contain old staged ranges; never reuse them.
        safe_rm_tree(job.compile_dir / "ranges")
        staged_index = package_ranges(
            job.compile_dir / f"{basename}.pdf", canonical, envelope,
            job.compile_dir / "ranges", max_pages=cfg.multikey_max_pages_per_range,
            target_bytes=cfg.multikey_target_max_range_bytes, warn=ui.warning_line,
        )
        names = publish_package(staged_index, output_dir, canonical)
        published = True
        for name in names:
            resultlist.append_line(
                RESULT_TYPE_MULTIKEY_JSON if name == output_name else RESULT_TYPE_MULTIKEY_PDF, name,
            )
        remove_legacy_outputs(output_dir, result_dir / RESULT_JSON_SUBDIRNAME, canonical.stem)

        # The scheduler waits for the whole ordinary job, including media and
        # JSON export, so it cannot overwrite this completed-package reference.
        source_name = f"{build_job_basename(ordinary_job)}.json"
        if cfg.json and f"{RESULT_TYPE_JSON}{RESULTLIST_SEPARATOR}{source_name}" in records:
            json_dir = result_dir / RESULT_JSON_SUBDIRNAME
            data = json.loads(read_text(json_dir / source_name))
            data["book_info"].pop("multikey_file", None)
            data["book_info"]["multikey_json_file"] = f"{RESULT_MULTIKEY_SUBDIRNAME}/{output_name}"
            temporary = json_dir / f".{source_name}.tmp"
            write_text(temporary, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            os.replace(temporary, json_dir / source_name)
        write_text(log_path, "Published MULTIKEY package:\n" + "\n".join(names) + "\n")
    except Exception as error:
        # An earlier index may describe an ordinary PDF replaced in this run.
        # Keep a newly published complete package if only bookkeeping failed.
        if not published:
            output_index.unlink(missing_ok=True)
        write_text(log_path, traceback.format_exc())
        raise CompileError(f"Failed to publish multikey ranges: {error}", log_path) from error
    return output_index, step + 1


def compile_one_job(
    ui: UI,
    assets: EngineAssets,
    cfg: Config,
    job: Job,
) -> CompilationResult:
    """Compile and optimize independently, retaining MULTIKEY masters privately.

    Hold the existing job lock through preparation, engraving, final pagination,
    font deduplication, optional exports, and warning analysis, releasing it on
    every exit. Ordinary PDF/media/JSON outputs are published in this phase.
    MULTIKEY jobs suppress those exports and report compilation completion, not
    final success; their master and fresh sidecar remain in the compile directory.

    Return compiler warnings and the next log number in ``CompilationResult``.
    The scheduler supplies that small handoff to a separate packaging task once
    both matching compilations succeed. Failures retain the usual numbered-log
    diagnostics and raise ``CompileError`` rather than returning a result.
    """
    txt_doc = ui.fmt_doc(job)
    ui.start_line(txt_doc)

    lock = JobLock(job.compile_dir)
    lock.acquire()

    try:
        prepare_compile_dir(ui=ui, assets=assets, cfg=cfg, job=job)
        result_dir = cfg.runtime.project_paths.result_dir
        pdf_dir = result_dir / RESULT_MULTIKEY_SUBDIRNAME if job.multikey else result_dir
        if cfg.verbose:
            basename = build_job_basename(job)
            midi, audio = _midi_audio_enabled(cfg, job)
            layers = cfg.multikey_books and job.multikey and job.variant != "lyrics"
            printouts = (
                not job.multikey and cfg.create_printouts and PAPERA5_FNAMEPART in basename
                and bool(which("context") or which("contextjit"))
            )
            output_file = pdf_dir / (basename + ("_RANGES.json" if job.multikey else ".pdf"))
            ui.debug_line(
                f"{txt_doc}\n{ui.colorize('Source:', ui.C_DGRAY)} {job.doc_tex_abs}; variant: {job.variant}; "
                f"edition: {'multikey' if job.multikey else 'standard'}; "
                f"compile: {job.compile_dir}; {'Index' if job.multikey else 'PDF'}: {output_file}"
                f"\n{ui.colorize('Outputs:', ui.C_DGRAY)} printouts={printouts}, MIDI={midi}, audio={audio}, "
                f"JSON={'range index' if job.multikey else cfg.json}, "
                f"covers={not job.multikey and cfg.coverimage and bool(which('pdftoppm'))}; "
                f"layers={layers}"
                + (f", strict IDs={cfg.multikey_require_song_ids}, layer UI={cfg.multikey_layer_ui}, "
                   f"min chord scale={cfg.multikey_min_chordname_scale:g}"
                   if layers else "")
            )
        input_tex = make_variant_tex(job, cfg)
        env: dict[str, str]
        lp_include_args: list[str]
        env, lp_include_args, db_include_paths = build_include_paths(cfg=cfg, job=job)
        if job.multikey and cfg.multikey_books and cfg.multikey_lilypond_scores and job.variant != "lyrics":
            # Capture the authoritative breaks while engraving t00, not in a
            # second approximation of the original's layout.
            # Heads cover explicit assemblies without tails; tails reinstall
            # capture after source-defined layout callbacks. The listener records
            # each physical system once even when both includes are present.
            for asset in ("ulsbs-internal-common-head.ly", "ulsbs-internal-common-tail.ly"):
                path = job.compile_dir / _JOB_ULSBS_ASSETS_DIRNAME / "ly" / asset
                write_text(path, read_text(path) + '\n\\include "ulsbs-score-boundaries.ily"\n')

        # Step counter for log numbering
        step = 1

        # 1) lilypond-book (+ overlay to job root)
        try:
            processed_tex, lp_log, step = step_lilypond_book(
                ui=ui,
                job=job,
                input_tex=input_tex,
                env=env,
                lp_include_args=lp_include_args,
                step=step,
            )
        except CompileError as ce:
            die_log(ui, cfg, job, cwd=job.compile_dir, message=str(ce), log_path=ce.log_path)

        basename = processed_tex.stem
        cwd = job.compile_dir
        ensure_dir(pdf_dir)

        score_sources = None
        if job.multikey and cfg.multikey_books and cfg.multikey_lilypond_scores and job.variant != "lyrics":
            from .lilypond_scores import prepare_scores

            score_sources = prepare_scores(cwd, basename)

        # 2) lualatex pass 1 (draftmode)
        try:
            last_tex_log, step = step_lualatex_pass(
                ui, cfg, job, basename, env, step, pass_no=1, draftmode=True
            )
        except CompileError as ce:
            die_log(ui, cfg, job, cwd=cwd, message=str(ce), log_path=ce.log_path)

        if score_sources is not None:
            from .lilypond_scores import generate_scores

            generate_scores(ui, job, basename, score_sources, env, lp_include_args, verbose=cfg.verbose)

        # 3) indices (if not selection)
        if not basename.startswith(SELECTION_FNAME_PREFIX):
            try:
                step = step_texlua_indices(ui, cfg, job, basename, env, step)
            except CompileError as ce:
                die_log(ui, cfg, job, cwd=cwd, message=str(ce), log_path=ce.log_path)

        # 4) lualatex pass 2 (full PDF, including image object allocation)
        try:
            last_tex_log, step = step_lualatex_pass(
                ui, cfg, job, basename, env, step, pass_no=2, draftmode=False
            )
        except CompileError as ce:
            die_log(ui, cfg, job, cwd=cwd, message=str(ce), log_path=ce.log_path)

        # 5) Full pass 3 resolves aux resource references from the first full pass.
        try:
            last_tex_log, step = step_lualatex_pass(
                ui, cfg, job, basename, env, step, pass_no=3, draftmode=False
            )
        except CompileError as ce:
            die_log(ui, cfg, job, cwd=cwd, message=str(ce), log_path=ce.log_path)

        # Ensure PDF exists before post-processing or publication.
        produced_pdf = cwd / f"{basename}.pdf"
        if not produced_pdf.exists():
            die_log(
                ui,
                cfg,
                job,
                cwd=cwd,
                message="Expected PDF not produced by lualatex.",
                log_path=last_tex_log,
            )
        try:
            last_tex_log, step = step_lualatex_convergence(
                ui, cfg, job, basename, env, last_tex_log, step,
            )
        except CompileError as ce:
            die_log(ui, cfg, job, cwd=cwd, message=str(ce), log_path=ce.log_path)
        try:
            step = step_pdf_fonts(ui, cfg, job, basename, step)
        except CompileError as ce:
            die_log(ui, cfg, job, cwd=cwd, message=str(ce), log_path=ce.log_path)

        if not job.multikey:
            dst_pdf = pdf_dir / produced_pdf.name
            shutil.copy2(produced_pdf, dst_pdf)
            resultlist.append_line(RESULT_TYPE_MAIN_PDF, produced_pdf.name)

        # 6) Optional printouts
        try:
            step = step_context_printouts(ui, cfg, job, basename, env, step)
        except CompileError as ce:
            die_log(ui, cfg, job, cwd=cwd, message=str(ce), log_path=ce.log_path)

        # 7) Optional cover image extraction
        try:
            step = step_coverimage_extraction(ui, cfg, job, basename, env, step)
        except CompileError as ce:
            die_log(ui, cfg, job, cwd=cwd, message=str(ce), log_path=ce.log_path)

        # 8) Build song database (in-memory only)
        try:
            song_db, step = step_build_song_db(
                ui=ui,
                cfg=cfg,
                job=job,
                processed_tex=processed_tex,
                include_paths=db_include_paths,
                step=step,
            )
        except CompileError as ce:
            die_log(ui, cfg, job, cwd=cwd, message=str(ce), log_path=ce.log_path)

        # 9) MIDI/audio assets (may update db with result file paths)
        try:
            step = step_midi_audio(
                ui=ui,
                assets=assets,
                cfg=cfg,
                job=job,
                processed_tex=processed_tex,
                db=song_db,
                step=step,
            )
        except CompileError as ce:
            die_log(ui, cfg, job, cwd=cwd, message=str(ce), log_path=ce.log_path)

        # 10) Optional JSON output (write after midi/audio so paths are included)
        try:
            step = step_write_song_db_json(
                ui=ui,
                cfg=cfg,
                job=job,
                processed_tex=processed_tex,
                db=song_db,
                step=step,
            )
        except CompileError as ce:
            die_log(ui, cfg, job, cwd=cwd, message=str(ce), log_path=ce.log_path)

        # Analyze warnings using lilypond log and the last lualatex log
        warn_count = analyze_warnings(
            ui, cfg, job, lilypond_log=lp_log, last_lualatex_log=last_tex_log
        )

        if job.multikey:
            ui.info_line(f"{txt_doc} Compilation complete; awaiting MULTIKEY range packaging.")
        else:
            ui.success_line(f"{txt_doc} Compilation successful!")
            ui.space_line(f"{ui.colorize('->', ui.C_LGREEN)} {dst_pdf.relative_to(result_dir.parent)}")
        return CompilationResult(warning_count=warn_count, next_step=step)
    finally:
        lock.release()


def finish_multikey_job(
    ui: UI, cfg: Config, job: Job, ordinary_job: Job, compilation: CompilationResult,
) -> int:
    """Publish a compiled MULTIKEY job after its ordinary counterpart succeeds.

    This worker never waits for another future. Reacquire the same per-job lock
    used by compilation, continue log numbering from ``compilation.next_step``,
    and run ``step_multikey_ranges``. The coordinator must keep the private
    compile directory until this task finishes; CLI cleanup happens afterward.

    Report final success only for a published package. Return the compiler's
    warning count, adding one for an explicitly layer-disabled source without
    announcing publication. Packaging failures use the ordinary job diagnostic
    path and release the lock before propagating to the coordinator.
    """
    lock = JobLock(job.compile_dir)
    lock.acquire()
    try:
        try:
            output, _ = step_multikey_ranges(
                ui, cfg, job, build_job_basename(job), ordinary_job, compilation.next_step,
            )
        except CompileError as error:
            die_log(ui, cfg, job, cwd=job.compile_dir, message=str(error), log_path=error.log_path)
        if output is None:
            return compilation.warning_count + 1
        ui.success_line(f"{ui.fmt_doc(job)} Compilation and MULTIKEY packaging successful!")
        ui.space_line(f"{ui.colorize('->', ui.C_LGREEN)} "
                      f"{output.relative_to(cfg.runtime.project_paths.result_dir.parent)}")
        return compilation.warning_count
    finally:
        lock.release()


def run_jobs_parallel(
    ui: UI,
    jobs: List[Job],
    assets: EngineAssets,
    cfg: Config,
) -> ParallelRunResult:
    """Compile in parallel and submit packaging when each matching pair is ready.

    Expect a queue with unique publication paths, as checked by job construction.
    Submit ordinary and MULTIKEY compilation together. Match editions by absolute
    source path and musical variant, not basename or queue order. An orphan
    MULTIKEY job fails without starting; either compilation failing prevents its
    package from being published, even if the other compilation is still running.

    A ready pair submits exactly one packaging task to the same bounded executor.
    Neither phase waits inside a worker, so a single worker cannot deadlock and
    unrelated jobs do not impose a global packaging barrier. Available executor
    capacity still determines when an already queued packaging task can start.

    Ordinary jobs become successful after compilation; MULTIKEY jobs only after
    packaging. Count their warnings once, without counting the intermediate
    compilation separately. Return final outcomes in ``ParallelRunResult``.
    Call from the main thread: this function temporarily installs a cooperative
    SIGINT handler, cancels queued work on abort, restores the previous handler,
    and propagates ``KeyboardInterrupt`` after executor shutdown.
    """
    successes: List[JobSuccess] = []
    failures: List[JobFailure] = []
    failed: set[Job] = set()
    compiled: dict[Job, CompilationResult] = {}
    packaging_started: set[Job] = set()
    stop_requested = {"value": False}

    def record_failure(job: Job, reason: str) -> None:
        """Deduplicate dependency failure and a later error from its running job."""
        if job not in failed:
            failed.add(job)
            failures.append(JobFailure(job, reason))

    def handle_sigint(signum, frame):
        """Request cooperative job cancellation without raising in the signal handler."""
        ABORT_EVENT.set()
        stop_requested["value"] = True
        # Don't raise here; let the main loop notice and cancel futures.

    old_int = signal.signal(signal.SIGINT, handle_sigint)

    ABORT_EVENT.clear()

    try:
        with cf.ThreadPoolExecutor(max_workers=cfg.max_parallel) as ex:
            # Each future maps to (job, is_packaging). Compilation returns a
            # handoff object; packaging returns the final integer warning count.
            fut_map = {}

            ordinary = {(job.doc_tex_abs, job.variant): job for job in jobs if not job.multikey}
            companions = {(job.doc_tex_abs, job.variant): job for job in jobs if job.multikey}
            for job in jobs:
                if job.multikey and (job.doc_tex_abs, job.variant) not in ordinary:
                    record_failure(job, "No matching ordinary edition in this run")
                else:
                    fut_map[ex.submit(compile_one_job, ui, assets, cfg, job)] = (job, False)

            # Compilation and packaging use the same bounded pool. Only this
            # coordinator waits on futures; workers never wait on one another.
            while fut_map:
                completed, _ = cf.wait(fut_map, return_when=cf.FIRST_COMPLETED)
                if stop_requested["value"]:
                    break
                for fut in completed:
                    job, packaging = fut_map.pop(fut)
                    try:
                        result = fut.result()
                    except KeyboardInterrupt:
                        stop_requested["value"] = True
                        ABORT_EVENT.set()
                        break
                    except Exception as error:
                        if ABORT_EVENT.is_set():
                            continue
                        record_failure(job, str(error))
                        if not job.multikey:
                            companion = companions.get((job.doc_tex_abs, job.variant))
                            if companion is not None:
                                record_failure(companion, "Matching ordinary edition failed")
                    else:
                        if packaging:
                            successes.append(JobSuccess(job=job, warning_count=result))
                            continue
                        compiled[job] = result
                        if not job.multikey:
                            successes.append(JobSuccess(job=job, warning_count=result.warning_count))
                        key = (job.doc_tex_abs, job.variant)
                        companion, source = companions.get(key), ordinary.get(key)
                        if (companion is not None and companion not in failed
                                and companion not in packaging_started
                                and companion in compiled and source in compiled):
                            future = ex.submit(finish_multikey_job, ui, cfg, companion, source,
                                               compiled[companion])
                            fut_map[future] = (companion, True)
                            packaging_started.add(companion)
                if stop_requested["value"]:
                    break

            if stop_requested["value"]:
                for future in fut_map:
                    future.cancel()
                # Let executor shut down; any running jobs may finish, but we will exit politely.
                raise KeyboardInterrupt()

    finally:
        signal.signal(signal.SIGINT, old_int)

    return ParallelRunResult(
        successes=successes,
        failures=failures,
        total_warnings=sum(s.warning_count for s in successes),
    )
