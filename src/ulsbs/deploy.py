# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Deploy compiled artifacts to the deploy directory.
This file is part of the 'ulsbs' package.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .config import Config

from .constants import (
    MULTIKEY_INDEX_MAX_BYTES,
    RESULTLIST_SEPARATOR,
    RESULT_TYPE_MAIN_PDF,
    RESULT_TYPE_MULTIKEY_PDF,
    RESULT_TYPE_MULTIKEY_JSON,
    RESULT_TYPE_PRINTOUT_PDF,
    RESULT_TYPE_JSON,
    RESULT_TYPE_EDITION,
    RESULT_TYPE_EDITION_MULTIKEY,
    RESULT_TYPE_IMAGE,
    RESULT_TYPE_MIDIDIR,
    RESULT_TYPE_AUDIODIR,
    RESULT_TYPE_COMMONICON,
    RESULT_TYPE_COMMONSOCIAL,
    RESULT_TYPE_COMMONMETADATA,
    RESULT_TYPE_COMMONOTHER,
    RESULT_PRINTOUT_SUBDIRNAME,
    RESULT_MULTIKEY_SUBDIRNAME,
    RESULT_JSON_SUBDIRNAME,
    RESULT_IMAGE_SUBDIRNAME,
    RESULT_MIDI_SUBDIRNAME,
    RESULT_AUDIO_SUBDIRNAME,
    DEPLOY_IMAGE_SUBDIRNAME,
    DEPLOY_PRINTOUT_SUBDIRNAME,
    DEPLOY_MULTIKEY_SUBDIRNAME,
    DEPLOY_JSON_SUBDIRNAME,
    DEPLOY_MIDI_SUBDIRNAME,
    DEPLOY_AUDIO_SUBDIRNAME,
    DEPLOY_COMMONICON_SUBDIRNAME,
    DEPLOY_COMMONSOCIAL_SUBDIRNAME,
    DEPLOY_COMMONMETADATA_SUBDIRNAME,
    DEPLOY_COMMONOTHER_SUBDIRNAME,
    NODEPLOY_FNAMEPART,
)
import ulsbs.resultlist as resultlist
from .ui import UI
from .util import ensure_dir, files_are_identical, sync_tree
from .variants import VARIANTS


def _validate_package(name: str, result_dir: Path, records: set[str]) -> dict:
    """Validate an advertised multikey family and its exact canonical PDF."""
    from .multikey_ranges import validate_index

    if Path(name).name != name or not name.endswith("_MULTIKEY_RANGES.json"):
        raise ValueError(f"Invalid MULTIKEY entry point in inventory: {name}")
    source = result_dir / RESULT_MULTIKEY_SUBDIRNAME / name
    if source.stat().st_size > MULTIKEY_INDEX_MAX_BYTES:
        raise ValueError(f"MULTIKEY index exceeds {MULTIKEY_INDEX_MAX_BYTES:,} bytes")
    data = json.loads(source.read_text(encoding="utf-8"))
    canonical_name = name.removesuffix("_MULTIKEY_RANGES.json") + ".pdf"
    if f"{RESULT_TYPE_MAIN_PDF}{RESULTLIST_SEPARATOR}{canonical_name}" not in records:
        raise ValueError(f"MULTIKEY canonical PDF missing from inventory: {canonical_name}")
    validate_index(data, source, result_dir / canonical_name)
    for entry in data["ranges"]:
        if f"{RESULT_TYPE_MULTIKEY_PDF}{RESULTLIST_SEPARATOR}{entry['file']}" not in records:
            raise ValueError(f"MULTIKEY range missing from inventory: {entry['file']}")
    return data


_EDITION_ARTIFACTS = {RESULT_TYPE_MAIN_PDF, RESULT_TYPE_JSON, RESULT_TYPE_MULTIKEY_JSON,
                      RESULT_TYPE_MULTIKEY_PDF}


