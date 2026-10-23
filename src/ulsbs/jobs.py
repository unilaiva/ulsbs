# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Build compilation jobs and detect variant feasibility.
This file is part of the 'ulsbs' package.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re
from typing import List

from .config import Config
from .constants import (
    BASSCLEF_FNAMEPART,
    CHARANGO_FNAMEPART,
    LYRICSONLY_FNAMEPART,
    MULTIKEY_FNAMEPART,
    RESULT_JSON_SUBDIRNAME,
    RESULT_MULTIKEY_SUBDIRNAME,
    TEMP_DIRNAME,
)
from .util import read_text, regex_documentclass_ulsbs_songbook


@dataclass(frozen=True)
class Job:
    """One compilation job (document + variant + edition + paths)."""

    doc_tex_abs: Path
    doc_stem: str
    variant: str
    compile_dir: Path
    multikey: bool = False


def variant_possible_lyrics(doc_tex_abs: Path) -> bool:
    """Return True if doc uses ulsbs-songbook class (lyrics variant ok)."""
    text = read_text(doc_tex_abs)

    # Use shared matcher for \\documentclass[...]{ulsbs-songbook*}
    docclass_re = regex_documentclass_ulsbs_songbook()
    return docclass_re.search(text) is not None


def _extra_variant_enabled(doc_tex_abs: Path, target: str) -> bool:
    """Return True if the given extra variant is enabled via ULSBS-EXTRA-VARIANTS.

    Examples of supported syntax (whitespace/comments flexible):

        % ULSBS-EXTRA-VARIANTS: bassclef % comment
        %%%ULSBS-EXTRA-VARIANTS:bassclef,somevariant % comment
        % ... ULSBS-EXTRA-VARIANTS: bassclef, somevariant % comment
    """
    text = read_text(doc_tex_abs)

    # Use shared matcher for \\documentclass[...]{ulsbs-songbook*}
    docclass_re = regex_documentclass_ulsbs_songbook()
    if docclass_re.search(text) is None:
        return False

    pattern = re.compile(r"ULSBS-EXTRA-VARIANTS\s*:(?P<variants>[^%]*)")

    for line in text.splitlines():
        m = pattern.search(line)
        if not m:
            continue
        raw = m.group("variants")
        for item in raw.split(","):
            name = item.strip().lower()
            if not name:
                continue
            if name == target:
                return True
    return False


def variant_possible_charango(doc_tex_abs: Path) -> bool:
    """Detect marker enabling the charango variant."""
    return _extra_variant_enabled(doc_tex_abs, "charango")


def variant_possible_bassclef(doc_tex_abs: Path) -> bool:
    """Detect marker enabling the bass-clef variant."""
    return _extra_variant_enabled(doc_tex_abs, "bassclef")


def build_variant_basename(original_base: str, insert: str) -> str:
    """Insert variant token before paper suffix like _A5, if present."""
    m = re.search(r"(_A\d)", original_base)
    if not m:
        return original_base + insert
    idx = m.start()
    return original_base[:idx] + insert + original_base[idx:]


def build_job_basename(job: Job) -> str:
    """Append the edition marker to the complete ordinary variant basename.

    Variant tokens retain their position before the paper suffix; ``_MULTIKEY``
    follows that suffix so the ordinary stem remains the package's identity.
    """
    variant_marker = {
        "default": "",
        "lyrics": LYRICSONLY_FNAMEPART,
        "charango": CHARANGO_FNAMEPART,
        "bassclef": BASSCLEF_FNAMEPART,
    }[job.variant]
    basename = build_variant_basename(job.doc_stem, variant_marker)
    return basename + (MULTIKEY_FNAMEPART if job.multikey else "")


def build_job_queue(cfg: Config) -> List[Job]:
    """Plan selected editions and reject colliding publication paths before work.

    Multikey jobs reserve their mandatory range index, not a public full PDF or
    optional song JSON. Equal basenames in distinct result directories are valid.
    """
    project_root = cfg.runtime.project_paths.project_root
    jobs: List[Job] = []
    for doc in cfg.songbooks:
        base = doc.stem
        first_job = len(jobs)
        jobs.append(Job(doc, base, "default", project_root / TEMP_DIRNAME / base / "default"))
        if cfg.lyricbooks and variant_possible_lyrics(doc):
            jobs.append(Job(doc, base, "lyrics", project_root / TEMP_DIRNAME / base / "lyrics"))
        if cfg.extrainstrumentbooks and variant_possible_charango(doc):
            jobs.append(
                Job(doc, base, "charango", project_root / TEMP_DIRNAME / base / "charango")
            )
        if cfg.extrainstrumentbooks and variant_possible_bassclef(doc):
            jobs.append(
                Job(doc, base, "bassclef", project_root / TEMP_DIRNAME / base / "bassclef")
            )
        if cfg.multikey_books:
            standard_jobs = jobs[first_job:]
            jobs.extend(
                replace(
                    job,
                    multikey=True,
                    compile_dir=job.compile_dir.with_name(f"{job.variant}-multikey"),
                )
                for job in standard_jobs
                if job.variant != "lyrics"
            )
    # Distinct job locks do not protect a shared publication destination.
    outputs: dict[Path, Job] = {}
    for job in jobs:
        basename = build_job_basename(job)
        if job.multikey:
            # The mandatory index owns the generated range family; reserving its
            # path detects competing owners even when song JSON export is off.
            destinations = [Path(RESULT_MULTIKEY_SUBDIRNAME) / (basename + "_RANGES.json")]
        else:
            destinations = [Path(basename + ".pdf")]
            if cfg.json:
                destinations.append(Path(RESULT_JSON_SUBDIRNAME) / (basename + ".json"))
        for destination in destinations:
            if destination in outputs:
                previous = outputs[destination]
                raise ValueError(
                    f"Output filename collision for {str(destination)!r}: "
                    f"{previous.doc_tex_abs} ({previous.variant}, multikey={previous.multikey}) and "
                    f"{job.doc_tex_abs} ({job.variant}, multikey={job.multikey}). "
                    "Rename a source document or change the selected variants/editions."
                )
            outputs[destination] = job
    return jobs
