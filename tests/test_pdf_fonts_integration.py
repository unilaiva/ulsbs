# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Real lilypond-book/LuaLaTeX pipeline and embedded-font preservation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import warnings
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pikepdf

from ulsbs import pipeline, resultlist
from ulsbs.config import Config
from ulsbs.engine_assets import EngineAssets
from ulsbs.jobs import Job, build_job_basename
from ulsbs.multikey_ranges import validate_index
from ulsbs.pdf_fonts import _check_equivalent, deduplicate_fonts


class LilyPondFontSharingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for tool in ("lilypond-book", "lilypond", "lualatex", "qpdf", "pdffonts", "pdftoppm", "pdftotext"):
            if shutil.which(tool) is None:
                raise unittest.SkipTest(f"{tool} is not installed")

    def test_cold_and_warm_pipeline_preserve_embedded_fonts_staging_and_midi(self):
        self.check_cold_and_warm_pipeline(multikey=False)

    def test_multikey_pipeline_preserves_fonts_metadata_and_all_key_selections(self):
        self.check_cold_and_warm_pipeline(multikey=True)

    def check_cold_and_warm_pipeline(self, *, multikey):
        with tempfile.TemporaryDirectory(prefix="ulsbs-font-integration-") as temporary:
            root = Path(temporary)
            content = root / "content"
            content.mkdir()
            (root / "include").mkdir()
            result = root / "result"
            result.mkdir()
            cache = root / "texmf-cache"
            cache.mkdir()
            doc = root / "ul-selection_fonts_A5.tex"
            doc.write_text(
                r"\documentclass[maintitle={Font Sharing Test}]{ulsbs-songbook}" + "\n"
                r"\begin{document}\begin{songs}{}\input{content/song.tex}"
                r"\end{songs}\end{document}" + "\n", encoding="utf-8",
            )
            # Direct grob font selection works in both LilyPond 2.24 and 2.26;
            # the optimizer does not depend on their different global-font APIs.
            (content / "common.ily").write_text(
                'words = \\lyricmode { "A\u00e7\u00e3o" "b\u00ean\u00e7\u00e3o" "luz" "paz" }'
                + "\n" + r'\layout { \context { \Lyrics \override LyricText.font-name = "Noto Sans" } }'
                + "\n", encoding="utf-8",
            )
            snippets = []
            for index, notes in enumerate(("c4 d e f", "f4 e d c")):
                snippets.append(
                    rf"\beginsong{{Song {index}}}[id={{font-song-{index}}},key={{C}}]" + "\n"
                    r"\beginverse |\[C]Test |\[G7]lyrics.\endverse" + "\n"
                    r"\begin{lilywrap}\begin{lilypond}[]" + "\n"
                    r'\include "common.ily"' + "\n"
                    "\\score { << \\new Voice = \"melody\" { \\relative c' { " + notes + r' } }'
                    + '\n' + r'\new Lyrics \lyricsto "melody" { \words } >>'
                    + "\n" + r"\layout {} \midi {} }" + "\n"
                    r"\end{lilypond}\end{lilywrap}\endsong" + "\n"
                )
            (content / "song.tex").write_text(
                "\\end{songs}\\clearpage\\begin{songs}{}\n".join(snippets), encoding="utf-8",
            )
            paths = SimpleNamespace(project_root=root, result_dir=result,
                                    content_dir=content, include_dir=root / "include")
            cfg = replace(
                Config(), runtime=SimpleNamespace(project_paths=paths, in_container=False),
                create_printouts=False, coverimage=False, multikey_books=multikey,
                audiofiles=False, midifiles=True, json=True, clean_temp=False,
                multikey_max_pages_per_range=1,
            )
            job = Job(doc, doc.stem, "default", root / "job", multikey=multikey)
            basename = build_job_basename(job)
            job.compile_dir.mkdir()
            ui = Mock()
            ui.fmt_doc.return_value = "[font integration]"
            ui.colorize.side_effect = lambda text, color: text
            baseline = root / "baseline.pdf"
            measurements = []
            source_snapshots = []

            def optimize(path):
                shutil.copy2(path, baseline)
                source_snapshots.append({
                    p: p.read_bytes() for p in job.compile_dir.rglob("*")
                    if p.is_file() and p.suffix in (".tex", ".ly", ".ily", ".midi")
                })
                measurement = deduplicate_fonts(path)
                measurements.append(measurement)
                return measurement

            resultlist.initialize(result, "font-integration")
            try:
                ordinary_job = None
                if multikey:
                    ordinary_job = replace(job, compile_dir=root / "ordinary-job", multikey=False)
                    ordinary_job.compile_dir.mkdir()
                    with patch.dict(os.environ, {
                        "TEXMFVAR": str(cache), "TEXMFCACHE": str(cache),
                    }):
                        pipeline.compile_one_job(
                            ui, EngineAssets(), replace(cfg, json=False, midifiles=False), ordinary_job,
                        )
                    canonical = result / f"{build_job_basename(ordinary_job)}.pdf"
                    canonical_bytes = canonical.read_bytes()
                for build in ("cold", "warm"):
                    with self.subTest(build=build), patch.dict(os.environ, {
                        "TEXMFVAR": str(cache), "TEXMFCACHE": str(cache),
                    }), patch("ulsbs.pdf_fonts.deduplicate_fonts", side_effect=optimize):
                        try:
                            compilation = pipeline.compile_one_job(ui, EngineAssets(), cfg, job)
                            if multikey:
                                pipeline.finish_multikey_job(ui, cfg, job, ordinary_job, compilation)
                        except pipeline.CompileError as error:
                            logs = "\n".join(p.read_text(errors="replace") for p in job.compile_dir.glob("*.log"))
                            self.fail(f"{error}\n{logs}")
                        before, after, removed = measurements[-1]
                        self.assertLess(after, before)
                        self.assertGreater(removed, 0)
                        optimized_pdf = job.compile_dir / f"{basename}.pdf"
                        self.assertEqual(optimized_pdf.stat().st_size, after)
                        if multikey:
                            self.assertFalse(list(result.rglob(optimized_pdf.name)))
                        else:
                            self.assertEqual((result / optimized_pdf.name).read_bytes(), optimized_pdf.read_bytes())
                        self.assertTrue((job.compile_dir / "content" / "song.tex").is_file())
                        for source, data in source_snapshots[-1].items():
                            self.assertEqual(source.read_bytes(), data, str(source))
                        with pikepdf.open(baseline) as original, pikepdf.open(optimized_pdf) as optimized:
                            _check_equivalent(original, optimized)
                            pages = len(original.pages)
                            if multikey:
                                groups = optimized.Root.OCProperties.OCGs
                                self.assertEqual(len(groups), 24)
                                self.assertEqual({str(group.Name) for group in groups}, {
                                    f"ulsbs:transpose:v1:id:font-song-{song}:t{offset:02d}"
                                    for song in range(2) for offset in range(12)
                                })
                                self.assertNotIn('/Metadata', optimized.Root)
                                manifest = json.loads((job.compile_dir / f"{basename}.ulsbs-multikey.json").read_text())
                                self.assertIs(manifest["has_multikey_info"], True)
                        ranges = []
                        if multikey:
                            # The optimized master stays private. Validate the
                            # published index against the unchanged ordinary PDF.
                            self.assertEqual(pages, 2, "The fixture must exercise actual page extraction")
                            index_path = result / "multikey" / f"{basename}_RANGES.json"
                            index = json.loads(index_path.read_text())
                            validate_index(index, index_path, canonical)
                            self.assertEqual(index["manifest"], manifest)
                            self.assertEqual(canonical.read_bytes(), canonical_bytes)
                            ranges = [(entry, index_path.parent / entry["file"]) for entry in index["ranges"]]
                            self.assertEqual(len(ranges), pages)
                            print(
                                f"Font/range measurements ({build}, qpdf {index['packaging']['tool_version']}): "
                                f"baseline={before}, optimized={after}, "
                                f"ranges={[path.stat().st_size for _, path in ranges]} bytes",
                                flush=True,
                            )
                        for path in [optimized_pdf, *(path for _, path in ranges)]:
                            inventory = subprocess.check_output(["pdffonts", str(path)], text=True)
                            font_rows = inventory.splitlines()[2:]
                            self.assertTrue(font_rows, str(path))
                            self.assertTrue(all(row.split()[-5] == "yes" for row in font_rows), inventory)
                            self.assertIn("NotoSans", inventory)
                            self.assertIn("Emmentaler", inventory)
                        for page in range(1, pages + 1):
                            command = ["pdftoppm", "-r", "96", "-f", str(page), "-singlefile", "-png"]
                            self.assertEqual(subprocess.check_output(command + [str(baseline)]),
                                             subprocess.check_output(command + [str(optimized_pdf)]))
                        command = ["pdftotext", "-bbox"]
                        self.assertEqual(subprocess.check_output(command + [str(baseline), "-"]),
                                          subprocess.check_output(command + [str(optimized_pdf), "-"]))
                        if multikey:
                            rasters = []
                            for offset in range(12):
                                selected = []
                                save_warnings = []
                                for source in (baseline, optimized_pdf, *(path for _, path in ranges)):
                                    selected_pdf = root / f"selected-{len(selected)}.pdf"
                                    with pikepdf.open(source) as pdf:
                                        groups = pdf.Root.OCProperties.OCGs
                                        configuration = pdf.Root.OCProperties.D
                                        configuration.BaseState = pikepdf.Name.OFF
                                        configuration.ON = pikepdf.Array([
                                            group for group in groups if str(group.Name).endswith(f":t{offset:02d}")
                                        ])
                                        configuration.OFF = pikepdf.Array([
                                            group for group in groups if not str(group.Name).endswith(f":t{offset:02d}")
                                        ])
                                        with warnings.catch_warnings(record=True) as caught:
                                            pdf.save(selected_pdf)
                                        save_warnings.append([str(w.message) for w in caught])
                                    with pikepdf.open(selected_pdf) as pdf:
                                        selected_pages = len(pdf.pages)
                                    selected.append(tuple(subprocess.check_output([
                                        "pdftoppm", "-r", "96", "-f", str(page),
                                        "-singlefile", "-png", str(selected_pdf),
                                    ]) for page in range(1, selected_pages + 1)))
                                self.assertEqual(selected[0], selected[1], f"key offset {offset}")
                                self.assertEqual(save_warnings[0], save_warnings[1])
                                for (entry, _), raster in zip(ranges, selected[2:], strict=True):
                                    # Index bounds are one-based and inclusive;
                                    # compare each extracted page in every key.
                                    self.assertEqual(
                                        raster, selected[1][entry["first_page"] - 1:entry["last_page"]],
                                        f"range {entry['file']}, key offset {offset}",
                                    )
                                rasters.append(selected[0])
                            self.assertGreater(len(set(rasters)), 1, "key selections must visibly change the PDF")
                            self.assertFalse((result / "json" / f"{basename}.json").exists())
                            self.assertFalse((result / "midi").exists())
                            self.assertFalse((result / "audio").exists())
                            continue
                        metadata = json.loads((result / "json" / f"{doc.stem}.json").read_text())
                        songs = metadata["songs_without_chapter"]
                        self.assertEqual(len(songs), 2)
                        self.assertTrue(list(job.compile_dir.glob("**/*.midi")))
                        processed = (job.compile_dir / "content" / "song.tex").read_text()
                        if "lilypondbook" in processed:
                            # Production 2.24's generated marker drives MIDI discovery.
                            for song in songs:
                                midi = song.get("midi_result_file_relative")
                                self.assertIsNotNone(midi)
                                self.assertTrue((result / midi).is_file(), midi)
                        else:
                            # 2.26 removed that marker. This pre-existing migration
                            # issue is independent of PDF rewriting; generated MIDI
                            # and the exact processed source tree must still survive.
                            self.assertTrue(all("midi_compile_file_relative" not in s for s in songs))
            finally:
                resultlist.delete()


if __name__ == "__main__":
    unittest.main()
