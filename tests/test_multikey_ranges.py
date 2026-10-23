# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generic synthetic PDFs only: no private score or extracted music fixtures."""

from __future__ import annotations

import copy
import json
import random
import shutil
import subprocess
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

import pikepdf

from ulsbs.constants import MULTIKEY_INDEX_MAX_BYTES
from ulsbs.multikey_ranges import (
    PROTOCOL, _check_range, _dependencies, _destinations, _encoded,
    check_pdf_property_resources, package_ranges, qpdf_version, validate_index,
)


def envelope(songs=None):
    return {"has_multikey_info": True, "multikey_info": {
        "schema_version": 2, "layer_protocol": PROTOCOL,
        "coordinate_space": "pdf-user-space", "songs": songs or [],
    }}


def synthetic(directory, count=5, *, layers=True, links=True, noisy=False):
    """Build independent canonical/master documents sharing physical geometry."""
    master, canonical = directory / "master with spaces.pdf", directory / "Book.edition_A5.pdf"
    prefix = PROTOCOL + ":id:generic"
    song = {"song_id": "generic", "occurrence": 1, "has_transposable_content": True,
            "original_key": "C", "key_labels": [f"key {i}" for i in range(12)],
            "layer_prefix": prefix, "layer_page_indices": list(range(count)),
            "page_index": 0, "anchor": {"x": 120, "y": 200}}
    manifest = envelope([song] if layers else [])
    for path in (master, canonical):
        with pikepdf.Pdf.new() as pdf:
            groups = [pdf.make_indirect(pikepdf.Dictionary(
                Type=pikepdf.Name.OCG, Name=f"{prefix}:t{i:02d}",
                Usage=pikepdf.Dictionary(View=pikepdf.Dictionary(ViewState=pikepdf.Name.ON))))
                for i in range(12)] if layers and path == master else []
            fixed = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.OCG, Name="Fixed rights"))
            all_groups = groups + [fixed]
            pdf.Root.OCProperties = pikepdf.Dictionary(
                OCGs=pikepdf.Array(all_groups), D=pikepdf.Dictionary(
                    BaseState=pikepdf.Name.OFF, ON=pikepdf.Array(groups[:1] + [fixed]),
                    OFF=pikepdf.Array(groups[1:]), Order=pikepdf.Array(all_groups),
                    RBGroups=pikepdf.Array([pikepdf.Array(groups)] if groups else [])),
                Configs=pikepdf.Array([pikepdf.Dictionary(Name="Print", BaseState=pikepdf.Name.ON)]))
            font = pdf.make_indirect(pikepdf.Dictionary(
                Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica))
            for i in range(count):
                page = pdf.add_blank_page(page_size=(320 + i, 480 + i))
                page.obj.CropBox = pikepdf.Array([5, 10, 310 + i, 470 + i])
                page.obj.TrimBox = pikepdf.Array([6, 11, 309 + i, 469 + i])
                page.obj.Rotate = (i % 4) * 90
                page.obj.UserUnit = 1 + (i % 2)
                page.obj.Group = pikepdf.Dictionary(S=pikepdf.Name.Transparency,
                                                    CS=pikepdf.Name.DeviceRGB)
                properties = {f"/L{j}": group for j, group in enumerate(groups)}
                properties["/Fixed"] = fixed
                page.obj.Resources = pikepdf.Dictionary(
                    Properties=pikepdf.Dictionary(properties), Font=pikepdf.Dictionary(F1=font))
                content = b"/OC /Fixed BDC BT /F1 10 Tf 20 20 Td (Generic rights) Tj ET EMC\n"
                for j in range(len(groups)):
                    content += (f"/OC /L{j} BDC q {j / 12:.4f} 0 0 rg "
                                f"{20+j} 40 10 20 re f Q BT /F1 12 Tf 20 100 Td "
                                f"(Alternative {j} page {i}) Tj ET EMC\n").encode()
                if noisy:
                    content += b"%" + random.Random(i).randbytes(8000).hex().encode() + b"\n"
                page.obj.Contents = pdf.make_stream(content)
            if links:
                tree = pikepdf.NameTree.new(pdf)
                tree["book-end"] = pikepdf.Array(
                    [pdf.pages[-1].obj, pikepdf.Name.XYZ, 12, 345, None])
                pdf.Root.Names = pikepdf.Dictionary(Dests=tree.obj)
                for page in pdf.pages:
                    page.obj.Annots = pikepdf.Array([
                        pdf.make_indirect(pikepdf.Dictionary(
                            Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link,
                            Rect=pikepdf.Array([20, 30, 100, 45]), Dest=pikepdf.String("book-end"))),
                        pdf.make_indirect(pikepdf.Dictionary(
                            Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link,
                            Rect=pikepdf.Array([20, 50, 100, 65]),
                            A=pikepdf.Dictionary(S=pikepdf.Name.URI,
                                                 URI=pikepdf.String("https://example.org/rights"))))])
            pdf.docinfo["/Title"] = "Generic synthetic book"
            pdf.save(path, deterministic_id=True)
    return master, canonical, manifest