def _deploy_checked_editions(ui: UI, cfg: Config, lines: list[str]) -> None:
    """Deploy verified edition groups without borrowing artifacts from earlier runs."""
    from .multikey_publish import install_files, publish_package, remove_legacy_outputs

    result_dir = cfg.runtime.project_paths.result_dir
    deploy_dir = cfg.deploy_dir
    records = set(lines)
    receipts = resultlist.edition_records(lines, RESULT_TYPE_EDITION)
    companions = resultlist.edition_records(lines, RESULT_TYPE_EDITION_MULTIKEY)
    stems = set()
    for line in lines:
        kind, _, name = line.partition(RESULTLIST_SEPARATOR)
        if kind not in _EDITION_ARTIFACTS:
            continue
        if Path(name).name != name or not name:
            ui.nodeploy_line(f"{name!r} not deployed: invalid edition filename")
        elif kind == RESULT_TYPE_MAIN_PDF and name.endswith(".pdf"):
            stems.add(name.removesuffix(".pdf"))
        elif kind == RESULT_TYPE_JSON and name.endswith(".json"):
            stems.add(name.removesuffix(".json"))
        elif kind == RESULT_TYPE_MULTIKEY_JSON and name.endswith("_MULTIKEY_RANGES.json"):
            stems.add(name.removesuffix("_MULTIKEY_RANGES.json"))
        elif kind == RESULT_TYPE_MULTIKEY_PDF:
            match = re.fullmatch(r"(.+)_MULTIKEY_RANGE_[1-9]\d*-[1-9]\d*\.pdf", name)
            if match:
                stems.add(match[1])
        else:
            ui.nodeploy_line(f"{name} not deployed: invalid edition filename")

    for stem in sorted(stems):
        pdf_name = stem + ".pdf"
        json_name = stem + ".json"
        index_name = stem + "_MULTIKEY_RANGES.json"
        if NODEPLOY_FNAMEPART in pdf_name:
            ui.nodeploy_line(f"{pdf_name} not deployed due to filename")
            continue
        pdf = result_dir / pdf_name
        index = result_dir / RESULT_MULTIKEY_SUBDIRNAME / index_name
        metadata = None
        has_json = f"{RESULT_TYPE_JSON}{RESULTLIST_SEPARATOR}{json_name}" in records
        has_multikey = f"{RESULT_TYPE_MULTIKEY_JSON}{RESULTLIST_SEPARATOR}{index_name}" in records
        expected = {}

        def verify(path: Path, digest: str | None) -> None:
            if not digest or resultlist.file_sha256(path) != digest:
                raise ValueError(f"{path.name} does not match this run's edition receipt")
            expected[path] = digest

        try:
            if f"{RESULT_TYPE_MAIN_PDF}{RESULTLIST_SEPARATOR}{pdf_name}" not in records:
                raise ValueError("ordinary PDF missing from this run's inventory")
            receipt = receipts.get(pdf_name)
            if receipt is None or "variant" not in receipt:
                raise ValueError("no edition receipt in this run's inventory; rebuild before deploying")
            variant = receipt["variant"]
            if variant is not None and (not isinstance(variant, str) or variant not in VARIANTS):
                raise ValueError("unknown variant in this run's edition receipt")
            missing = []
            if cfg.require_json_for_pdf_deploy and variant is not None and not has_json:
                missing.append("ordinary JSON")
            if (cfg.require_multikey_for_pdf_deploy and variant is not None
                    and "multikey" in VARIANTS[variant].editions and not has_multikey):
                missing.append("multikey package")
            if missing:
                raise ValueError(f"required {' and '.join(missing)} missing from this run's inventory")
            verify(pdf, receipt.get("pdf_sha256"))
            if has_multikey:
                companion = companions.get(pdf_name, {})
                verify(index, companion.get("index_sha256"))
                _validate_package(index_name, result_dir, records)
            if has_json:
                source = result_dir / RESULT_JSON_SUBDIRNAME / json_name
                verify(source, (companion if has_multikey else receipt).get("json_sha256"))
                metadata = (source, deploy_dir / DEPLOY_JSON_SUBDIRNAME / json_name)
        except (OSError, ValueError, TypeError, KeyError) as error:
            ui.nodeploy_line(f"{pdf_name} not deployed: {error}")
            continue

        if has_multikey:
            publish_package(index, deploy_dir / DEPLOY_MULTIKEY_SUBDIRNAME, pdf,
                            canonical_destination=deploy_dir / pdf_name, metadata=metadata,
                            expected=expected)
            remove_legacy_outputs(deploy_dir / DEPLOY_MULTIKEY_SUBDIRNAME,
                                  deploy_dir / DEPLOY_JSON_SUBDIRNAME, stem)
            ui.deploy_line(f"{DEPLOY_MULTIKEY_SUBDIRNAME}/{index_name}")
        else:
            operations = [(pdf, deploy_dir / pdf_name)]
            if metadata is not None:
                operations.append(metadata)
            install_files(operations, expected=expected)
            ui.deploy_line(pdf_name)
        if metadata is not None:
            ui.deploy_line(f"{DEPLOY_JSON_SUBDIRNAME}/{json_name}")


