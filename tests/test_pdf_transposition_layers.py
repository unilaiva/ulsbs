# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Local LuaLaTeX integration tests for song-level PDF optional content.

qpdf inspects the PDF dictionaries; Poppler independently reads and renders
the resulting documents. No songbook/LilyPond compilation is required.
"""

from __future__ import annotations

from collections import Counter
import base64
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from test_tex_integration import compile_fixture


LAYER_NAME = re.compile(
    r"ulsbs:transpose:v1:id:([A-Za-z0-9_-]+)(?::o(0[2-9]|[1-9]\d+))?:t(0\d|1[01])\Z"
)
OPTIONAL_CONTENT_START = re.compile(rb"/OC\s*(/[^\s]+)\s+BDC")


def pdf_command(pdf: bytes, command: list[str]) -> bytes:
    with tempfile.TemporaryDirectory(prefix="ulsbs-test-pdf-") as temporary:
        source = Path(temporary) / "input.pdf"
        source.write_bytes(pdf)
        result = subprocess.run(
            [argument.replace("{pdf}", str(source)) for argument in command],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if b"Syntax Error" in result.stderr:
            raise AssertionError("\n".join(result.stderr.decode(errors="replace").splitlines()[:3]))
        return result.stdout


class PdfStructure:
    def __init__(self, pdf: bytes) -> None:
        self.data = json.loads(pdf_command(pdf, ["qpdf", "--json", "--json-stream-data=inline", "{pdf}"]))
        self.objects = self.data["qpdf"][1]
        self.catalog = next(
            entry["value"]
            for entry in self.objects.values()
            if isinstance(entry.get("value"), dict) and entry["value"].get("/Type") == "/Catalog"
        )
        self.properties = self.resolve(self.catalog.get("/OCProperties", {}))
        self.config = self.resolve(self.properties.get("/D", {}))
        self.layers = {
            reference: self.resolve(reference)
            for reference in self.resolve(self.properties.get("/OCGs", []))
        }
        self.names = {
            reference: layer["/Name"].removeprefix("u:")
            for reference, layer in self.layers.items()
        }

    def resolve(self, value):
        if isinstance(value, str) and re.fullmatch(r"\d+ \d+ R", value):
            return self.objects[f"obj:{value}"]["value"]
        return value

    def order_references(self, value=None) -> set[str]:
        if value is None:
            value = self.config.get("/Order", [])
        if isinstance(value, str) and value in self.layers:
            return {value}
        value = self.resolve(value)
        if isinstance(value, list):
            return set().union(*(self.order_references(item) for item in value))
        return set()

    def selected_pdf(self, pdf: bytes, offsets: dict[int, int]) -> bytes:
        on = []
        families = {}
        for reference, name in self.names.items():
            match = LAYER_NAME.fullmatch(name)
            if not match:
                continue
            # /OCGs preserves creation order, independently of the song ID or
            # native layer UI order. Repeated IDs have distinct occurrence families.
            family = name.rsplit(":t", 1)[0]
            ordinal = families.setdefault(family, len(families) + 1)
            if int(match[3]) == offsets.get(ordinal, 0):
                on.append(reference)
        self.config["/BaseState"] = "/OFF"
        self.config["/ON"] = on
        self.config["/OFF"] = sorted(set(self.layers) - set(on))
        return self.updated_pdf(pdf)

    def visible_text_pdf(self, pdf: bytes) -> bytes:
        if not self.layers:
            return pdf
        on = set(self.resolve(self.config.get("/ON", [])))
        off = set(self.resolve(self.config.get("/OFF", [])))
        base_on = self.config.get("/BaseState", "/ON") == "/ON"
        visible = {reference for reference in self.layers
                   if reference in on or (base_on and reference not in off)}
        for page in self.data["pages"]:
            resources = self.resolve(self.resolve(page["object"])["/Resources"])
            properties = self.resolve(resources.get("/Properties", {}))
            for reference in page["contents"]:
                stream = self.objects[f"obj:{reference}"]["stream"]
                content = base64.b64decode(stream["data"])
                # Poppler extracts hidden OCG text. Empty ActualText suppresses
                # only its extraction, preserving every graphics/text-position
                # operator and the original marked-content nesting.
                content = OPTIONAL_CONTENT_START.sub(
                    lambda match, properties=properties: b"/Span << /ActualText () >> BDC"
                    if properties[match[1].decode()] not in visible else match[0],
                    content,
                )
                stream["data"] = base64.b64encode(content).decode()
        return self.updated_pdf(pdf)

    def updated_pdf(self, pdf: bytes) -> bytes:
        with tempfile.TemporaryDirectory(prefix="ulsbs-test-layer-select-") as temporary:
            root = Path(temporary)
            source, update, destination = (
                root / "input.pdf", root / "update.json", root / "selected.pdf"
            )
            source.write_bytes(pdf)
            update.write_text(json.dumps(self.data))
            subprocess.run(
                ["qpdf", str(source), f"--update-from-json={update}", str(destination)],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            return destination.read_bytes()


def words_and_geometry(pdf: bytes) -> list[tuple]:
    pdf = PdfStructure(pdf).visible_text_pdf(pdf)
    xml = pdf_command(pdf, ["pdftotext", "-bbox", "{pdf}", "-"])
    root = ET.fromstring(xml)
    result = []
    for page_number, page in enumerate(root.iter("{http://www.w3.org/1999/xhtml}page")):
        result.append((page_number, "page", page.get("width"), page.get("height")))
        for word in page.iter("{http://www.w3.org/1999/xhtml}word"):
            result.append((
                page_number, word.text,
                *(round(float(word.get(key)), 2) for key in ("xMin", "yMin", "xMax", "yMax")),
            ))
    return result


def rendered_pages(pdf: bytes) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="ulsbs-test-render-") as temporary:
        root = Path(temporary)
        source = root / "input.pdf"
        source.write_bytes(pdf)
        result = subprocess.run(
            ["pdftoppm", "-r", "72", str(source), str(root / "page")],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if b"Syntax Error" in result.stderr:
            raise AssertionError("\n".join(result.stderr.decode(errors="replace").splitlines()[:3]))
        return [hashlib.sha256(page.read_bytes()).hexdigest() for page in sorted(root.glob("page-*.ppm"))]


class PdfTranspositionLayerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        missing = [tool for tool in ("lualatex", "qpdf", "pdftotext", "pdftoppm")
                   if shutil.which(tool) is None]
        if missing:
            raise unittest.SkipTest(f"PDF integration tools are not installed: {', '.join(missing)}")
        cls.pdfs = {}
        cls.outputs = {}
        for mode, preamble in (
            ("native", ""),
            ("hidden", "\\def\\ulPdfTranspositionLayerUI{hidden}\n"),
            ("disabled", "\\def\\ulPdfTranspositionLayers{false}\n"),
        ):
            # Match the local songbook rerun workflow, including outline/page refs.
            output, pdf = compile_fixture("pdf-transposition-layout", preamble=preamble, passes=3)
            if "Fatal error" in output:
                raise AssertionError(output)
            cls.pdfs[mode] = pdf
            cls.outputs[mode] = output
        _, cls.semantic_pdf = compile_fixture("pdf-transposition-semantics", passes=3)
        _, cls.semantic_disabled = compile_fixture(
            "pdf-transposition-semantics",
            preamble="\\def\\ulPdfTranspositionLayers{false}\n", passes=3,
        )

    def test_twelve_stably_named_layers_per_song_and_independent_radio_groups(self) -> None:
        structure = PdfStructure(self.pdfs["native"])
        expected = {
            f"ulsbs:transpose:v1:id:fixture-{song}:t{offset:02d}"
            for song in (1, 2) for offset in range(12)
        }
        self.assertEqual(set(structure.names.values()), expected)
        self.assertEqual(len(structure.layers), 24)
        groups = structure.resolve(structure.config["/RBGroups"])
        self.assertEqual(len(groups), 2)
        self.assertEqual(
            {frozenset(structure.names[reference] for reference in structure.resolve(group)) for group in groups},
            {frozenset(name for name in expected if f":id:fixture-{song}:" in name) for song in (1, 2)},
        )
        self.assertEqual(structure.order_references(), set(structure.layers))

    def test_original_only_initial_visibility_and_print_usage(self) -> None:
        for mode in ("native", "hidden"):
            with self.subTest(mode=mode):
                structure = PdfStructure(self.pdfs[mode])
                on = set(structure.resolve(structure.config.get("/ON", [])))
                off = set(structure.resolve(structure.config.get("/OFF", [])))
                base_on = structure.config.get("/BaseState", "/ON") == "/ON"
                for reference, name in structure.names.items():
                    original = name.endswith(":t00")
                    visible = reference in on or (base_on and reference not in off)
                    self.assertEqual(visible, original, name)
                    usage = structure.resolve(structure.layers[reference]["/Usage"])
                    printing = structure.resolve(usage["/Print"])
                    self.assertEqual(printing["/PrintState"], "/ON" if original else "/OFF", name)
                print_rules = [rule for rule in structure.resolve(structure.config.get("/AS", []))
                               if rule.get("/Event") == "/Print" and "/Print" in rule.get("/Category", [])]
                self.assertTrue(print_rules, "Print usage must be applied by the default configuration")
                covered = set().union(*(set(structure.resolve(rule.get("/OCGs", list(structure.layers))))
                                        for rule in print_rules))
                self.assertEqual(covered, set(structure.layers))

    def test_hidden_ui_preserves_layers_groups_and_programmatic_selection(self) -> None:
        native, hidden = (PdfStructure(self.pdfs[mode]) for mode in ("native", "hidden"))
        self.assertEqual(set(native.names.values()), set(hidden.names.values()))
        self.assertFalse(hidden.order_references())
        self.assertEqual(len(hidden.resolve(hidden.config["/RBGroups"])), 2)
        selected = hidden.selected_pdf(self.pdfs["hidden"], {1: 2, 2: 5})
        self.assertNotEqual(rendered_pages(selected), rendered_pages(self.pdfs["hidden"]))
        # Shared lyrics keep exactly the same positions after independent selection.
        anchors = {"Opening", "Independent", "Combined", "Hidden"}
        self.assertEqual(
            [word for word in words_and_geometry(selected) if word[1] in anchors],
            [word for word in words_and_geometry(self.pdfs["hidden"]) if word[1] in anchors],
        )

    def test_prose_inline_chord_is_not_part_of_interactive_notation(self) -> None:
        pdf = self.pdfs["native"]
        original = words_and_geometry(pdf)
        prose = next(word for word in original if word[1] == "Prose")
        selected = words_and_geometry(PdfStructure(pdf).selected_pdf(pdf, {1: 2}))
        def prose_line(words):
            return [word for word in words if word[0] == prose[0] and word[1] != "page"
                    and word[3] >= prose[3] - 5 and word[5] <= prose[5] + 5]
        self.assertIn("C", [word[1] for word in prose_line(original)])
        self.assertEqual(prose_line(selected), prose_line(original))

    def test_disabled_has_no_optional_content_or_dependency(self) -> None:
        structure = PdfStructure(self.pdfs["disabled"])
        self.assertNotIn("/OCProperties", structure.catalog)
        self.assertFalse(structure.layers)
        self.assertNotIn("ocgx2.sty", self.outputs["disabled"])

    def test_default_and_hidden_preserve_disabled_layout_and_rendering(self) -> None:
        disabled = self.pdfs["disabled"]
        geometry = words_and_geometry(disabled)
        self.assertTrue(geometry, "The layout comparison must contain actual page content")
        images = rendered_pages(disabled)
        for mode in ("native", "hidden"):
            with self.subTest(mode=mode):
                self.assertEqual(words_and_geometry(self.pdfs[mode]), geometry)
                self.assertEqual(rendered_pages(self.pdfs[mode]), images)

    def test_effective_source_transposition_notrans_replay_melody_and_inline_chords(self) -> None:
        self.assertEqual(words_and_geometry(self.semantic_pdf), words_and_geometry(self.semantic_disabled))
        structure = PdfStructure(self.semantic_pdf)
        selected = structure.selected_pdf(self.semantic_pdf, {1: 2})
        original_words = Counter(word[1] for word in words_and_geometry(self.semantic_pdf))
        selected_words = Counter(word[1] for word in words_and_geometry(selected))
        # Source C under +2 is D; layer +2 must produce E, not D or F#.
        # Primary C and secondary E hints and their replay follow the same rule.
        self.assertEqual(original_words["D"], 4)  # source, inline, stored, replayed chords
        self.assertEqual(original_words["d"], 3)  # lowercase font text for primary hints
        self.assertEqual(original_words["f"], 3)  # secondary F# hints
        self.assertEqual(selected_words["E"], 4)
        self.assertEqual(selected_words["e"], 3)
        self.assertEqual(selected_words["g"], 3)
        self.assertEqual(selected_words["G"], 1)  # standalone altchord
        self.assertEqual(selected_words["A"], 1)  # source-level notrans{G} still shifts interactively
        self.assertEqual(selected_words["C"], 1)  # standalone altchords remain unchanged
        self.assertEqual(selected_words["D"], 1)  # source transpose changed back to zero
        for anchor in ("source", "suppressed", "inline", "melody", "stored", "replayed", "alternate", "changed"):
            self.assertEqual(original_words[anchor], 1, anchor)
            self.assertEqual(selected_words[anchor], 1, anchor)

    def test_generated_pdfs_pass_qpdf_validation(self) -> None:
        for mode, pdf in (*self.pdfs.items(), ("semantics", self.semantic_pdf)):
            with self.subTest(mode=mode):
                pdf_command(pdf, ["qpdf", "--check", "{pdf}"])

    def test_prelude_keys_follow_song_layers_without_source_retransposition(self) -> None:
        output, enabled = compile_fixture("pdf-transposition-keys", passes=3)
        self.assertNotIn("Missing character", output)
        _, disabled = compile_fixture(
            "pdf-transposition-keys", passes=3,
            preamble="\\def\\ulPdfTranspositionLayers{false}\n",
        )
        self.assertEqual(rendered_pages(enabled), rendered_pages(disabled))
        self.assertEqual(words_and_geometry(enabled), words_and_geometry(disabled))
        structure = PdfStructure(enabled)
        self.assertEqual(len(structure.layers), 48)
        self.assert_valid_layer_content(enabled)

        def key_labels(pdf):
            words = words_and_geometry(pdf)
            labels = []
            for key in (word for word in words if word[1] == "Key:"):
                label = [word for word in words if word[0] == key[0]
                         and word[1] != "page" and word[2] >= key[2] - 0.1
                         and word[3] < key[5] + 2 and word[5] > key[3] - 2]
                labels.append("".join(word[1] for word in sorted(label, key=lambda word: word[2])))
            return labels

        self.assertEqual(key_labels(enabled), ["Key:D", "Key:F♯m"])
        first = structure.selected_pdf(enabled, {1: 2})
        self.assertEqual(key_labels(first), ["Key:E", "Key:F♯m"])
        both = PdfStructure(enabled).selected_pdf(enabled, {1: 2, 2: 2})
        self.assertEqual(key_labels(both), ["Key:E", "Key:G♯m"])
        # One shared symbol demonstrates the public macro outside song tags.
        # Only non-original badges add another symbol before their Key label.
        text = lambda pdf: " ".join(word[1] for word in words_and_geometry(pdf))
        self.assertEqual(text(enabled).count("⮁"), 1)
        self.assertEqual(text(first).count("⮁"), 2)
        self.assertEqual(text(both).count("⮁"), 3)
        self.assertRegex(text(both), r"⮁\s+Key:")
        colors = []
        for obj in structure.objects.values():
            stream = obj.get("stream", {})
            if "data" in stream:
                colors += re.findall(
                    rb"([\d.]+) ([\d.]+) ([\d.]+) (?:rg|RG)\b",
                    base64.b64decode(stream["data"]),
                )
        self.assertIn((0.6, 0.0, 0.04), [tuple(map(float, color)) for color in colors])
        selected_words = Counter(word[1] for word in words_and_geometry(both))
        self.assertEqual(selected_words["Am"], 2)  # recommended key and hidden-key body
        self.assertEqual(selected_words["Cm"], 1)  # recommended key remains shared

        # Default and alternate badge drawing use different colors, including
        # the pitch text. The public color can be customized independently.
        for color in ("transposedkeycolor", "chordcolor"):
            _, recolored = compile_fixture(
                "pdf-transposition-keys", passes=3,
                preamble="\\AtBeginDocument{\\colorlet{" + color + "}{red}}\n",
            )
            recolored_structure = PdfStructure(recolored)
            alternate = recolored_structure.selected_pdf(recolored, {1: 2, 2: 2})
            if color == "transposedkeycolor":
                self.assertEqual(rendered_pages(recolored), rendered_pages(enabled))
                self.assertNotEqual(rendered_pages(alternate), rendered_pages(both))
            else:
                self.assertNotEqual(rendered_pages(recolored), rendered_pages(enabled))

    def test_page_marked_content_references_real_layers_and_is_balanced(self) -> None:
        for mode in ("native", "hidden"):
            with self.subTest(mode=mode):
                self.assert_valid_layer_content(self.pdfs[mode])

    def test_draft_then_two_full_passes_resolve_layers_after_image_allocation(self) -> None:
        # A tiny PNG is generated in the compiler's temporary directory only.
        image = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        _, pdf = compile_fixture(
            "pdf-transposition-draft-image", passes=3, draft_passes=1,
            files={"layer-image.png": image},
        )
        self.assert_valid_layer_content(pdf)
        selected = PdfStructure(pdf).selected_pdf(pdf, {1: 2})
        self.assertNotEqual(rendered_pages(pdf), rendered_pages(selected))
        pdf_command(pdf, ["qpdf", "--check", "{pdf}"])

    def test_chord_scaling_respects_natural_width_minimum_and_empty_original(self) -> None:
        for minimum in (0.85, 0.95):
            with self.subTest(minimum=minimum):
                output, _ = compile_fixture(
                    "pdf-transposition-scaling",
                    preamble=f"\\def\\ulPdfTranspositionMinimumScale{{{minimum}}}\n",
                )
                samples = re.findall(
                    r"ULSBS-SCALE:([a-z]+):([\d.]+):([\d.]+):([\d.]+)", output
                )
                self.assertEqual(len(samples), 44)
                narrower = equal = wider = limited = 0
                for case, scale, original, alternative in samples:
                    scale, original, alternative = map(float, (scale, original, alternative))
                    expected = max(minimum, original / alternative) if alternative > original > 0 else 1
                    self.assertAlmostEqual(scale, expected, delta=0.00002, msg=case)
                    if case == "empty":
                        self.assertEqual(original, 0)
                        self.assertEqual(scale, 1)
                    elif alternative < original:
                        narrower += 1
                    elif alternative == original:
                        equal += 1
                    elif scale > minimum:
                        wider += 1
                    else:
                        limited += 1
                        self.assertGreater(alternative * scale, original)
                self.assertTrue(all(count > 0 for count in (narrower, equal, limited)))
                if minimum == 0.85:
                    self.assertGreater(wider, 0, "Exercise proportional shrinking above the floor")
                self.assertIn("ULSBS-GROUP-SIDEEFFECT:1", output)

    def assert_valid_layer_content(self, pdf: bytes) -> None:
        structure = PdfStructure(pdf)
        used_layers = set()
        for page in structure.data["pages"]:
            resources = structure.resolve(structure.resolve(page["object"])["/Resources"])
            properties = structure.resolve(resources.get("/Properties", {}))
            depth = 0
            for reference in page["contents"]:
                content = base64.b64decode(structure.objects[f"obj:{reference}"]["stream"]["data"])
                for match in OPTIONAL_CONTENT_START.finditer(content):
                    layer = properties[match[1].decode()]
                    self.assertIn(layer, structure.layers, "Span does not reference a real OCG")
                    used_layers.add(layer)
                for operator in re.findall(rb"\b(?:BDC|BMC|EMC)\b", content):
                    depth += -1 if operator == b"EMC" else 1
                    self.assertGreaterEqual(depth, 0, "Unmatched PDF marked-content end")
            self.assertEqual(depth, 0, "Unclosed PDF marked-content group")
        self.assertEqual(used_layers, set(structure.layers))


if __name__ == "__main__":
    unittest.main()
