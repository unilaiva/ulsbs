# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Exercise publication integrity separately from PDF content preservation.

Use tiny blank PDFs and an empty finalized manifest so tests focus on index-last
installation, exact ownership, stable files, and rollback. Layer/resource and
appearance qualification belongs to the range-packager and TeX integration tests.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pikepdf

from ulsbs import resultlist
from ulsbs.config import Config
from ulsbs.constants import RESULT_TYPE_MAIN_PDF, RESULT_TYPE_MULTIKEY_JSON, RESULT_TYPE_MULTIKEY_PDF
from ulsbs.deploy import deploy_results
from ulsbs.multikey_publish import owned_ranges, publish_package, remove_legacy_outputs, remove_package


@unittest.skipUnless(shutil.which("qpdf"), "qpdf unavailable")
class PackagePublicationTests(unittest.TestCase):
    """Real qpdf packages with injected installation failures, never private music."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.canonical = self.root / "Book_A5.pdf"
        self.master = self.root / "Book_A5_MULTIKEY.pdf"
        with pikepdf.new() as pdf:
            for _ in range(3):
                pdf.add_blank_page(page_size=(300, 400))
            pdf.save(self.canonical, deterministic_id=True)
        shutil.copy2(self.canonical, self.master)
        self.manifest = {"has_multikey_info": True, "multikey_info": {
            "schema_version": 2, "layer_protocol": "ulsbs:transpose:v1",
            "coordinate_space": "pdf-user-space", "songs": [],
        }}

    def package(self, pages, directory="stage"):
        """Stage the same three-page book under a requested nominal page limit."""
        from ulsbs.multikey_ranges import package_ranges

        return package_ranges(self.master, self.canonical, self.manifest,
                              self.root / directory, max_pages=pages)

    def test_index_last_stale_inventory_cleanup_and_unchanged_files(self):
        first = self.package(1)
        output = self.root / "output"
        names = publish_package(first, output, self.canonical)
        unrelated = output / "other_RANGE_1-1.pdf"
        unrelated.write_bytes(b"unrelated")
        times = {name: (output / name).stat().st_mtime_ns for name in names}
        self.assertEqual(publish_package(first, output, self.canonical), names)
        self.assertEqual(times, {name: (output / name).stat().st_mtime_ns for name in names})
        final = self.package(2, "second")
        events = []
        import os
        original = os.replace

        def record(source, target):
            events.append(Path(target).name)
            return original(source, target)

        with patch("ulsbs.multikey_publish.os.replace", side_effect=record):
            final_names = publish_package(final, output, self.canonical)
        self.assertEqual(events[-1], final.name)
        self.assertEqual({path.name for path in output.iterdir()}, set(final_names) | {unrelated.name})
        self.assertEqual(unrelated.read_bytes(), b"unrelated")

    def test_installation_failure_rolls_back_existing_family(self):
        first = self.package(1)
        output = self.root / "output"
        names = publish_package(first, output, self.canonical)
        original_bytes = {name: (output / name).read_bytes() for name in names}
        final = self.package(2, "second")
        import os
        original = os.replace

        def fail_at_index(source, target):
            # Numeric staging names identify forward installation, not rollback.
            if Path(target).name == final.name and Path(source).name.isdigit():
                raise OSError("simulated installation failure")
            return original(source, target)

        with patch("ulsbs.multikey_publish.os.replace", side_effect=fail_at_index), \
                self.assertRaisesRegex(OSError, "simulated"):
            publish_package(final, output, self.canonical)
        self.assertEqual(original_bytes, {name: (output / name).read_bytes() for name in names})
        self.assertEqual(set(names), {path.name for path in output.iterdir()})

    def test_missing_or_corrupt_range_never_replaces_index(self):
        index = self.package(2)
        output = self.root / "output"
        names = publish_package(index, output, self.canonical)
        original = (output / index.name).read_bytes()
        (index.parent / names[0]).write_bytes(b"broken")
        with self.assertRaises(ValueError):
            publish_package(index, output, self.canonical)
        self.assertEqual((output / index.name).read_bytes(), original)

    def test_untrusted_previous_inventory_cannot_delete_neighbors(self):
        index = self.root / "Book_A5_MULTIKEY_RANGES.json"
        index.write_text(json.dumps({"format": "ulsbs:multikey-ranges", "ranges": [
            {"file": "../outside.pdf"}, {"file": "other_RANGE_1-2.pdf"},
            {"file": "Book_A5_MULTIKEY_RANGE_1-2.pdf"},
        ]}))
        self.assertEqual(owned_ranges(index), {"Book_A5_MULTIKEY_RANGE_1-2.pdf"})

    def test_owned_inventory_enforces_size_limit_before_parsing(self):
        index = self.root / "Book_A5_MULTIKEY_RANGES.json"
        name = "Book_A5_MULTIKEY_RANGE_1-2.pdf"
        data = json.dumps({"format": "ulsbs:multikey-ranges", "ranges": [{"file": name}]}).encode()
        index.write_bytes(data)
        with patch("ulsbs.multikey_publish.MULTIKEY_INDEX_MAX_BYTES", len(data)):
            self.assertEqual(owned_ranges(index), {name})
        with patch("ulsbs.multikey_publish.MULTIKEY_INDEX_MAX_BYTES", len(data) - 1), \
                patch("ulsbs.multikey_publish.json.loads", side_effect=AssertionError("Must not parse")):
            self.assertEqual(owned_ranges(index), set())

    def test_disabled_edition_cleanup_uses_previous_owned_inventory(self):
        index = self.package(2)
        output = self.root / "output"
        publish_package(index, output, self.canonical)
        unrelated = output / "notes.pdf"
        unrelated.write_bytes(b"not generated")
        remove_package(output / index.name)
        self.assertEqual(list(output.iterdir()), [unrelated])

    def test_legacy_cleanup_only_changes_the_final_edition_suffix(self):
        multikey, metadata = self.root / "multikey", self.root / "json"
        multikey.mkdir()
        metadata.mkdir()
        for canonical, legacy in (
            ("Book_A5", "Book_MULTIKEY_A5"),
            ("Book_CHARANGO_A5_LANDSCAPE", "Book_MULTIKEY_CHARANGO_A5_LANDSCAPE"),
            ("Book_BASSCLEF", "Book_MULTIKEY_BASSCLEF"),
            ("Book_A4_Appendix_A5", "Book_A4_Appendix_MULTIKEY_A5"),
        ):
            with self.subTest(canonical=canonical):
                (multikey / f"{legacy}.pdf").write_bytes(b"legacy")
                (metadata / f"{legacy}.json").write_bytes(b"legacy")
                neighbor = multikey / f"{canonical}_OTHER.pdf"
                neighbor.write_bytes(b"unrelated")
                remove_legacy_outputs(multikey, metadata, canonical)
                self.assertFalse((multikey / f"{legacy}.pdf").exists())
                self.assertFalse((metadata / f"{legacy}.json").exists())
                self.assertEqual(neighbor.read_bytes(), b"unrelated")

    def test_deployment_failure_restores_canonical_and_range_family_together(self):
        first = self.package(1)
        output, deployed_canonical = self.root / "output", self.root / "deployed.pdf"
        deployed_canonical.write_bytes(b"previous ordinary edition")
        names = publish_package(first, output, self.canonical)
        before = {name: (output / name).read_bytes() for name in names}
        second = self.package(2, "second")
        import os
        original = os.replace

        def fail_index(source, target):
            if Path(target).name == second.name and Path(source).name.isdigit():
                raise OSError("deployment error")
            return original(source, target)

        with patch("ulsbs.multikey_publish.os.replace", side_effect=fail_index), \
                self.assertRaisesRegex(OSError, "deployment error"):
            publish_package(second, output, self.canonical,
                            canonical_destination=deployed_canonical)
        self.assertEqual(deployed_canonical.read_bytes(), b"previous ordinary edition")
        self.assertEqual(before, {name: (output / name).read_bytes() for name in names})

    def test_deploy_preflights_and_routes_complete_package_before_metadata(self):
        result, deploy = self.root / "result", self.root / "deploy"
        result.mkdir()
        deploy.mkdir()
        shutil.copy2(self.canonical, result / self.canonical.name)
        index = self.package(2)
        names = publish_package(index, result / "multikey", self.canonical)
        cfg = replace(Config(), deploy_dir=deploy,
                      runtime=SimpleNamespace(in_container=False,
                                              project_paths=SimpleNamespace(result_dir=result)))
        resultlist.initialize(result, "test")
        self.addCleanup(lambda: resultlist.delete() if resultlist._initialized else None)
        # Deliberately put entry point before its canonical PDF in the inventory.
        resultlist.append_line(RESULT_TYPE_MULTIKEY_JSON, index.name)
        resultlist.append_line(RESULT_TYPE_MAIN_PDF, self.canonical.name)
        for name in names[:-1]:
            resultlist.append_line(RESULT_TYPE_MULTIKEY_PDF, name)
        with patch("ulsbs.deploy.MULTIKEY_INDEX_MAX_BYTES", index.stat().st_size - 1), \
                patch("ulsbs.deploy.json.loads", side_effect=AssertionError("Must not parse")), \
                self.assertRaisesRegex(ValueError, "MULTIKEY index exceeds"):
            deploy_results(Mock(), cfg)
        self.assertEqual(list(deploy.iterdir()), [])
        missing = result / "multikey" / names[0]
        saved = missing.read_bytes()
        missing.unlink()
        with self.assertRaises((ValueError, OSError)):
            deploy_results(Mock(), cfg)
        self.assertEqual(list(deploy.iterdir()), [])
        missing.write_bytes(saved)
        deploy_results(Mock(), cfg)
        self.assertEqual({path.name for path in (deploy / "multikey").iterdir()}, set(names))
        self.assertFalse((deploy / "multikey" / self.master.name).exists())
        self.assertEqual((deploy / self.canonical.name).read_bytes(), self.canonical.read_bytes())


if __name__ == "__main__":
    unittest.main()