def deploy_results(ui: UI, cfg: Config) -> None:
    """Deploy inventoried results under the selected PDF deployment requirements.

    Strict mode filters incomplete editions individually and installs each complete
    group together. Otherwise retain the existing all-package preflight and copy
    order. Neither mode gives concurrent readers multi-file atomic visibility.
    """
    result_dir = cfg.runtime.project_paths.result_dir
    deploy_dir = cfg.deploy_dir

    if cfg.runtime.in_container:
        return

    if not resultlist.exists():
        ui.nodeploy_line("Nothing to deploy!")
        return

    if not deploy_dir.exists():
        ui.nodeploy_line(
            f"Results NOT copied to deploy directory. Directory not found: {str(deploy_dir)}"
        )
        return

    # Append common files to the deploy list if not there already, with abs path
    for icon in sorted(cfg.common_deploy_icons):
        resultlist.append_line_if_missing(RESULT_TYPE_COMMONICON, icon)
    for social in sorted(cfg.common_deploy_social_images):
        resultlist.append_line_if_missing(RESULT_TYPE_COMMONSOCIAL, social)
    for md in sorted(cfg.common_deploy_metadata):
        resultlist.append_line_if_missing(RESULT_TYPE_COMMONMETADATA, md)
    for oth in sorted(cfg.common_deploy_other):
        resultlist.append_line_if_missing(RESULT_TYPE_COMMONOTHER, oth)

    lines = resultlist.lines()
    records = set(lines)
    packages = {}
    package_canonicals = set()
    checked = not cfg.deploy_common and (cfg.require_multikey_for_pdf_deploy
                                         or cfg.require_json_for_pdf_deploy)
    if checked:
        _deploy_checked_editions(ui, cfg, lines)
    elif not cfg.deploy_common:
        # With neither requirement enabled, preserve the existing all-package
        # preflight before changing any deployed output.
        for line in lines:
            if not line.startswith(RESULT_TYPE_MULTIKEY_JSON + RESULTLIST_SEPARATOR):
                continue
            name = line.split(RESULTLIST_SEPARATOR, 1)[1]
            if NODEPLOY_FNAMEPART in name:
                continue
            data = _validate_package(name, result_dir, records)
            canonical_name = data["canonical"]["file"]
            packages[name] = data
            package_canonicals.add(canonical_name)

    # Independent PDFs precede packages; package canonicals are deferred into
    # publish_package's rollback boundary. Referring metadata goes last because
    # parallel compilation makes the original inventory order unreliable.
    def publication_order(line):
        kind = line.split(RESULTLIST_SEPARATOR, 1)[0]
        return 2 if kind in (RESULT_TYPE_JSON, RESULT_TYPE_COMMONMETADATA) else (
            1 if kind == RESULT_TYPE_MULTIKEY_JSON else 0)

    skipped = 0
    for line in sorted(lines, key=publication_order):
        if not line.strip():
            continue
        try:
            ftype, fname = line.split(RESULTLIST_SEPARATOR, 1)
        except ValueError:
            ui.warning_line(f"Skipping deformed result list line: {line}")
            continue

        if ftype in (RESULT_TYPE_EDITION, RESULT_TYPE_EDITION_MULTIKEY) or (
            checked and ftype in _EDITION_ARTIFACTS
        ):
            continue

        if NODEPLOY_FNAMEPART in fname:
            ui.nodeploy_line(f"{fname} not deployed due to filename")
            continue

        if cfg.deploy_common and ftype not in (
            RESULT_TYPE_COMMONICON,
            RESULT_TYPE_COMMONSOCIAL,
            RESULT_TYPE_COMMONMETADATA,
            RESULT_TYPE_COMMONOTHER,
        ):
            continue

        if ftype == RESULT_TYPE_MAIN_PDF:
            if fname in package_canonicals:
                # Installed with its range family so both roll back together.
                continue
            src = result_dir / fname
            dst_dir = deploy_dir
        elif ftype == RESULT_TYPE_MULTIKEY_PDF:
            # Ranges are installed only as a complete validated family. Legacy
            # inventories must never deploy the old full layered PDFs.
            continue
        elif ftype == RESULT_TYPE_MULTIKEY_JSON:
            from .multikey_publish import publish_package, remove_legacy_outputs

            source = result_dir / RESULT_MULTIKEY_SUBDIRNAME / fname
            data = packages[fname]
            canonical_name = data["canonical"]["file"]
            # The publisher installs the canonical and ranges before the index,
            # restoring replaced files on failure rather than exposing a new index
            # that advertises a partly copied family.
            publish_package(source, deploy_dir / DEPLOY_MULTIKEY_SUBDIRNAME,
                            result_dir / canonical_name,
                            canonical_destination=deploy_dir / canonical_name)
            remove_legacy_outputs(deploy_dir / DEPLOY_MULTIKEY_SUBDIRNAME,
                                  deploy_dir / DEPLOY_JSON_SUBDIRNAME,
                                  Path(data["canonical"]["file"]).stem)
            ui.deploy_line(f"{DEPLOY_MULTIKEY_SUBDIRNAME}/{fname}")
            continue
        elif ftype == RESULT_TYPE_PRINTOUT_PDF:
            src = result_dir / RESULT_PRINTOUT_SUBDIRNAME / fname
            dst_dir = deploy_dir / DEPLOY_PRINTOUT_SUBDIRNAME
        elif ftype == RESULT_TYPE_JSON:
            src = result_dir / RESULT_JSON_SUBDIRNAME / fname
            dst_dir = deploy_dir / DEPLOY_JSON_SUBDIRNAME
        elif ftype == RESULT_TYPE_IMAGE:
            src = result_dir / RESULT_IMAGE_SUBDIRNAME / fname
            dst_dir = deploy_dir / DEPLOY_IMAGE_SUBDIRNAME
        elif ftype == RESULT_TYPE_COMMONICON:
            src = Path(fname)
            dst_dir = deploy_dir / DEPLOY_COMMONICON_SUBDIRNAME
        elif ftype == RESULT_TYPE_COMMONSOCIAL:
            src = Path(fname)
            dst_dir = deploy_dir / DEPLOY_COMMONSOCIAL_SUBDIRNAME
        elif ftype == RESULT_TYPE_COMMONMETADATA:
            src = Path(fname)
            dst_dir = deploy_dir / DEPLOY_COMMONMETADATA_SUBDIRNAME
        elif ftype == RESULT_TYPE_COMMONOTHER:
            src = Path(fname)
            dst_dir = deploy_dir / DEPLOY_COMMONOTHER_SUBDIRNAME
        elif ftype == RESULT_TYPE_MIDIDIR:
            src = result_dir / RESULT_MIDI_SUBDIRNAME / fname
            dst_dir = deploy_dir / DEPLOY_MIDI_SUBDIRNAME / fname
        elif ftype == RESULT_TYPE_AUDIODIR:
            src = result_dir / RESULT_AUDIO_SUBDIRNAME / fname
            dst_dir = deploy_dir / DEPLOY_AUDIO_SUBDIRNAME / fname
        else:
            continue

        if not src.exists():
            ui.warning_line(f"Could not access {src} for deployment")
            continue

        ensure_dir(dst_dir)

        # dir
        if src.is_dir():
            # Synchronize directory contents without overwriting identical files
            # and remove entries in the destination that no longer exist in the
            # source tree.
            skipped += sync_tree(src, dst_dir)
            ui.deploy_line(f"{dst_dir.parent.name}/{dst_dir.name}/")
            continue

        # single file
        dst = dst_dir / src.name
        if dst.exists():
            try:
                if files_are_identical(src, dst):
                    skipped += 1
                    continue
            except Exception:
                pass
        shutil.copy2(src, dst)

        try:
            display_path = dst.relative_to(deploy_dir)
        except ValueError:
            display_path = dst
        ui.deploy_line(str(display_path))

    if skipped:
        ui.nodeploy_line(
            f"Skipped {skipped} existing identical file{'s' if skipped != 1 else ''} during deploy"
        )

    resultlist.delete()
