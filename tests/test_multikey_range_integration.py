# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Qualify real TeX shipout metadata and selected-content extraction end to end.

Generic public fixtures exercise pagination and late content without private
scores. Compare concatenated range raster/text evidence with the unchanged
layered master for default and non-default selections, not PDF serialization
bytes. The separate font integration tests exercise all twelve key alternatives.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from test_tex_integration import compile_fixture


@unittest.skipUnless(all(shutil.which(tool) for tool in
                         ("lualatex", "qpdf", "pdftoppm", "pdftotext")), "PDF tools unavailable")
class TypesetRangeIntegrationTests(unittest.TestCase):
    """Preserve global metadata while rendering each range independently."""

    def test_stale_aux_property_streams_settle_on_fourth_pass(self):
        import pikepdf

        from ulsbs import pipeline
        from ulsbs.config import Config
        from ulsbs.jobs import Job
        from ulsbs.multikey_ranges import _dependencies, check_pdf_property_resources
        from test_tex_integration import TEX_ASSETS

        fixture = "multikey-resource-convergence"
        artifacts = {f"{fixture}.{suffix}": None for suffix in
                     ("tex", "aux", "out", "sxc", "pdf", "log", "ulsbs-multikey.json")}
        output, stale_bytes = compile_fixture(fixture, passes=3, artifacts=artifacts)
        self.assertIn("ULSBS-RESOURCE-RUN:3", output)
        aux = artifacts[f"{fixture}.aux"].decode()
        self.assertIn(r"\gdef\ResourceRun{3}", aux)
        with pikepdf.open(io.BytesIO(stale_bytes)) as pdf:
            properties = pdf.pages[0].Resources.Properties
            streams = [value for _, value in properties.items() if isinstance(value, pikepdf.Stream)]
            self.assertTrue(streams, "pass 3 must reproduce a property pointing to a stream")
            self.assertTrue(all(b"public dummy stream two" in stream.read_bytes() for stream in streams))
            # The newly written aux already has correct OCG numbers. It is the
            # PDF's previous-pass property cache, not the current aux, that is bad.
            refs = re.findall(r"\\ocgxii@newkey\{ocgx2\.ocg\.[^}]+\}\{(\d+) 0 R\}", aux)
            self.assertEqual(len(refs), 12)
            for ref in refs:
                self.assertEqual(pdf.get_object((int(ref), 0)).Type, pikepdf.Name.OCG)
            with self.assertRaisesRegex(ValueError, "Invalid optional content resource"):
                _dependencies(pdf)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, contents in artifacts.items():
                self.assertIsNotNone(contents, name)
                (root / name).write_bytes(contents)
            # Only the last pass is relevant; the helper's combined stdout also
            # contains deliberately unsettled first-pass reference diagnostics.
            (root / "06_lualatex-pass3.log").write_bytes(artifacts[f"{fixture}.log"])
            master = root / f"{fixture}.pdf"
            with self.assertRaisesRegex(ValueError, "property.*stream"):
                check_pdf_property_resources(master)
            cache = root / "texmf-cache"
            cache.mkdir()
            env = dict(os.environ, TEXINPUTS=f"{TEX_ASSETS}//{os.pathsep}",
                       TEXMFVAR=str(cache), TEXMFCACHE=str(cache))
            job = Job(root / f"{fixture}.tex", fixture, "default", root, multikey=True)
            last_log, step = pipeline.step_lualatex_convergence(
                Mock(), Config(), job, fixture, env, root / "06_lualatex-pass3.log", 7,
            )
            self.assertEqual((last_log.name, step), ("07_lualatex-pass4.log", 8))
            self.assertIn("ULSBS-RESOURCE-RUN:4", last_log.read_text())
            self.assertFalse((root / "08_lualatex-pass5.log").exists())
            self.assertIn(r"\gdef\ResourceRun{4}", (root / f"{fixture}.aux").read_text())
            check_pdf_property_resources(master)
            with pikepdf.open(master) as pdf:
                dependencies = _dependencies(pdf)
                self.assertEqual(len(dependencies), 12)
                self.assertEqual(set().union(*dependencies.values()), {0})
                declared = {group.objgen for group in pdf.Root.OCProperties.OCGs}
                for _, value in pdf.pages[0].Resources.Properties.items():
                    self.assertIsInstance(value, pikepdf.Dictionary)
                    self.assertIn(value.objgen, declared)
            manifest = json.loads((root / f"{fixture}.ulsbs-multikey.json").read_text())
            self.assertEqual([song["song_id"] for song in manifest["multikey_info"]["songs"]],
                             ["public-resource-song"])

        output, settled_bytes = compile_fixture(fixture, passes=4)
        self.assertIn("ULSBS-RESOURCE-RUN:4", output)
        with pikepdf.open(io.BytesIO(settled_bytes)) as pdf:
            self.assertEqual(len(_dependencies(pdf)), 12)
            self.assertTrue(all(isinstance(value, pikepdf.Dictionary)
                                for _, value in pdf.pages[0].Resources.Properties.items()))

    def test_long_header_preserves_canonical_targets_without_adding_a_line(self):
        import pikepdf

        from ulsbs.multikey_ranges import (
            _dependencies, _destinations, _links, package_ranges, validate_index,
        )
        from test_pdf_transposition_layers import PdfStructure, rendered_pages, words_and_geometry

        fixture = "multikey-header-layout"
        artifacts = {f"{fixture}.ulsbs-multikey.json": None}
        output, master_bytes = compile_fixture(fixture, passes=3, artifacts=artifacts)
        ordinary_output, ordinary_bytes = compile_fixture(fixture, passes=3, multikey=False)
        for log in (output, ordinary_output):
            self.assertNotIn("Missing or invalid song id", log)
        self.assertIsNotNone(artifacts[f"{fixture}.ulsbs-multikey.json"])
        manifest = json.loads(artifacts[f"{fixture}.ulsbs-multikey.json"])
        songs = manifest["multikey_info"]["songs"]
        self.assertEqual([song["song_id"] for song in songs],
                         ["wide-chorded", "medium-chorded"])
        # Pin the normal, non-overfull headers' pre-fix right-edge UI positions.
        # Moving the anchor into the title must not move it to the title's end.
        for song, page, x in zip(songs, (5, 6), (339.32280012, 276.96058908), strict=True):
            self.assertEqual(song["page_index"], page)
            self.assertEqual(song["layer_page_indices"], [page])
            self.assertAlmostEqual(song["anchor"]["x"], x, delta=0.02)
            self.assertAlmostEqual(song["anchor"]["y"], 549.3159806, delta=0.02)

        ordinary_words = words_and_geometry(ordinary_bytes)
        master_words = words_and_geometry(master_bytes)
        # The original failure preserved text and page assignment, but shifted
        # lyrics and named targets by 2 TeX pt (about 1.99 PDF user-space units).
        self.assertEqual([word[:2] for word in master_words],
                         [word[:2] for word in ordinary_words])
        with pikepdf.open(io.BytesIO(master_bytes)) as master, pikepdf.open(
                io.BytesIO(ordinary_bytes)) as ordinary:
            self.assertEqual(len(master.pages), 7)
            self.assertEqual(len(ordinary.pages), 7)
            master_names, ordinary_names = _destinations(master), _destinations(ordinary)
            self.assertEqual(set(master_names), set(ordinary_names))
            self.assertEqual({name: value[0] for name, value in master_names.items()},
                             {name: value[0] for name, value in ordinary_names.items()})
            for song_id in ("wide-long", "medium-long", "narrow-long", "wide-short",
                            "medium-tagged", "wide-chorded", "medium-chorded"):
                self.assertIn(f"after-{song_id}", ordinary_names)
            dependencies = _dependencies(master)
            self.assertTrue(dependencies)
            self.assertEqual(set().union(*dependencies.values()), {5, 6})
            _links(ordinary, ordinary_names)
            _links(master, ordinary_names, master_names)
            self.assertEqual(master_names, ordinary_names)
        self.assertEqual(master_words, ordinary_words)
        ordinary_render = rendered_pages(ordinary_bytes)
        self.assertEqual(rendered_pages(master_bytes), ordinary_render)
        structure = PdfStructure(master_bytes)
        default = structure.selected_pdf(master_bytes, {1: 0, 2: 0})
        self.assertEqual(words_and_geometry(default), ordinary_words)
        self.assertEqual(rendered_pages(default), ordinary_render)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            master, ordinary = root / "Header_MULTIKEY.pdf", root / "Header.pdf"
            master.write_bytes(master_bytes)
            ordinary.write_bytes(ordinary_bytes)
            index_path = package_ranges(master, ordinary, manifest, root / "stage", max_pages=2)
            index = json.loads(index_path.read_text())
            validate_index(index, index_path, ordinary)
            self.assertEqual(index["manifest"], manifest)
            range_render = []
            for entry in index["ranges"]:
                range_render.extend(rendered_pages((index_path.parent / entry["file"]).read_bytes()))
            self.assertEqual(range_render, ordinary_render)

    def test_final_shipout_manifest_and_layer_alternatives_survive_ranges(self):
        from ulsbs.multikey_ranges import package_ranges, validate_index
        from test_pdf_transposition_layers import PdfStructure, rendered_pages, words_and_geometry

        for fixture in ("pdf-transposition-layout", "multikey-pages"):
            with self.subTest(fixture=fixture), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                artifacts = {f"{fixture}.ulsbs-multikey.json": None}
                _, master_bytes = compile_fixture(fixture, passes=3, artifacts=artifacts)
                # This fixture deliberately calls a private layered wrapper to
                # delay content. Its conventional equivalent is plain content.
                preamble = (r"\AtBeginDocument{\renewcommand{\MarkLayer}[2]{#2}}" + "\n"
                            if fixture == "multikey-pages" else "")
                _, ordinary_bytes = compile_fixture(fixture, passes=3, multikey=False,
                                                     preamble=preamble)
                master = root / "Book_A5_MULTIKEY.pdf"
                canonical = root / "Book_A5.pdf"
                master.write_bytes(master_bytes)
                canonical.write_bytes(ordinary_bytes)
                manifest = json.loads(artifacts[f"{fixture}.ulsbs-multikey.json"])
                index_path = package_ranges(master, canonical, manifest, root / "stage", max_pages=2)
                index = json.loads(index_path.read_text())
                validate_index(index, index_path, canonical)
                self.assertEqual(index["manifest"], manifest)
                self.assertEqual(canonical.read_bytes(), ordinary_bytes)
                structure = PdfStructure(master_bytes)
                families = len({name.rsplit(":t", 1)[0] for name in structure.names.values()})
                for offset in (0, 7):
                    selection = {song: offset for song in range(1, families + 1)}
                    selected_master = structure.selected_pdf(master_bytes, selection)
                    master_render = rendered_pages(selected_master)
                    master_words = words_and_geometry(selected_master)
                    range_render, range_words = [], []
                    for entry in index["ranges"]:
                        content = (index_path.parent / entry["file"]).read_bytes()
                        range_structure = PdfStructure(content)
                        self.assertEqual(set(range_structure.names.values()), set(structure.names.values()))
                        selected = range_structure.selected_pdf(content, selection)
                        range_render.extend(rendered_pages(selected))
                        # Only the comparison evidence is rebased: published
                        # manifest indices remain global, never range-local.
                        range_words.extend((item[0] + entry["first_page"] - 1, *item[1:])
                                           for item in words_and_geometry(selected))
                    self.assertEqual(range_render, master_render)
                    self.assertEqual(range_words, master_words)


if __name__ == "__main__":
    unittest.main()
