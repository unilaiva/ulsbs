# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Public multikey layer identities, embedded JSON, and physical UI anchors."""

from __future__ import annotations

import base64
import io
import json
import shutil
import unittest
import xml.etree.ElementTree as ET

import pikepdf

from test_pdf_transposition_layers import (
    PdfStructure, pdf_command,
    rendered_pages, words_and_geometry,
)
from test_tex_integration import compile_fixture


def embedded_multikey_info(pdf: bytes) -> dict | None:
    structure = PdfStructure(pdf)
    reference = structure.catalog.get("/Metadata")
    if reference is None:
        return None
    stream = structure.objects[f"obj:{reference}"]["stream"]
    xml = ET.fromstring(base64.b64decode(stream["data"]))
    field = xml.find(".//{urn:ulsbs:multikey:1}multikey")
    return json.loads(field.text) if field is not None else None


def layer_page_dependencies(pdf) -> dict[str, list[int]]:
    """Independent oracle: follow shipped BDCs and invoked forms, not resources."""
    pages = {}

    def record(group, index):
        groups = group.get('/OCGs', [group])
        if not isinstance(groups, (list, pikepdf.Array)):
            groups = [groups]
        for ocg in groups:
            name = str(ocg.get('/Name', ''))
            if name.startswith('ulsbs:transpose:v1:'):
                pages.setdefault(name.rsplit(':t', 1)[0], set()).add(index)

    def visit(stream, resources, index):
        properties = resources.get('/Properties', {})
        for operands, operator in pikepdf.parse_content_stream(stream):
            if str(operator) == 'BDC' and str(operands[0]) == '/OC':
                group = operands[1]
                record(properties[group] if isinstance(group, pikepdf.Name) else group, index)
            elif str(operator) == 'Do':
                graphic = resources['/XObject'][operands[0]]
                if '/OC' in graphic:
                    record(graphic.OC, index)
                if graphic.get('/Subtype') == '/Form':
                    visit(graphic, graphic.get('/Resources', resources), index)

    for index, page in enumerate(pdf.pages):
        visit(page, page.Resources, index)
    return {prefix: sorted(indices) for prefix, indices in pages.items()}


class MultikeyMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if any(shutil.which(tool) is None for tool in ("lualatex", "qpdf", "pdftotext", "pdftoppm")):
            raise unittest.SkipTest("PDF integration tools unavailable")
        cls.artifacts = {"multikey-metadata.ulsbs-multikey.json": None}
        cls.output, cls.pdf = compile_fixture("multikey-metadata", passes=3, artifacts=cls.artifacts)
        cls.ordinary_artifacts = {"multikey-metadata.ulsbs-multikey.json": None}
        cls.ordinary_output, cls.ordinary = compile_fixture(
            "multikey-metadata", passes=3, multikey=False, artifacts=cls.ordinary_artifacts,
        )
        _, cls.hidden = compile_fixture(
            "multikey-metadata", passes=3, preamble="\\def\\ulPdfTranspositionLayerUI{hidden}\n",
        )
        cls.envelope = embedded_multikey_info(cls.pdf)
        cls.info = cls.envelope["multikey_info"]
        cls.songs = cls.info["songs"]

    def test_manifest_has_explicit_multikey_labels_and_correct_original_keys(self) -> None:
        self.assertEqual(set(self.envelope), {"has_multikey_info", "multikey_info"})
        self.assertIs(self.envelope["has_multikey_info"], True)
        self.assertEqual(self.info["schema_version"], 2)
        self.assertEqual(self.info["layer_protocol"], "ulsbs:transpose:v1")
        self.assertEqual(self.info["coordinate_space"], "pdf-user-space")
        self.assertEqual([song["song_id"] for song in self.songs], [
            "repeat-song", "repeat-song", "no-key", "repeat-song",
        ])
        self.assertEqual([song["original_key"] for song in self.songs], ["Am", "C#m", None, "G&"])
        self.assertEqual(self.songs[0]["key_labels"], [
            "Am", "B♭m", "Bm", "Cm", "C♯m", "Dm", "D♯m", "Em", "Fm", "F♯m", "Gm", "G♯m",
        ])
        self.assertEqual(self.songs[1]["key_labels"][:2], ["C♯m", "Dm"])
        self.assertEqual(self.songs[3]["key_labels"][:2], ["G♭", "G"])
        self.assertIsNone(self.songs[2]["key_labels"])

    def test_repeated_ids_get_independent_families_without_printed_number_dependence(self) -> None:
        structure = PdfStructure(self.pdf)
        prefixes = [song["layer_prefix"] for song in self.songs]
        self.assertEqual(prefixes[:4], [
            "ulsbs:transpose:v1:id:repeat-song",
            "ulsbs:transpose:v1:id:repeat-song:o02",
            "ulsbs:transpose:v1:id:no-key",
            "ulsbs:transpose:v1:id:repeat-song:o03",
        ])
        self.assertEqual([song["occurrence"] for song in self.songs], [1, 2, 1, 3])
        self.assertEqual(set(structure.names.values()), {
            f"{prefix}:t{offset:02d}" for prefix in prefixes for offset in range(12)
        })
        groups = structure.resolve(structure.config["/RBGroups"])
        self.assertEqual(len(groups), 4)
        self.assertEqual({len(structure.resolve(group)) for group in groups}, {12})
        selected = structure.selected_pdf(self.pdf, {1: 5, 2: 2})
        selected_structure = PdfStructure(selected)
        on = {selected_structure.names[ref] for ref in selected_structure.config["/ON"]}
        self.assertIn(prefixes[0] + ":t05", on)
        self.assertIn(prefixes[1] + ":t02", on)
        self.assertIn(prefixes[3] + ":t00", on)

    def test_publication_payload_is_the_same_as_embedded_json(self) -> None:
        raw = self.artifacts["multikey-metadata.ulsbs-multikey.json"]
        self.assertIsNotNone(raw)
        self.assertEqual(json.loads(raw), self.envelope)
        self.assertIsNone(self.ordinary_artifacts["multikey-metadata.ulsbs-multikey.json"])

    def test_shipout_anchors_use_physical_pages_and_exist_without_any_tags(self) -> None:
        self.assertEqual([song["page_index"] for song in self.songs], [1, 2, 3, 4])
        words = words_and_geometry(self.pdf)
        pages = {word[0]: (float(word[2]), float(word[3])) for word in words if word[1] == "page"}
        for song in self.songs:
            width, height = pages[song["page_index"]]
            x, y = song["anchor"]["x"], song["anchor"]["y"]
            self.assertTrue(0 < x < width)
            self.assertTrue(0 < y < height)
        # Printed page/song numbers reset at every header. The anchor tracks the
        # same virtual tag corner even with no key or tags and all notation hidden.
        first = self.songs[0]["anchor"]
        for song in self.songs[1:]:
            self.assertAlmostEqual(song["anchor"]["x"], first["x"], places=3)
            self.assertAlmostEqual(song["anchor"]["y"], first["y"], places=3)
        phase = next(word for word in words if word[0] == 1 and word[1] == "I")
        height = pages[1][1]
        self.assertGreater(first["x"], phase[4])
        self.assertTrue(0 <= first["y"] - (height - phase[3]) < 10)

    def test_visible_content_is_marked_only_for_shipped_annotations(self) -> None:
        self.assertEqual([song["has_transposable_content"] for song in self.songs], [
            True, True, True, True,
        ])
        structure = PdfStructure(self.pdf)
        self.assertEqual(len(structure.layers), 48)
        self.assertNotIn('hidden-song', json.dumps(self.envelope))
        self.assertNotIn("Missing ID", json.dumps(self.envelope))
        self.assertIn("skipping multikey layers", " ".join(self.output.split()))

    def test_layer_pages_match_shipped_pdf_content(self) -> None:
        with pikepdf.open(io.BytesIO(self.pdf)) as pdf:
            self.assertEqual(layer_page_dependencies(pdf), {
                song['layer_prefix']: song['layer_page_indices'] for song in self.songs
            })
        self.assertEqual([song['layer_page_indices'] for song in self.songs], [[1], [2], [3], [4]])

    def test_page_union_includes_hidden_reused_boxes_not_headers_or_page_ranges(self) -> None:
        _, data = compile_fixture('multikey-pages', passes=3)
        songs = embedded_multikey_info(data)['multikey_info']['songs']
        self.assertEqual([song['song_id'] for song in songs], ['shared', 'shared'])
        self.assertEqual([song['page_index'] for song in songs], [1, 1])
        self.assertEqual([song['layer_page_indices'] for song in songs], [[1, 3, 4, 5], [1]])
        with pikepdf.open(io.BytesIO(data)) as pdf:
            self.assertEqual(layer_page_dependencies(pdf), {
                song['layer_prefix']: song['layer_page_indices'] for song in songs
            })
        names = set(PdfStructure(data).names.values())
        self.assertFalse(any('lyrics-only' in name for name in names))

    def test_reusable_pdf_forms_fail_instead_of_claiming_exact_page_dependencies(self) -> None:
        # Form serialization executes its late Lua only once, not per placement.
        # Test immediate and deferred forms, including after earlier pages ship.
        for immediate in ('', r'\immediate'):
            with self.subTest(immediate=immediate):
                output, _ = compile_fixture('multikey-pages', expect_success=False, preamble=(
                    r'\AddToHook{enddocument}{'
                    + immediate + r'\saveboxresource\DelayedAlternative'
                    r'\useboxresource\lastsavedboxresourceindex}'))
                self.assertIn('reusablePDFformsareunsupported', ''.join(output.split()))

    def test_leaders_fail_rather_than_suppress_dependency_markers(self) -> None:
        output, _ = compile_fixture('multikey-pages', expect_success=False, preamble=(
            r'\AddToHook{enddocument}{\hbox to 300pt{\leaders\copy\DelayedAlternative\hfill}}'))
        self.assertIn('TeXleadershasunknownpagedependencies', ''.join(output.split()))

    def test_entirely_hidden_notation_has_no_ocgs_or_song_records(self) -> None:
        _, data = compile_fixture('multikey-metadata', passes=2, preamble=(
            r'\AtBeginDocument{\chordsoff\shownotesfalse}'))
        self.assertEqual(embedded_multikey_info(data)['multikey_info']['songs'], [])
        self.assertEqual(PdfStructure(data).layers, {})

    def test_hidden_ui_keeps_the_same_manifest_and_positions(self) -> None:
        self.assertEqual(embedded_multikey_info(self.hidden), self.envelope)
        self.assertEqual(PdfStructure(self.hidden).order_references(), set())

    def test_metadata_and_position_markers_do_not_change_default_layout(self) -> None:
        self.assertNotIn("was incomplete", self.output)
        self.assertNotIn("was incomplete", self.ordinary_output)
        self.assertIsNone(embedded_multikey_info(self.ordinary))
        self.assertEqual(PdfStructure(self.ordinary).layers, {})
        self.assertEqual(words_and_geometry(self.pdf), words_and_geometry(self.ordinary))
        self.assertEqual(rendered_pages(self.pdf), rendered_pages(self.ordinary))
        pdf_command(self.pdf, ["qpdf", "--check", "{pdf}"])

    def test_missing_and_malformed_ids_are_strict_only_in_multikey_pdfs(self) -> None:
        for identifier in ("", "invalid_id", "Uppercase", "has:colon"):
            with self.subTest(identifier=identifier):
                output, _ = compile_fixture(
                    "multikey-metadata", expect_success=False,
                    preamble="\\def\\ulPdfTranspositionRequireSongIDs{true}\n"
                             + "\\def\\MetadataSongID{" + identifier + "}\n",
                )
                self.assertIn("Missing or invalid song id", output)
        output, pdf = compile_fixture(
            "multikey-metadata", passes=2, multikey=False,
            preamble="\\def\\ulPdfTranspositionRequireSongIDs{true}\n",
        )
        self.assertNotIn("Missing or invalid song id", output)
        self.assertIsNone(embedded_multikey_info(pdf))


if __name__ == "__main__":
    unittest.main()