@unittest.skipUnless(shutil.which("qpdf"), "qpdf required")
class MultikeyRangeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def package(self, count=5, **kwargs):
        master, canonical, manifest = synthetic(self.root, count)
        index_path = package_ranges(master, canonical, manifest, self.root / "stage", **kwargs)
        return master, canonical, manifest, index_path, json.loads(index_path.read_text())

    def test_complete_catalog_content_links_geometry_and_determinism(self):
        master, canonical, manifest = synthetic(self.root)
        source_bytes, ordinary_bytes = master.read_bytes(), canonical.read_bytes()
        path = package_ranges(master, canonical, manifest, self.root / "stage", max_pages=2)
        index = json.loads(path.read_text())
        self.assertEqual(path.name, "Book.edition_A5_MULTIKEY_RANGES.json")
        self.assertEqual(index["manifest"], manifest)
        self.assertEqual([(p["first_page"], p["last_page"]) for p in index["ranges"]],
                         [(1, 2), (3, 4), (5, 5)])
        self.assertEqual(index["geometry"][1], {
            "view": [5, 10, 311, 471], "rotation": 90, "user_unit": 2})
        self.assertEqual(index["packaging"], {"tool": "qpdf", "tool_version": qpdf_version()})
        validate_index(index, path, canonical)
        with pikepdf.open(master) as source:
            for part in index["ranges"]:
                with pikepdf.open(path.parent / part["file"]) as pdf:
                    _check_range(source, pdf, part["first_page"], part["last_page"],
                                 _destinations(source))
                    self.assertEqual(len(pdf.Root.OCProperties.OCGs), 13)
                    self.assertEqual(str(pdf.pages[0].obj.Annots[0].Dest), "book-end")
                    self.assertEqual(str(pdf.pages[0].obj.Annots[1].A.URI),
                                     "https://example.org/rights")
        other = package_ranges(master, canonical, manifest, self.root / "repeat", max_pages=2)
        self.assertEqual(path.read_bytes(), other.read_bytes())
        for part in index["ranges"]:
            self.assertEqual((path.parent / part["file"]).read_bytes(),
                             (other.parent / part["file"]).read_bytes())
        self.assertEqual(master.read_bytes(), source_bytes)
        self.assertEqual(canonical.read_bytes(), ordinary_bytes)

    def test_empty_song_cover_and_short_final_range(self):
        for count in (1, 31, 51):
            with self.subTest(count=count):
                directory = self.root / str(count)
                directory.mkdir()
                master, canonical, manifest = synthetic(directory, count, layers=False, links=False)
                maximum = 30 if count == 31 else 50
                path = package_ranges(master, canonical, manifest, directory / "stage", max_pages=maximum)
                index = json.loads(path.read_text())
                self.assertEqual(index["ranges"][-1]["last_page"], count)
                self.assertEqual(index["ranges"][-1]["page_count"], 1)
                self.assertTrue(index["ranges"])

    def test_adaptive_bisection_and_single_page_warning(self):
        master, canonical, manifest = synthetic(self.root, 4, noisy=True)
        initial = package_ranges(master, canonical, manifest, self.root / "initial", max_pages=4)
        initial_index = json.loads(initial.read_text())
        total = initial_index["ranges"][0]["byte_length"]
        path = package_ranges(master, canonical, manifest, self.root / "adaptive",
                              max_pages=4, target_bytes=total // 2)
        parts = json.loads(path.read_text())["ranges"]
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(part["byte_length"] <= total // 2 for part in parts))
        messages = []
        path = package_ranges(master, canonical, manifest, self.root / "tiny", target_bytes=1,
                              warn=messages.append)
        self.assertEqual(len(messages), 4)
        self.assertEqual(len(json.loads(path.read_text())["ranges"]), 4)

    def test_direct_links_and_unsafe_actions_fail_without_partial_index(self):
        for kind in ("direct", "uri", "action"):
            with self.subTest(kind=kind):
                directory = self.root / kind
                directory.mkdir()
                master, canonical, manifest = synthetic(directory, 2)
                with pikepdf.open(master, allow_overwriting_input=True) as pdf:
                    link = pdf.pages[0].obj.Annots[0]
                    if kind == "direct":
                        link.Dest = pikepdf.Array([pdf.pages[1].obj, pikepdf.Name.Fit])
                    elif kind == "uri":
                        pdf.pages[0].obj.Annots[1].A.URI = pikepdf.String("javascript:alert(1)")
                    else:
                        pdf.Root.OpenAction = pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS="1")
                    pdf.save(master)
                with self.assertRaises(ValueError):
                    package_ranges(master, canonical, manifest, directory / "stage")
                self.assertEqual(list((directory / "stage").iterdir()), [])

    def test_pairing_geometry_names_and_manifest_failures(self):
        master, canonical, manifest = synthetic(self.root, 3)
        mutations = [
            lambda m: m["multikey_info"]["songs"][0].update(page_index=3),
            lambda m: m["multikey_info"]["songs"][0].update(anchor={"x": 1000, "y": 100}),
            lambda m: m["multikey_info"]["songs"][0].update(layer_page_indices=[0, 1]),
            lambda m: m["multikey_info"]["songs"][0].update(key_labels=["C"]),
            lambda m: m.update(has_multikey_info=1),
            lambda m: m["multikey_info"].update(schema_version=True),
        ]
        for mutation in mutations:
            bad = copy.deepcopy(manifest)
            mutation(bad)
            with self.assertRaises(ValueError):
                package_ranges(master, canonical, bad, self.root / "bad")
        with pikepdf.open(canonical, allow_overwriting_input=True) as pdf:
            pdf.pages[0].obj.TrimBox = pikepdf.Array([7, 11, 309, 469])
            pdf.save(canonical)
        with self.assertRaisesRegex(ValueError, "geometry"):
            package_ranges(master, canonical, manifest, self.root / "geometry")
        master, canonical, manifest = synthetic(self.root, 3)
        with pikepdf.open(canonical, allow_overwriting_input=True) as pdf:
            pikepdf.NameTree(pdf.Root.Names.Dests)["book-end"][2] = 13
            pdf.save(canonical)
        with self.assertRaisesRegex(ValueError, r"coordinates differ for 'book-end'.*12.*13"):
            package_ranges(master, canonical, manifest, self.root / "names")

    def test_actual_dependencies_ignore_unused_resources_follow_forms(self):
        master, canonical, manifest = synthetic(self.root, 2)
        with pikepdf.open(master, allow_overwriting_input=True) as pdf:
            page = pdf.pages[0]
            form = pdf.make_stream(page.obj.Contents.read_bytes())
            form.Type, form.Subtype = pikepdf.Name.XObject, pikepdf.Name.Form
            form.BBox = pikepdf.Array([0, 0, 320, 480])
            form.Resources = page.obj.Resources
            page.obj.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Fm=form))
            page.obj.Contents = pdf.make_stream(b"/Fm Do\n")
            self.assertTrue(all(indices == {0, 1} for indices in _dependencies(pdf).values()))
            pdf.save(master)
        package_ranges(master, canonical, manifest, self.root / "stage", max_pages=1)
        with pikepdf.open(master, allow_overwriting_input=True) as pdf:
            pdf.pages[1].obj.Contents = pdf.make_stream(b"q Q\n")
            pdf.save(master)
        with self.assertRaisesRegex(ValueError, "actual optional content"):
            package_ranges(master, canonical, manifest, self.root / "wrong")

    def test_repeated_occurrences_and_shared_pages_keep_all_alternatives(self):
        master, canonical, manifest = synthetic(self.root, 3)
        repeated = copy.deepcopy(manifest["multikey_info"]["songs"][0])
        repeated.update(occurrence=2, layer_prefix=repeated["layer_prefix"] + ":o02",
                        layer_page_indices=[0, 2], page_index=1)
        manifest["multikey_info"]["songs"].append(repeated)
        with pikepdf.open(master, allow_overwriting_input=True) as pdf:
            groups = [pdf.make_indirect(pikepdf.Dictionary(
                Type=pikepdf.Name.OCG, Name=f"{repeated['layer_prefix']}:t{i:02d}")) for i in range(12)]
            for group in groups:
                pdf.Root.OCProperties.OCGs.append(group)
                pdf.Root.OCProperties.D.Order.append(group)
            pdf.Root.OCProperties.D.ON.append(groups[0])
            for group in groups[1:]:
                pdf.Root.OCProperties.D.OFF.append(group)
            pdf.Root.OCProperties.D.RBGroups.append(pikepdf.Array(groups))
            for index in (0, 2):
                page = pdf.pages[index]
                content = page.obj.Contents.read_bytes()
                for offset, group in enumerate(groups):
                    page.obj.Resources.Properties[f"/Repeat{offset}"] = group
                    content += (f"/OC /Repeat{offset} BDC BT /F1 12 Tf 20 150 Td "
                                f"(Repeated alternative {offset}) Tj ET EMC\n").encode()
                page.obj.Contents = pdf.make_stream(content)
            pdf.save(master)
        path = package_ranges(master, canonical, manifest, self.root / "stage", max_pages=1)
        self.assertEqual(json.loads(path.read_text())["manifest"], manifest)
        for part in json.loads(path.read_text())["ranges"]:
            with pikepdf.open(path.parent / part["file"]) as pdf:
                self.assertEqual(len(pdf.Root.OCProperties.OCGs), 25)

    def test_union_dependencies_sparse_occurrences_and_unused_global_groups(self):
        master, canonical, manifest = synthetic(self.root, 2)
        song = manifest["multikey_info"]["songs"][0]
        song["occurrence"] = 2
        song["layer_prefix"] += ":o02"
        with pikepdf.open(master, allow_overwriting_input=True) as pdf:
            for offset, group in enumerate(list(pdf.Root.OCProperties.OCGs)[:12]):
                group.Name = f"{song['layer_prefix']}:t{offset:02d}"
            for offset in range(12):
                pdf.Root.OCProperties.OCGs.append(pdf.make_indirect(pikepdf.Dictionary(
                    Type=pikepdf.Name.OCG, Name=f"{PROTOCOL}:id:unused:t{offset:02d}")))
            # The global affected-page set is a union, not a promise that every
            # alternative has content on every affected physical page.
            pdf.pages[1].obj.Contents = pdf.make_stream(
                b"/OC /L0 BDC 20 20 10 10 re f EMC /OC /L11 BDC 40 40 10 10 re f EMC\n")
            pdf.save(master)
        path = package_ranges(master, canonical, manifest, self.root / "stage", max_pages=1)
        self.assertEqual(json.loads(path.read_text())["manifest"], manifest)

    def test_unshipped_header_has_paired_null_anchor_and_page(self):
        master, canonical, manifest = synthetic(self.root, 2)
        song = manifest["multikey_info"]["songs"][0]
        song.update(page_index=None, anchor=None)
        path = package_ranges(master, canonical, manifest, self.root / "stage", max_pages=1)
        self.assertEqual(json.loads(path.read_text())["manifest"], manifest)
        song.update(page_index=0)
        with self.assertRaisesRegex(ValueError, "Unpaired"):
            package_ranges(master, canonical, manifest, self.root / "bad")

    def test_inherited_resources_and_page_boxes(self):
        master, canonical, manifest = synthetic(self.root, 1)
        for path in (master, canonical):
            with pikepdf.open(path, allow_overwriting_input=True) as pdf:
                page = pdf.pages[0].obj
                for key in ("/Resources", "/MediaBox", "/CropBox", "/Rotate"):
                    page.Parent[key] = page[key]
                    del page[key]
                pdf.save(path)
        package_ranges(master, canonical, manifest, self.root / "stage")

    def test_initial_view_goto_is_not_a_link_annotation(self):
        # A startup page may be the cover or a later page. Retain its exact view
        # only in the containing range; normal removal elsewhere is not a warning.
        for initial_page in (0, 1):
            with self.subTest(initial_page=initial_page):
                directory = self.root / f"initial-view-{initial_page}"
                directory.mkdir()
                master, canonical, manifest = synthetic(directory, 3)
                with pikepdf.open(master, allow_overwriting_input=True) as pdf:
                    pdf.Root.OpenAction = pikepdf.Dictionary(
                        S=pikepdf.Name.GoTo,
                        D=pikepdf.Array([pdf.pages[initial_page].obj, pikepdf.Name.XYZ, 12, 345, None]))
                    pdf.save(master)
                messages = []
                with warnings.catch_warnings():
                    warnings.simplefilter("error")
                    path = package_ranges(master, canonical, manifest, directory / "stage",
                                          max_pages=1, warn=messages.append)
                self.assertEqual(messages, [])
                for part in json.loads(path.read_text())["ranges"]:
                    with pikepdf.open(path.parent / part["file"]) as pdf:
                        included = part["first_page"] == initial_page + 1
                        self.assertEqual("/OpenAction" in pdf.Root, included)
                        if included:
                            self.assertEqual(pdf.Root.OpenAction.D[0].objgen, pdf.pages[0].obj.objgen)
                            self.assertEqual(list(pdf.Root.OpenAction.D)[1:], [pikepdf.Name.XYZ, 12, 345, None])

    def test_existing_readonly_pgf_widgets_and_layer_controls_are_preserved(self):
        master, canonical, manifest = synthetic(self.root, 3)
        with pikepdf.open(master, allow_overwriting_input=True) as pdf:
            fields = []
            for index, page in enumerate(pdf.pages):
                appearance = pdf.make_stream(b"q Q\n")
                appearance.Type, appearance.Subtype = pikepdf.Name.XObject, pikepdf.Name.Form
                appearance.BBox = pikepdf.Array([0, 0, 1, 1])
                field = pdf.make_indirect(pikepdf.Dictionary(
                    Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget, FT=pikepdf.Name.Btn,
                    Ff=65537, T=f"pbs@ARFix@{index}", Rect=pikepdf.Array([0, 0, 1, 1]),
                    A=pikepdf.Dictionary(S=pikepdf.Name.ResetForm),
                    AP=pikepdf.Dictionary(N=pikepdf.Dictionary(On=appearance)), AS=pikepdf.Name.On))
                fields.append(field)
                page.obj.Annots.append(field)
                page.obj.Annots.append(pdf.make_indirect(pikepdf.Dictionary(
                    Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link,
                    Rect=pikepdf.Array([20, 80, 100, 95]),
                    A=pikepdf.Dictionary(S=pikepdf.Name.SetOCGState, State=pikepdf.Array(
                        [pikepdf.Name.ON, pdf.Root.OCProperties.OCGs[7]])))))
            pdf.Root.AcroForm = pikepdf.Dictionary(Fields=pikepdf.Array(fields))
            pdf.save(master)
        path = package_ranges(master, canonical, manifest, self.root / "stage", max_pages=1)
        for part in json.loads(path.read_text())["ranges"]:
            with pikepdf.open(path.parent / part["file"]) as pdf:
                self.assertEqual(len(pdf.Root.AcroForm.Fields), 1)
                self.assertEqual(len(pdf.pages[0].obj.Annots), 4)
        with pikepdf.open(master, allow_overwriting_input=True) as pdf:
            pdf.Root.AcroForm.Fields[0].Ff = 0
            pdf.save(master)
        with self.assertRaisesRegex(ValueError, "editable"):
            package_ranges(master, canonical, manifest, self.root / "editable")

    def test_qpdf_policy_applies_to_tool_and_recorded_package_version(self):
        master, canonical, manifest = synthetic(self.root, 1)
        index = json.loads(package_ranges(master, canonical, manifest, self.root / "policy").read_text())
        with patch("ulsbs.multikey_ranges.MULTIKEY_MIN_QPDF_VERSION", (99, 1, 0)):
            with patch("ulsbs.multikey_ranges._run", return_value="qpdf version 99.0.0"), \
                    self.assertRaisesRegex(ValueError, r"qpdf >= 99\.1\.0 required"):
                qpdf_version()
            with self.assertRaisesRegex(ValueError, "packaging"):
                validate_index(index)

    def test_page_labels_are_preserved_when_number_tree_is_rebased(self):
        master, canonical, manifest = synthetic(self.root, 5)
        with pikepdf.open(master, allow_overwriting_input=True) as pdf:
            pdf.Root.PageLabels = pikepdf.Dictionary(Nums=pikepdf.Array([
                0, pikepdf.Dictionary(S=pikepdf.Name.r),
                2, pikepdf.Dictionary(S=pikepdf.Name.D, St=1, P="Song ")]))
            labels = [page.label for page in pdf.pages]
            pdf.save(master)
        path = package_ranges(master, canonical, manifest, self.root / "stage", max_pages=2)
        actual = []
        for part in json.loads(path.read_text())["ranges"]:
            with pikepdf.open(path.parent / part["file"]) as pdf:
                actual.extend(page.label for page in pdf.pages)
        self.assertEqual(actual, labels)

    def test_metadata_channels_reject_json_preserve_title(self):
        for kind in ("info", "xmp", "attachment", "custom-key"):
            with self.subTest(kind=kind):
                directory = self.root / kind
                directory.mkdir()
                master, canonical, manifest = synthetic(directory, 1)
                with pikepdf.open(master, allow_overwriting_input=True) as pdf:
                    if kind == "info":
                        pdf.docinfo["/Subject"] = json.dumps(manifest)
                    elif kind == "xmp":
                        pdf.Root.Metadata = pdf.make_stream(
                            b'<x xmlns:ulsbs="urn:ulsbs:multikey:1"><ulsbs:multikey/></x>')
                        pdf.Root.Metadata.Type, pdf.Root.Metadata.Subtype = (
                            pikepdf.Name.Metadata, pikepdf.Name.XML)
                    elif kind == "attachment":
                        pdf.attachments["metadata.json"] = json.dumps(manifest).encode()
                    else:
                        pdf.Root["/ulsbs:multikey"] = "payload"
                    pdf.save(master, fix_metadata_version=False)
                with self.assertRaisesRegex(ValueError, "ULSBS JSON"):
                    package_ranges(master, canonical, manifest, directory / "stage")

    def test_qpdf_failure_version_gate_and_safe_explicit_argv(self):
        master, canonical, manifest = synthetic(self.root, 1)
        real_run = subprocess.run
        calls = []
        def run(argv, **kwargs):
            calls.append(argv)
            return real_run(argv, **kwargs)
        with patch("ulsbs.multikey_ranges.subprocess.run", side_effect=run):
            package_ranges(master, canonical, manifest, self.root / "stage")
        extraction = next(call for call in calls if "--pages" in call)
        self.assertEqual(extraction[:7], ["qpdf", str(master.resolve()), "--deterministic-id",
                                         "--pages", ".", "1-1", "--"])
        self.assertTrue(any(call[1] == "--check" for call in calls))
        with patch("ulsbs.multikey_ranges._run", return_value="qpdf version 12.1.0"):
            with self.assertRaisesRegex(ValueError, "12.2.0"):
                package_ranges(master, canonical, manifest, self.root / "old")
        with patch("ulsbs.multikey_ranges.subprocess.run", return_value=subprocess.CompletedProcess(
                ["qpdf"], 2, "", "synthetic failure")):
            with self.assertRaisesRegex(ValueError, "synthetic failure"):
                package_ranges(master, canonical, manifest, self.root / "failed")

    def test_broken_extraction_and_failed_final_check_clean_only_new_files(self):
        master, canonical, manifest = synthetic(self.root, 2)
        stage = self.root / "stage"
        stage.mkdir()
        unrelated = stage / "unrelated.bin"
        unrelated.write_bytes(b"keep")
        real_run = subprocess.run
        def broken(argv, **kwargs):
            result = real_run(argv, **kwargs)
            if "--pages" in argv:
                Path(argv[-1]).write_bytes(b"not a PDF")
            return result
        with patch("ulsbs.multikey_ranges.subprocess.run", side_effect=broken):
            with self.assertRaises((ValueError, pikepdf.PdfError)):
                package_ranges(master, canonical, manifest, stage)
        self.assertEqual(list(stage.iterdir()), [unrelated])
        def failed_check(argv, **kwargs):
            if "--check" in argv:
                return subprocess.CompletedProcess(argv, 2, "", "synthetic check failed")
            return real_run(argv, **kwargs)
        with patch("ulsbs.multikey_ranges.subprocess.run", side_effect=failed_check):
            with self.assertRaisesRegex(ValueError, "synthetic check failed"):
                package_ranges(master, canonical, manifest, stage)
        self.assertEqual(list(stage.iterdir()), [unrelated])

    def test_named_destination_action_and_pdf_name_encoding(self):
        master, canonical, manifest = synthetic(self.root, 3)
        with pikepdf.open(master, allow_overwriting_input=True) as pdf:
            link = pdf.pages[0].obj.Annots[0]
            del link["/Dest"]
            link.A = pikepdf.Dictionary(S=pikepdf.Name.GoTo, D=pikepdf.Name("/book-end"))
            pdf.save(master)
        package_ranges(master, canonical, manifest, self.root / "stage", max_pages=1)
        with pikepdf.open(master, allow_overwriting_input=True) as pdf:
            pdf.pages[0].obj.Annots[0].A.D = pikepdf.String("missing-name")
            pdf.save(master)
        with self.assertRaisesRegex(ValueError, "missing from ordinary"):
            package_ranges(master, canonical, manifest, self.root / "missing")

    def test_catalog_loss_and_changed_alternative_are_rejected(self):
        master, _, _ = synthetic(self.root, 3)
        output = self.root / "empty.pdf"
        subprocess.run(["qpdf", "--empty", "--pages", str(master), "1", "--", str(output)],
                       check=True, capture_output=True)
        with pikepdf.open(master) as source, pikepdf.open(output) as candidate:
            self.assertNotIn("/OCProperties", candidate.Root)
            with self.assertRaises(ValueError):
                _check_range(source, candidate, 1, 1, _destinations(source))
        subprocess.run(["qpdf", str(master), "--deterministic-id", "--pages", ".", "1", "--",
                        str(output)], check=True, capture_output=True)
        with pikepdf.open(output, allow_overwriting_input=True) as pdf:
            data = pdf.pages[0].obj.Contents.read_bytes().replace(b"Alternative 11", b"Changed key 11")
            pdf.pages[0].obj.Contents = pdf.make_stream(data)
            pdf.save(output)
        with pikepdf.open(master) as source, pikepdf.open(output) as candidate:
            with self.assertRaisesRegex(ValueError, "stream"):
                _check_range(source, candidate, 1, 1, _destinations(source))

    def test_ocg_state_font_and_unrequested_graph_mutations_are_rejected(self):
        master, _, _ = synthetic(self.root, 3)
        output = self.root / "candidate.pdf"
        for kind in ("state", "font", "page"):
            subprocess.run(["qpdf", str(master), "--deterministic-id", "--pages", ".", "1", "--",
                            str(output)], check=True, capture_output=True)
            with pikepdf.open(output, allow_overwriting_input=True) as pdf:
                if kind == "state":
                    pdf.Root.OCProperties.OCGs[0].Usage.View.ViewState = pikepdf.Name.OFF
                elif kind == "font":
                    pdf.pages[0].obj.Resources.Font.F1.BaseFont = pikepdf.Name.Courier
                else:
                    with pikepdf.open(master) as source:
                        pdf.Root.RetainedPage = pdf.copy_foreign(source.pages[-1].obj)
                pdf.save(output)
            with pikepdf.open(master) as source, pikepdf.open(output) as candidate:
                with self.assertRaises(ValueError):
                    _check_range(source, candidate, 1, 1, _destinations(source))

    def test_split_pages_catalog_loss_regression(self):
        master, _, _ = synthetic(self.root, 3)
        subprocess.run(["qpdf", str(master), "--split-pages=2", str(self.root / "split.pdf")],
                       check=True, capture_output=True)
        with pikepdf.open(self.root / "split-1-2.pdf") as pdf:
            self.assertNotIn("/OCProperties", pdf.Root)

    def test_retained_unselected_pages_fail_not_silently_delete_outlines(self):
        master, canonical, manifest = synthetic(self.root, 3)
        with pikepdf.open(master, allow_overwriting_input=True) as pdf:
            pdf.Root.PrivatePageReference = pdf.pages[2].obj
            pdf.save(master)
        with self.assertRaisesRegex(ValueError, "unrequested page|Changed PDF reference"):
            package_ranges(master, canonical, manifest, self.root / "stage", max_pages=1)
        self.assertEqual(list((self.root / "stage").iterdir()), [])

    def test_property_resource_convergence_check_includes_nested_forms(self):
        path = self.root / "properties.pdf"
        for nested in (False, True):
            with self.subTest(nested=nested), pikepdf.new() as pdf:
                page = pdf.add_blank_page(page_size=(100, 100))
                resources = pikepdf.Dictionary(Properties=pikepdf.Dictionary(
                    OtherTag=pikepdf.Dictionary(MCID=0)))
                page.Resources = resources
                resources = page.Resources
                pdf.save(path)
                check_pdf_property_resources(path)  # Non-OCG property lists are legal.
                invalid = pdf.make_stream(b"q Q")
                target = resources
                if nested:
                    form = pdf.make_stream(b"q Q")
                    form.Type, form.Subtype = pikepdf.Name.XObject, pikepdf.Name.Form
                    form.BBox = [0, 0, 100, 100]
                    form.Resources = pikepdf.Dictionary(Properties=pikepdf.Dictionary())
                    resources.XObject = pikepdf.Dictionary(Wrapper=form)
                    target = form.Resources
                target.Properties.Broken = invalid
                pdf.save(path)
                with self.assertRaisesRegex(ValueError, r"/Broken on page 1.*got stream"):
                    check_pdf_property_resources(path)

    def test_encoded_index_enforces_byte_limit_inclusively(self):
        with patch("ulsbs.multikey_ranges.MULTIKEY_INDEX_MAX_BYTES", 4):
            self.assertEqual(_encoded("\u00e9"), b'"\xc3\xa9"')
            with self.assertRaisesRegex(ValueError, "exceeds 4 bytes"):
                _encoded("\u00e9a")

    def test_malformed_indices_and_integrity_checks(self):
        _, canonical, _, path, index = self.package(max_pages=2)
        mutations = [
            lambda x: x.update(extra=True),
            lambda x: x.update(page_count=True),
            lambda x: x.update(ranges=[]),
            lambda x: x["ranges"][1].update(first_page=2),
            lambda x: x["ranges"][1].update(first_page=4),
            lambda x: x["ranges"][0].update(file="../escape.pdf"),
            lambda x: x["ranges"][0].update(file="x%2f.pdf"),
            lambda x: x["ranges"][0].update(sha256="A" * 64),
            lambda x: x["ranges"][0].update(byte_length="oops"),
            lambda x: x["canonical"].update(file="https:book.pdf"),
            lambda x: x["geometry"][0].update(view=[0, 0, float("nan"), 1]),
            lambda x: x["geometry"][0].update(rotation=True),
            lambda x: x["packaging"].update(tool_version="11.0.0"),
            lambda x: x["manifest"]["multikey_info"]["songs"][0].update(
                song_id="x" * MULTIKEY_INDEX_MAX_BYTES),
        ]
        for mutation in mutations:
            bad = copy.deepcopy(index)
            mutation(bad)
            with self.assertRaises(ValueError):
                validate_index(bad, path, canonical)
        (path.parent / index["ranges"][0]["file"]).write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "size/hash"):
            validate_index(index, path, canonical)
        (path.parent / index["ranges"][0]["file"]).unlink()
        with self.assertRaises(FileNotFoundError):
            validate_index(index, path, canonical)

    def test_zero_pages_missing_canonical_and_changed_canonical_fail(self):
        master, canonical, manifest = synthetic(self.root, 1, layers=False, links=False)
        path = package_ranges(master, canonical, manifest, self.root / "stage")
        index = json.loads(path.read_text())
        canonical.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "Canonical size/hash"):
            validate_index(index, path, canonical)
        canonical.unlink()
        with self.assertRaises(FileNotFoundError):
            validate_index(index, path, canonical)
        for output in (master, canonical):
            with pikepdf.Pdf.new() as pdf:
                pdf.save(output)
        with self.assertRaisesRegex(ValueError, "page count"):
            package_ranges(master, canonical, manifest, self.root / "empty")

    def test_existing_family_is_not_overwritten(self):
        master, canonical, manifest, path, _ = self.package()
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "already contains"):
            package_ranges(master, canonical, manifest, path.parent)
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
