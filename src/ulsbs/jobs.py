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
    MULTIKEY_FNAMEPART,
    RESULT_JSON_SUBDIRNAME,
    RESULT_MULTIKEY_SUBDIRNAME,
    TEMP_DIRNAME,
)
from .util import read_text
from .variants import VARIANTS, available_variants, read_documentclass, validate_variant_names


@dataclass(frozen=True)
class Job:
    """One compilation job (document + variant + edition + paths)."""

    doc_tex_abs: Path
    doc_stem: str
    variant: str
    compile_dir: Path
    multikey: bool = False
    is_songbook: bool = False

    @property
    def supports_multikey(self) -> bool:
        """Whether the source and variant support a companion, regardless of build settings."""
        return self.is_songbook and "multikey" in VARIANTS[self.variant].editions


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
    variant_marker = VARIANTS[job.variant].filename_marker
    basename = build_variant_basename(job.doc_stem, variant_marker)
    return basename + (MULTIKEY_FNAMEPART if job.multikey else "")


def build_job_queue(cfg: Config) -> List[Job]:
    """Plan selected editions and reject colliding publication paths before work.

    Multikey jobs reserve their mandatory range index, not a public full PDF or
    optional song JSON. Equal basenames in distinct result directories are valid.
    """
    project_root = cfg.runtime.project_paths.project_root
    jobs: List[Job] = []
    requested = None if cfg.variants == "all" else validate_variant_names(
        ",".join(cfg.variants)
    )
    matched: set[str] = set()
    for doc in cfg.songbooks:
        base = doc.stem
        first_job = len(jobs)
        try:
            text = read_text(doc)
            available = available_variants(text)
            declaration = read_documentclass(text)
        except ValueError as error:
            raise ValueError(f"{doc}: {error}") from error
        selected = [name for name in available if requested is None or name in requested]
        if requested is not None and len(cfg.songbooks) == 1:
            unavailable = set(requested) - set(available)
            if unavailable:
                raise ValueError(f"{doc}: unavailable variants: {', '.join(sorted(unavailable))}")
        # Declaration order is authoritative except that selected default is first.
        selected.sort(key=lambda name: name != "default")
        matched.update(selected)
        songbook = declaration is not None and declaration.name.startswith("ulsbs-songbook")
        jobs.extend(Job(doc, base, name, project_root / TEMP_DIRNAME / base / name,
                        is_songbook=songbook) for name in selected)
        if cfg.multikey_books:
            standard_jobs = jobs[first_job:]
            jobs.extend(
                replace(
                    job,
                    multikey=True,
                    compile_dir=job.compile_dir.with_name(f"{job.variant}-multikey"),
                )
                for job in standard_jobs
                if job.supports_multikey
            )
    if requested is not None and (unmatched := set(requested) - matched):
        raise ValueError(f"Requested variants available in none of the selected books: {', '.join(sorted(unmatched))}")
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
