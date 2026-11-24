# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Install complete MULTIKEY families and retire only their owned outputs.

``multikey_ranges`` stages and semantically qualifies PDFs; this module checks
index/file integrity again at the publication boundary, installs the index last,
and handles rollback and previous-inventory cleanup. It does not compile PDFs,
write build result-list records, or update book metadata; callers own those steps.

Replacement is atomic per file, not across an entire edition. Live HTTP readers
still need an atomic edition-directory deployment for a consistent snapshot.
"""

from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from .constants import MULTIKEY_INDEX_MAX_BYTES
from .resultlist import file_sha256
from .util import files_are_identical


def remove_legacy_outputs(multikey_dir: Path, json_dir: Path, canonical_stem: str) -> None:
    """Remove this edition's former full layered PDFs and companion book JSON.

    ``canonical_stem`` is the ordinary filename without ``.pdf``. Recognize only
    its final instrument/paper suffix when reconstructing the old infix name,
    e.g. ``Book_MULTIKEY_CHARANGO_A5``, as well as the appended master name.
    Missing files are harmless; never glob the directory or remove ordinary PDFs.
    """
    marker = re.search(r"(?:_(?:CHARANGO|BASSCLEF))?(?:_A\d(?:_(?:LANDSCAPE|PORTRAIT))?)?$",
                       canonical_stem)
    offset = marker.start() if marker else len(canonical_stem)
    legacy = canonical_stem[:offset] + "_MULTIKEY" + canonical_stem[offset:]
    for stem in (legacy, canonical_stem + "_MULTIKEY"):
        (multikey_dir / f"{stem}.pdf").unlink(missing_ok=True)
        (json_dir / f"{stem}.json").unlink(missing_ok=True)


def owned_ranges(index_path: Path) -> set[str]:
    """Recover safe cleanup candidates from the previous edition's index.

    Require an expected ``*_MULTIKEY_RANGES.json`` basename and accept only range
    basenames belonging to that exact stem. Do not require valid old hashes:
    the canonical PDF may already have been replaced, but ownership still matters.
    Unreadable, unusable, or oversized indices conservatively own no files;
    individual candidate entries are filtered independently. An invalid
    entry-point filename itself raises ``ValueError``.
    """
    if not index_path.name.endswith("_MULTIKEY_RANGES.json"):
        raise ValueError("Not a MULTIKEY range index filename")
    stem = index_path.name.removesuffix("_RANGES.json")
    try:
        # Same raw UTF-8 size bound as protocol v1; cleanup must not parse an
        # unbounded prior inventory merely to discover filenames to delete.
        if index_path.stat().st_size > MULTIKEY_INDEX_MAX_BYTES:
            return set()
        data = json.loads(index_path.read_text(encoding="utf-8"))
        if data.get("format") != "ulsbs:multikey-ranges":
            return set()
        pattern = re.compile(re.escape(stem) + r"_RANGE_[1-9][0-9]*-[1-9][0-9]*\.pdf")
        return {entry["file"] for entry in data["ranges"]
                if isinstance(entry, dict) and isinstance(entry.get("file"), str)
                and pattern.fullmatch(entry["file"])}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return set()


def publish_package(index_path: Path, destination: Path, canonical_path: Path, *,
                    canonical_destination: Path | None = None,
                    metadata: tuple[Path, Path] | None = None,
                    expected: dict[Path, str] | None = None) -> list[str]:
    """Preflight, install, and clean one indexed family, with rollback on failure.

    ``index_path`` and its sibling ranges are the completed staging/source family.
    ``canonical_path`` explicitly identifies the ordinary PDF whose exact bytes
    must match the index; it need not be in that directory. ``destination`` is
    the result/deploy multikey directory. Optionally install the ordinary PDF at
    ``canonical_destination`` first, sharing the family's rollback boundary.

    Validate coverage, names, sizes, and hashes before changing destinations.
    Keep byte-identical files untouched. Otherwise copy into a destination-local
    temporary directory and replace files, installing ranges before the index.
    Retire obsolete ranges from the prior safe ownership inventory only, never
    neighboring files. Backups also cover these deletions and the optional
    canonical replacement; exceptions, including interrupts, trigger rollback.

    Return the complete family basenames in range order followed by the index,
    including byte-identical files skipped during installation but excluding
    the optional ordinary PDF.
    Validation and filesystem exceptions propagate to the caller. This does not
    provide multi-file atomic visibility to concurrent readers. Optional ordinary
    metadata is installed last in the same rollback operation. With run receipts,
    verify staged bytes against the expected digests before replacing any file.
    """
    from .multikey_ranges import validate_index

    index_bytes = index_path.read_bytes()
    if expected is not None and hashlib.sha256(index_bytes).hexdigest() != expected[index_path]:
        raise ValueError(f"{index_path.name} changed while preparing deployment")
    data = json.loads(index_bytes)
    validate_index(data, index_path, canonical_path)
    obsolete = owned_ranges(destination / index_path.name)
    names = [entry["file"] for entry in data["ranges"]] + [index_path.name]
    operations = [(index_path.parent / name, destination / name) for name in names]
    if canonical_destination is not None:
        # Deploy the ordinary PDF and its family as one rollback boundary.
        operations.insert(0, (canonical_path, canonical_destination))
    if metadata is not None:
        operations.append(metadata)
    if expected is not None:
        expected = {**expected, **{index_path.parent / entry["file"]: entry["sha256"]
                                  for entry in data["ranges"]}}
    install_files(operations, obsolete=tuple(destination / name for name in sorted(obsolete - set(names))),
                  expected=expected)
    return names


def install_files(operations: list[tuple[Path, Path]], *, obsolete: tuple[Path, ...] = (),
                  expected: dict[Path, str] | None = None) -> None:
    """Install one edition in order, rolling back replacements and removals on error."""
    if not operations:
        return
    installed = []
    with ExitStack() as stack:
        staging = {}

        def stage_dir(parent: Path) -> Path:
            if parent not in staging:
                parent.mkdir(parents=True, exist_ok=True)
                staging[parent] = Path(stack.enter_context(tempfile.TemporaryDirectory(
                    prefix=".ulsbs-package-", dir=parent)))
            return staging[parent]

        staged = []
        backups = {}
        for number, (source, target) in enumerate(operations):
            digest = (expected or {}).get(source)
            if target.is_file() and (file_sha256(target) == digest if digest is not None
                                     else files_are_identical(source, target)):
                continue
            candidate = stage_dir(target.parent) / str(number)
            shutil.copy2(source, candidate)
            if digest is not None and file_sha256(candidate) != digest:
                raise ValueError(f"{source.name} changed while staging deployment")
            staged.append((candidate, target))
        try:
            for number, (candidate, target) in enumerate(staged):
                if target.exists():
                    backup = candidate.with_name(f"old-{number}")
                    shutil.copy2(target, backup)
                    backups[target] = backup
                os.replace(candidate, target)
                installed.append(target)
            for number, target in enumerate(obsolete):
                if target.exists():
                    backup = stage_dir(target.parent) / f"obsolete-{number}"
                    shutil.copy2(target, backup)
                    backups[target] = backup
                    target.unlink()
                    installed.append(target)
        except BaseException:
            for target in reversed(installed):
                if target in backups:
                    os.replace(backups[target], target)
                else:
                    target.unlink(missing_ok=True)
            raise


def remove_package(index_path: Path) -> None:
    """Retire an explicitly disabled edition without sweeping adjacent outputs.

    Read its safe ownership inventory before removing the entry point, then
    unlink those ranges. Missing files are ignored. An unreadable old inventory
    may leave orphan ranges rather than risking deletion of unrelated files.
    Ordinary PDFs and legacy companions are handled separately by the caller.
    """
    names = owned_ranges(index_path)
    index_path.unlink(missing_ok=True)
    for name in names:
        (index_path.parent / name).unlink(missing_ok=True)
