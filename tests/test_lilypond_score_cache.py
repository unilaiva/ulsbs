# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Persistent score cache tests; no LilyPond/TeX execution required."""

import io
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pikepdf

from ulsbs import lilypond_score_cache as cache


class ScoreCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ulsbs score cache ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.job = self.root / "job"
        self.job.mkdir()
        self.assets = self.root / "assets"
        self.assets.mkdir()
        self.data = self.root / "installed"
        (self.data / "ly").mkdir(parents=True)
        (self.data / "ly/lilypond-book-preamble.ly").write_text("#(define trusted #t)\n")
        self.toolchain = cache.ToolchainFingerprint("a" * 64, self.data)
        self.source = self.job / "snippet.ly"
        self.source.write_text('\\include "head.ly"\n{ c4 d4 }\n')
        (self.assets / "head.ly").write_text('\\include "nested.ily"\n')
        (self.assets / "nested.ily").write_text("notes = { e4 }\n")
        self.env = {"HOME": str(self.root), "ULSBS_SCORE_CACHE_DIR": str(self.root / "cache")}
        self.stem = self.job / "t01"
        self.key = self.candidate()

    def fingerprint(self, source=None, **kwargs):
        return cache.source_fingerprint(
            source or self.source, kwargs.pop("include_args", ["-I", str(self.assets)]),
            cwd=kwargs.pop("cwd", self.job), env=kwargs.pop("env", self.env),
            toolchain=kwargs.pop("toolchain", self.toolchain), **kwargs)

    def candidate(self, **kwargs):
        inputs = dict(signed=1, spelled=("c", "des"), original_dimensions=(100, 50),
                      original_boundaries=[0, 0, 100, 50], extra={"mode": "major"})
        inputs.update(kwargs)
        return cache.candidate_key(self.fingerprint(), **inputs)

    def artifacts(self, stem=None, *, size=(100, 50), pages=1, log="warning: harmless\n"):
        stem = stem or self.stem
        stem.parent.mkdir(parents=True, exist_ok=True)
        with pikepdf.Pdf.new() as pdf:
            for _ in range(pages):
                pdf.add_blank_page(page_size=size)
            pdf.save(stem.with_name(stem.name + "-1.pdf"))
        stem.with_suffix(".log").write_text(log)

    def publish(self, **kwargs):
        inputs = dict(success=True, original_dimensions=(100, 50), env=self.env,
                      metadata={"boundary_info": [0, 1], "status": "transposed"})
        inputs.update(kwargs)
        return cache.publish(self.key, self.stem, **inputs)

    def test_root_precedence_and_relative_paths_disable_cache(self):
        self.assertEqual(cache.cache_root(self.env), self.root / "cache")
        self.assertEqual(cache.cache_root({"XDG_CACHE_HOME": str(self.root)}),
                         self.root / "ulsbs/lilypond-scores")
        self.assertEqual(cache.cache_root({"HOME": str(self.root)}),
                         self.root / ".cache/ulsbs/lilypond-scores")
        self.assertIsNone(cache.cache_root({"ULSBS_SCORE_CACHE_DIR": "relative"}))

    def test_clear_cache_preserves_unrelated_files_and_in_progress_publications(self):
        root = cache.cache_root(self.env)
        self.assertEqual(cache.clear_cache(env=self.env), (root, 0))
        self.assertFalse(root.exists())
        self.artifacts()
        self.assertTrue(self.publish())
        (root / "notes.txt").write_text("keep unrelated files")
        staging = root / ".publish-active"
        staging.mkdir()
        (staging / "artifact.log").write_text("still writing")
        # Corrupt entries can be cleared without trusting their manifests.
        corrupt = root / ("c" * 64)
        corrupt.mkdir()
        (corrupt / "manifest.json").write_text("corrupt JSON")
        self.assertEqual(cache.clear_cache(env=self.env), (root, 2))
        self.assertEqual(sorted(path.name for path in root.iterdir()), [".publish-active", "notes.txt"])
        self.assertEqual((staging / "artifact.log").read_text(), "still writing")
        self.assertEqual(cache.clear_cache(env=self.env), (root, 0))

    def test_clear_cache_unlinks_symlinks_without_following_targets(self):
        root = cache.cache_root(self.env)
        root.mkdir()
        external = self.root / "external"
        external.mkdir()
        keep = external / "artifact.log"
        keep.write_text("keep target")
        (root / ("a" * 64)).symlink_to(external, target_is_directory=True)
        entry = root / ("b" * 64)
        entry.mkdir()
        (entry / "artifact.log").symlink_to(keep)
        self.assertEqual(cache.clear_cache(env=self.env), (root, 2))
        self.assertEqual(keep.read_text(), "keep target")
        root.rmdir()
        root.symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlinked"):
            cache.clear_cache(env=self.env)
        self.assertEqual(keep.read_text(), "keep target")

    def test_clear_cache_refuses_unsafe_inputs_before_removing_entries(self):
        with self.assertRaisesRegex(ValueError, "absolute"):
            cache.clear_cache(env={"ULSBS_SCORE_CACHE_DIR": "relative"})
        self.artifacts()
        self.assertTrue(self.publish())
        root = cache.cache_root(self.env)
        unexpected = root / ("f" * 64)
        unexpected.mkdir()
        (unexpected / "user-data").mkdir()
        with self.assertRaisesRegex(ValueError, "unrecognized"):
            cache.clear_cache(env=self.env)
        self.assertTrue((root / self.key / "manifest.json").is_file())
        self.assertTrue((unexpected / "user-data").is_dir())
        ordinary_file = self.root / "not-a-directory"
        ordinary_file.write_text("keep")
        with self.assertRaisesRegex(ValueError, "not a directory"):
            cache.clear_cache(env={"ULSBS_SCORE_CACHE_DIR": str(ordinary_file)})

    def test_clear_cache_reports_removal_errors(self):
        self.artifacts()
        self.assertTrue(self.publish())
        with patch.object(cache.shutil, "rmtree", side_effect=PermissionError("read-only cache")):
            with self.assertRaisesRegex(PermissionError, "read-only"):
                cache.clear_cache(env=self.env)

    def test_clear_cache_preserves_unrelated_hash_named_regular_files(self):
        self.artifacts()
        self.assertTrue(self.publish())
        root = cache.cache_root(self.env)
        unrelated = root / ("f" * 64)
        unrelated.write_text("unrelated content-addressed download")
        with self.assertRaisesRegex(ValueError, "non-directory cache entry"):
            cache.clear_cache(env=self.env)
        self.assertEqual(unrelated.read_text(), "unrelated content-addressed download")
        self.assertTrue((root / self.key / "manifest.json").is_file())

    def test_recursive_dependencies_source_layout_and_include_args(self):
        before = self.fingerprint()
        self.assertIsNotNone(before)
        for args in (["-I" + str(self.assets)], ["--include=" + str(self.assets)],
                     ["--include", str(self.assets)]):
            self.assertEqual(before, self.fingerprint(include_args=args))
        (self.assets / "nested.ily").write_text("notes = { f4 }\n")
        self.assertNotEqual(before, self.fingerprint())
        before = self.fingerprint()
        self.source.write_text(self.source.read_text() + "% exact layout matters\n")
        self.assertNotEqual(before, self.fingerprint())
        self.assertIsNone(self.fingerprint(include_args=["-I"]))
        self.assertIsNone(self.fingerprint(include_args=["-e", "arbitrary"]))

    def test_source_directory_cwd_nested_resolution_and_installed_preamble(self):
        self.source.write_text('\\include "local.ily"\n\\include "lilypond-book-preamble.ly"\n')
        (self.job / "local.ily").write_text('{ c4 }\n')
        before = self.fingerprint()
        self.assertIsNotNone(before)
        (self.data / "ly/lilypond-book-preamble.ly").write_text("#(define changed #f)\n")
        self.assertNotEqual(before, self.fingerprint())
        nested = self.job / "sub/snippet.ly"
        nested.parent.mkdir()
        nested.write_bytes(self.source.read_bytes())
        self.assertIsNotNone(self.fingerprint(source=nested))

    def test_missing_ambiguous_dynamic_cycles_and_scheme_are_ineligible(self):
        for text in ('\\include "missing.ly"', '\\include variable',
                     '#(load "file.scm")', '#(eval (read))', '$(read)',
                     '\\epsfile #X #10 "picture.eps"', '%{ unterminated'):
            with self.subTest(text=text):
                self.source.write_text(text)
                self.assertIsNone(self.fingerprint())
        self.source.write_text('\\include "head.ly"')
        (self.job / "head.ly").write_text('{ d4 }')
        self.assertIsNone(self.fingerprint())
        (self.job / "head.ly").unlink()
        (self.assets / "nested.ily").write_text('\\include "head.ly"')
        self.assertIsNone(self.fingerprint())

    def test_comments_strings_and_safe_literals(self):
        self.source.write_text('% \\include "missing.ly"\n'
                               '%{ nested %{ x %} \\include "bad.ly" %}\n'
                               'title = "100% # music"\n'
                               '#(set-global-staff-size 16)\n'
                               "#(ly:set-option 'eps-box-padding 3.000000)\n"
                               'line-width = #(- line-width (* mm  3.000000) (* mm 1))\n'
                               '#(set-paper-size "a5")\n'
                               "#(set-paper-size '(cons (* 421.10 pt) (* 597.51 pt)))\n"
                               '\\paper { indent = #0 ragged-right = ##f }\n{ c4 }')
        self.assertIsNotNone(self.fingerprint())
        self.source.write_text('title = "\\\" % escaped quote"\n{ c4 }')
        self.assertIsNotNone(self.fingerprint())

    def test_quoted_scheme_literals_are_data_not_evaluation(self):
        for value in ("#'()", "#'( )", "#'(melismaBusy slurMelismaBusy)",
                      "#'melismaBusy", "#'(load eval read)", "#'(item 1 -2.5 #t #f)",
                      '#\'(label "literal #.(read) text")'):
            with self.subTest(value=value):
                self.source.write_text(r"\set melismaBusyProperties = " + value + "\n{ c4 }")
                self.assertIsNotNone(self.fingerprint())
        for value in ("#(load \"external.scm\")", "#'(a #.(read))", "#`(a ,(read))",
                      "#'(a . b)", "#'((a b))", "#'(a", "#'() #(eval (read))",
                      "#'(a #! reader-extension)"):
            with self.subTest(value=value):
                self.source.write_text("value = " + value)
                self.assertIsNone(self.fingerprint())

    def test_generated_numeric_paper_size_is_narrow_and_content_addressed(self):
        self.source.write_text("#(set-paper-size '(cons (* 421.10 pt) (* 597.51 pt)))\n{ c4 }")
        before = self.fingerprint()
        self.assertIsNotNone(before)
        self.source.write_text(self.source.read_text().replace("421.10", "422.10"))
        self.assertNotEqual(before, self.fingerprint())
        for expression in ("#(set-paper-size '(cons (* (read) pt) (* 597.51 pt)))",
                           "#(set-paper-size (cons (* 421.10 pt) (* 597.51 pt)))",
                           "#(set-paper-size '(cons (* 421.10 pt) (* (load \"x\") pt)))"):
            self.source.write_text(expression)
            self.assertIsNone(self.fingerprint())

    def test_debug_logging_explains_ineligible_source_and_publication_failure(self):
        self.source.write_text('#(load "external.scm")')
        with self.assertLogs(cache.__name__, level="DEBUG") as source_logs:
            self.assertIsNone(self.fingerprint())
        self.assertIn("source ineligible", source_logs.output[0])
        self.assertIn(str(self.source), source_logs.output[0])
        self.assertIn("custom Scheme", source_logs.output[0])
        with self.assertLogs(cache.__name__, level="DEBUG") as publish_logs:
            self.assertFalse(self.publish())
        self.assertIn("publication failed", publish_logs.output[0])

    def test_duplicate_include_aliases_resolve_to_one_dependency(self):
        alias = self.root / "alias"
        alias.symlink_to(self.assets, target_is_directory=True)
        before = self.fingerprint(include_args=["-I", str(self.assets), "-I", str(alias)])
        self.assertIsNotNone(before)
        self.assertEqual(before, self.fingerprint(
            include_args=["-I", str(self.assets), "-I", str(self.assets)]))

    def test_real_standard_assets_and_nested_changes(self):
        self.source.write_text('\\include "ulsbs-include-head.ly"\n'
                               '\\include "lilypond-book-preamble.ly"\n'
                               'theMelody = { c4 }\n\\include "ulsbs-include-tail.ly"\n')
        self.assertIsNotNone(self.fingerprint(include_args=["-I" + str(cache._BUNDLED)]))
        copied = self.assets / "ulsbs-include-head.ly"
        copied.write_bytes((cache._BUNDLED / copied.name).read_bytes())
        copied.write_text(copied.read_text() + '\n#(load "untracked.scm")')
        self.assertIsNone(self.fingerprint())

    def test_asset_audit_recognizes_bundled_and_exact_pipeline_mutations(self):
        records = cache.audit_assets([cache._BUNDLED])
        self.assertTrue(records)
        self.assertTrue(all(trusted for _, _, trusted in records))
        midi = self.assets / "ulsbs-internal-score-midi.ly"
        midi.write_bytes(b"% MIDI generation is disabled for this edition.\n")
        self.assertTrue(cache.audit_assets([midi])[0][2])
        for filename, mutation in (
                ("ulsbs-internal-common-tail.ly", lambda data:
                 data + b'\n\\include "ulsbs-score-boundaries.ily"\n'),
                ("ulsbs-internal-common-head.ly", lambda data: data.replace(
                    b"%%%ULSBS-PLACEHOLDER-FOR-EXTRA-INSTRUMENT-VARIANT-CODE%%%\n",
                    b"%%%ULSBS-PLACEHOLDER-FOR-EXTRA-INSTRUMENT-VARIANT-CODE%%%\n"
                    b"ul-chosen-tuning = #ul-charango-tuning\n", 1))):
            with self.subTest(filename=filename):
                original = (cache._BUNDLED / filename).read_bytes()
                copied = self.assets / filename
                copied.write_bytes(mutation(original))
                self.assertEqual(cache.audit_assets([copied]), [
                    (copied, cache._digest(original), True)])
                copied.write_bytes(copied.read_bytes() + b"% edited\n")
                self.assertFalse(cache.audit_assets([copied])[0][2])

    def test_asset_audit_cli_is_read_only_with_actionable_statuses(self):
        copied = self.assets / "ulsbs-internal-common-tail.ly"
        original = (cache._BUNDLED / copied.name).read_bytes()
        for data, status, label in ((original, 0, "TRUSTED"),
                                    (original + b"% changed\n", 1, "UNTRUSTED")):
            with self.subTest(status=status):
                copied.write_bytes(data)
                stdout, stderr = io.StringIO(), io.StringIO()
                before = cache._TRUST_MANIFEST.read_bytes()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    self.assertEqual(cache.main([str(copied)]), status)
                self.assertEqual(copied.read_bytes(), data)
                self.assertEqual(cache._TRUST_MANIFEST.read_bytes(), before)
                self.assertIn(f"{label} {cache._digest(data)} {copied}", stdout.getvalue())
                self.assertEqual(bool(stderr.getvalue()), bool(status))
                if status:
                    self.assertIn("before rewriting the trusted-asset manifest", stderr.getvalue())
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(cache.main([]), 0)
        self.assertNotIn("UNTRUSTED", stdout.getvalue())
        self.assertTrue(stdout.getvalue())

    def test_asset_audit_cli_reports_missing_and_empty_inputs(self):
        empty = self.root / "empty"
        empty.mkdir()
        for path in (empty, self.root / "missing.ly"):
            with self.subTest(path=path):
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    self.assertEqual(cache.main([str(path)]), 2)
                self.assertEqual(stdout.getvalue(), "")
                self.assertIn("Asset audit failed", stderr.getvalue())

    def test_rewrite_refreshes_source_hashes_preserves_variants_and_is_deterministic(self):
        path = self.root / "trusted.json"
        path.write_text(json.dumps({"schema_version": 1, "assets": {"removed.ly": "a" * 64},
                                    "variants": {"supported-version": "b" * 64}}))
        variant = self.root / "converted.ly"
        variant.write_text("% separately reviewed generated variant\n{ c4 }\n")
        sources = {source.name: source.read_bytes() for source in self.assets.iterdir()}
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(cache, "_BUNDLED", self.assets), \
                patch.object(cache.subprocess, "run", side_effect=AssertionError("no execution")), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(cache.main(["--rewrite", "--manifest", str(path),
                                         "--variant", f"converted={variant}"]), 0)
            first = path.read_bytes()
            self.assertEqual(cache.main(["--rewrite", "--manifest", str(path)]), 0)
        self.assertEqual(path.read_bytes(), first)
        manifest = cache.load_asset_manifest(path)
        self.assertEqual(manifest["assets"], {name: cache._digest(data) for name, data in sources.items()})
        self.assertEqual(manifest["variants"], {"supported-version": "b" * 64,
                                              "converted": cache._digest(variant.read_bytes())})
        self.assertEqual(sources, {source.name: source.read_bytes() for source in self.assets.iterdir()})
        self.assertIn("Review the manifest diff", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")
        self.assertTrue(all(trusted for _, _, trusted in cache.audit_assets([self.assets], manifest=path)))

    def test_rewrite_failures_leave_manifest_unchanged_and_clean_temporary_files(self):
        path = self.root / "trusted.json"
        original = cache._TRUST_MANIFEST.read_bytes()
        path.write_bytes(original)
        with patch.object(cache, "_BUNDLED", self.assets):
            for variants in ([("bad/name", self.source)], [("missing", self.root / "missing.ly")]):
                with self.subTest(variants=variants), self.assertRaises((ValueError, OSError)):
                    cache.rewrite_asset_manifest(path=path, variants=variants)
                self.assertEqual(path.read_bytes(), original)
            with patch.object(cache.os, "replace", side_effect=PermissionError("read-only")):
                with self.assertRaises(PermissionError):
                    cache.rewrite_asset_manifest(path=path)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(self.root.glob(".trusted.json-*")), [])
            alias = self.root / "alias.json"
            alias.symlink_to(path)
            with self.assertRaisesRegex(ValueError, "symlinked"):
                cache.rewrite_asset_manifest(path=alias)
        self.assertEqual(path.read_bytes(), original)

    def test_rewrite_can_create_a_manifest_but_requires_explicit_mode_for_variants(self):
        path = self.root / "new.json"
        with patch.object(cache, "_BUNDLED", self.assets):
            manifest = cache.rewrite_asset_manifest(path=path)
        self.assertEqual(manifest["variants"], {})
        self.assertEqual(cache.load_asset_manifest(path), manifest)
        before = path.read_bytes()
        for args in (["--variant", f"converted={self.source}"],
                     ["--rewrite", str(self.source)],
                     ["--rewrite", "--variant", "missing-equals"]):
            with self.subTest(args=args), redirect_stderr(io.StringIO()):
                if "missing-equals" in args:
                    self.assertEqual(cache.main(["--manifest", str(path), *args]), 2)
                else:
                    with self.assertRaises(SystemExit) as error:
                        cache.main(["--manifest", str(path), *args])
                    self.assertEqual(error.exception.code, 2)
            self.assertEqual(path.read_bytes(), before)

    def test_invalid_or_missing_trust_manifest_disables_cache_without_breaking_import(self):
        path = self.root / "invalid.json"
        with patch.object(cache, "_TRUST_MANIFEST", path):
            self.assertIsNone(self.fingerprint())
            for data in (b"not json", b"[]", b'{"schema_version":true,"assets":{},"variants":{}}',
                         b'{"schema_version":1,"assets":[],"variants":{}}',
                         b'{"schema_version":1,"assets":{"bad.ly":"not a hash"},"variants":{}}'):
                with self.subTest(data=data):
                    path.write_bytes(data)
                    self.assertIsNone(self.fingerprint())
                    with redirect_stderr(io.StringIO()):
                        self.assertEqual(cache.main([]), 2)
                    with self.assertRaises(ValueError):
                        cache.load_asset_manifest()

    def test_all_bundled_sources_are_manifested_and_have_maintenance_notices(self):
        sources = cache._asset_files([cache._BUNDLED])
        self.assertEqual(set(cache.load_asset_manifest()["assets"]), {source.name for source in sources})
        for source in sources:
            with self.subTest(source=source):
                header = "\n".join(source.read_text().splitlines()[:15])
                self.assertIn("assets/lilypond-score-cache-assets.json", header)
                self.assertIn("ulsbs-score-cache-assets --rewrite", header)

    def test_pipeline_boundary_instrumentation_retains_safe_eligibility(self):
        for source in cache._BUNDLED.iterdir():
            if source.is_file():
                (self.assets / source.name).write_bytes(source.read_bytes())
        self.source.write_text('\\include "ulsbs-include-head.ly"\n'
                               'theMelody = { c4 }\n\\include "ulsbs-include-tail.ly"\n')
        tail = self.assets / "ulsbs-internal-common-tail.ly"
        tail.write_bytes(tail.read_bytes() + b'\n\\include "ulsbs-score-boundaries.ily"\n')
        before = self.fingerprint()
        self.assertIsNotNone(before)
        helper = self.assets / "ulsbs-score-boundaries.ily"
        helper.write_bytes(helper.read_bytes() + b'\n#(load "external.scm")\n')
        self.assertIsNone(self.fingerprint())

    def test_exact_pipeline_instrument_variants_remain_eligible(self):
        for source in cache._BUNDLED.iterdir():
            if source.is_file():
                (self.assets / source.name).write_bytes(source.read_bytes())
        self.source.write_text('\\include "ulsbs-include-head.ly"\n'
                               'theMelody = { c4 }\n\\include "ulsbs-include-tail.ly"\n')
        before = self.fingerprint()
        head = self.assets / "ulsbs-internal-common-head.ly"
        original = head.read_bytes()
        marker = b"%%%ULSBS-PLACEHOLDER-FOR-EXTRA-INSTRUMENT-VARIANT-CODE%%%\n"
        insertion = b"ul-chosen-tuning = #ul-charango-tuning\n"
        head.write_bytes(original.replace(marker, marker + insertion, 1))
        charango = self.fingerprint()
        self.assertIsNotNone(charango)
        self.assertNotEqual(before, charango)
        head.write_bytes(head.read_bytes() + b'\n#(load "external.scm")\n')
        self.assertIsNone(self.fingerprint())
        head.write_bytes(original.replace(marker, marker + insertion * 2, 1))
        self.assertIsNone(self.fingerprint())
        head.write_bytes(original)
        tail = self.assets / "ulsbs-include-tail.ly"
        tail.write_bytes((self.assets / "ulsbs-include-tail_bassclef.ly").read_bytes())
        bassclef = self.fingerprint()
        self.assertIsNotNone(bassclef)
        self.assertNotEqual(before, bassclef)

    def test_audited_host_converted_tail_is_eligible_but_other_changes_are_not(self):
        # Reconstruct the audited convert-ly output without running a process.
        original = (cache._BUNDLED / "ulsbs-internal-common-tail.ly").read_text()
        start = original.index("      #(define fonts\n")
        end = original.index("        ))\n", start) + len("        ))\n")
        fonts = ('      property-defaults.fonts.serif = "Noto Sans Medium"\n'
                 '      property-defaults.fonts.sans = "Noto Sans Medium"\n'
                 '      property-defaults.fonts.typewriter = "Noto Sans Mono Medium"\n')
        converted = '\\version "2.26.0"\n' + original[:start] + fonts + original[end:]
        self.assertIn(cache._digest(converted.encode()), cache._trusted_assets())
        for source in cache._BUNDLED.iterdir():
            if source.is_file():
                (self.assets / source.name).write_bytes(source.read_bytes())
        tail = self.assets / "ulsbs-internal-common-tail.ly"
        self.source.write_text('\\include "ulsbs-include-head.ly"\n'
                               'theMelody = { c4 }\n\\include "ulsbs-include-tail.ly"\n')
        tail.write_text(converted)
        self.assertIsNotNone(self.fingerprint())
        tail.write_text(converted + '\n\\include "ulsbs-score-boundaries.ily"\n')
        self.assertIsNotNone(self.fingerprint())
        self.assertTrue(cache.audit_assets([tail])[0][2])
        tail.write_text(tail.read_text() + '\n#(load "external.scm")\n')
        self.assertIsNone(self.fingerprint())

    def test_relocated_jobs_share_but_external_environment_and_paths_matter(self):
        second = self.root / "other-job"
        second.mkdir()
        source = second / self.source.name
        source.write_bytes(self.source.read_bytes())
        self.assertEqual(self.fingerprint(), self.fingerprint(source=source, cwd=second))
        self.assertNotEqual(self.fingerprint(), self.fingerprint(env={**self.env, "LANG": "fi_FI"}))
        self.assertEqual(self.fingerprint(), self.fingerprint(env={
            **self.env, "HOSTNAME": "new-container", "ULSBS_INTERNAL_UNIQUE_ID": "new-build",
            "TEXINPUTS": "/new/temp/directory:", "PWD": "/other-job", "SHLVL": "3"}))
        self.assertNotEqual(self.fingerprint(), self.fingerprint(
            toolchain=cache.ToolchainFingerprint("b" * 64, self.data)))
        self.assertIsNone(self.fingerprint(toolchain=None))

    def test_candidate_inputs_are_distinct_and_no_probes_per_candidate(self):
        with patch.object(cache.subprocess, "run", side_effect=AssertionError("no probe")):
            for change in (dict(signed=-11), dict(spelled=("c", "cis")),
                           dict(original_dimensions=(101, 50)),
                           dict(original_boundaries=[1, 0, 101, 50]),
                           dict(extra={"mode": "minor"}), dict(implementation_version="v2")):
                self.assertNotEqual(self.key, self.candidate(**change))
        self.assertIsNone(self.candidate(original_dimensions=(float("nan"), 50)))
        self.assertIsNone(self.candidate(extra=object()))

    def test_toolchain_probes_fixed_commands_and_hashes_assets(self):
        binary = self.root / "lilypond"
        binary.write_bytes(b"executable bytes")
        def probe(args, **kwargs):
            self.assertNotIn("shell", kwargs)
            return SimpleNamespace(stdout="GNU LilyPond 2.26" if args[1] == "--version" else str(self.data))
        with patch.object(cache.shutil, "which", return_value=str(binary)), \
                patch.object(cache.subprocess, "run", side_effect=probe) as run:
            first = cache.toolchain_fingerprint(env=self.env, cwd=self.job)
            self.assertIsNotNone(first)
            self.assertEqual(run.call_count, 2)
            (self.data / "new-font").write_bytes(b"changed font")
            self.assertNotEqual(first, cache.toolchain_fingerprint(env=self.env, cwd=self.job))
        with patch.object(cache.subprocess, "run", side_effect=OSError("unavailable")):
            self.assertIsNone(cache.toolchain_fingerprint(env=self.env))

    def test_publish_restore_copy_metadata_and_clear_stale_systems(self):
        self.artifacts()
        self.assertTrue(self.publish())
        destination = self.root / "new-job/variant/t02"
        destination.parent.mkdir(parents=True)
        destination.with_name("t02-9.pdf").write_bytes(b"stale")
        result = cache.restore(self.key, destination, env=self.env)
        self.assertEqual(result["metadata"]["boundary_info"], [0, 1])
        self.assertEqual(result["validation"]["boundaries"], [[0, 0, 100, 50]])
        self.assertFalse(destination.with_name("t02-9.pdf").exists())
        pdf = destination.with_name("t02-1.pdf")
        self.assertEqual(pdf.read_bytes(), self.stem.with_name("t01-1.pdf").read_bytes())
        pdf.write_bytes(b"job edit")
        self.assertIsNotNone(cache.restore(self.key, destination, env=self.env))
        self.assertNotEqual(pdf.read_bytes(), b"job edit")

    def test_unsuccessful_or_invalid_artifacts_are_never_published(self):
        self.artifacts()
        self.assertFalse(self.publish(success=False))
        for options in (dict(log="fatal error: bad"), dict(log="No string for pitch"),
                        dict(pages=2), dict(size=(200, 50))):
            self.artifacts(**options)
            self.assertFalse(self.publish())
        self.artifacts()
        self.stem.with_name("t01-2.pdf").write_bytes(self.stem.with_name("t01-1.pdf").read_bytes())
        self.assertFalse(self.publish())
        self.assertFalse((self.root / "cache" / self.key).exists())

    def test_warm_success_reuses_while_failed_candidates_are_retried(self):
        failed_key = self.candidate(signed=-11)
        destination = self.root / "round/t01"
        attempts = {self.key: 0, failed_key: 0}
        def generate():
            hits = 0
            for key in attempts:
                if cache.restore(key, destination, env=self.env) is not None:
                    hits += 1
                    continue
                attempts[key] += 1
                self.artifacts(destination)
                cache.publish(key, destination, success=key == self.key,
                              original_dimensions=(100, 50), env=self.env)
            return hits
        self.assertEqual(generate(), 0)
        self.assertEqual(attempts, {self.key: 1, failed_key: 1})
        self.assertEqual(generate(), 1)
        self.assertEqual(attempts, {self.key: 1, failed_key: 2})

    def test_corrupt_entries_are_misses_without_touching_destination(self):
        self.artifacts()
        self.assertTrue(self.publish())
        entry = self.root / "cache" / self.key
        manifest = (entry / "manifest.json").read_bytes()
        pdf = (entry / "artifact-1.pdf").read_bytes()
        destination = self.root / "untouched/t01"
        for file, data in (("manifest.json", b"{}"), ("manifest.json", b"not json"),
                           ("artifact-1.pdf", b"not a pdf"), ("artifact.log", b"corrupt")):
            with self.subTest(file=file, data=data):
                (entry / file).write_bytes(data)
                self.assertIsNone(cache.restore(self.key, destination, env=self.env))
                self.assertFalse(destination.parent.exists())
                (entry / "manifest.json").write_bytes(manifest)
                (entry / "artifact-1.pdf").write_bytes(pdf)
                (entry / "artifact.log").write_text("warning: harmless\n")
        self.assertFalse(cache.publish("../unsafe", self.stem, success=True,
                                      original_dimensions=(100, 50), env=self.env))

    def test_manifest_path_traversal_and_symlinks_rejected(self):
        self.artifacts()
        self.assertTrue(self.publish())
        entry = self.root / "cache" / self.key
        path = entry / "manifest.json"
        envelope = json.loads(path.read_bytes())
        envelope["manifest"]["files"]["/../../escape"] = {"sha256": "a" * 64, "size": 1}
        envelope["sha256"] = cache._digest(cache._json(envelope["manifest"]))
        path.write_bytes(cache._json(envelope))
        self.assertIsNone(cache.restore(self.key, self.root / "new/t01", env=self.env))

    def test_symlink_artifacts_and_entries_are_misses(self):
        self.artifacts()
        self.assertTrue(self.publish())
        root = self.root / "cache"
        entry = root / self.key
        pdf = entry / "artifact-1.pdf"
        pdf.unlink()
        pdf.symlink_to(self.stem.with_name("t01-1.pdf"))
        self.assertIsNone(cache.restore(self.key, self.root / "new/t01", env=self.env))
        entry.rename(root / "elsewhere")
        entry.symlink_to(root / "elsewhere", target_is_directory=True)
        self.assertIsNone(cache.restore(self.key, self.root / "new/t01", env=self.env))

    def test_valid_hashes_do_not_bypass_pdf_or_boundary_validation(self):
        self.artifacts()
        self.assertTrue(self.publish())
        entry = self.root / "cache" / self.key
        path = entry / "manifest.json"
        original = json.loads(path.read_bytes())
        original["manifest"]["validation"]["boundaries"] = [[1, 2, 3, 4]]
        original["sha256"] = cache._digest(cache._json(original["manifest"]))
        path.write_bytes(cache._json(original))
        self.assertIsNone(cache.restore(self.key, self.root / "new/t01", env=self.env))
        # Even a consistently hashed broken PDF must not be accepted.
        broken = b"not a valid PDF"
        (entry / "artifact-1.pdf").write_bytes(broken)
        original["manifest"]["files"]["-1.pdf"] = {
            "sha256": cache._digest(broken), "size": len(broken)}
        original["sha256"] = cache._digest(cache._json(original["manifest"]))
        path.write_bytes(cache._json(original))
        self.assertIsNone(cache.restore(self.key, self.root / "new/t01", env=self.env))
        self.assertFalse(self.publish())

    def test_partial_entries_missing_logs_and_bad_bounds(self):
        self.artifacts()
        self.stem.with_suffix(".log").unlink()
        self.assertFalse(self.publish())
        self.artifacts()
        for bounds in ((0, 50), (100, float("inf")), (100,), (100, -1)):
            self.assertFalse(self.publish(original_dimensions=bounds))
        self.assertFalse(self.publish(minimum_scale=float("nan")))
        entry = self.root / "cache" / self.key
        entry.mkdir(parents=True)
        (entry / "artifact-1.pdf").write_bytes(self.stem.with_name("t01-1.pdf").read_bytes())
        self.assertIsNone(cache.restore(self.key, self.root / "new/t01", env=self.env))
        self.assertFalse(self.publish())

    def test_asset_tree_layout_and_missing_assets_change_fingerprint(self):
        tree = self.root / "fonts"
        tree.mkdir()
        (tree / "font.otf").write_bytes(b"font")
        first = cache._tree(tree)
        (tree / "font.otf").rename(tree / "renamed.otf")
        self.assertNotEqual(first, cache._tree(tree))
        (tree / "alias").symlink_to(tree, target_is_directory=True)
        with self.assertRaises(ValueError):
            cache._tree(tree)

    def test_asset_directory_symlinks_hash_targets_and_detect_cycles(self):
        fonts = self.root / "fonts"
        fonts.mkdir()
        external = self.root / "tex-fonts"
        external.mkdir()
        font = external / "font.otf"
        font.write_bytes(b"original font")
        (fonts / "type1").symlink_to(external, target_is_directory=True)
        (fonts / "alias").symlink_to(external, target_is_directory=True)
        first = cache._tree(fonts)
        font.write_bytes(b"changed font")
        self.assertNotEqual(first, cache._tree(fonts))
        (external / "cycle").symlink_to(fonts, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "cycle"):
            cache._tree(fonts)
        (external / "cycle").unlink()
        (external / "broken").symlink_to(external / "missing")
        with self.assertRaisesRegex(ValueError, "unreadable"):
            cache._tree(fonts)

    def test_multiple_system_pdfs_and_exact_boundary_sidecar(self):
        self.artifacts()
        self.stem.with_name("t01-2.pdf").write_bytes(self.stem.with_name("t01-1.pdf").read_bytes())
        sizes = ((100, 50), (100, 50))
        boundaries = ((Fraction(0), Fraction(0), Fraction(1, 2), Fraction(0)),
                      (Fraction(1, 2), Fraction(0), Fraction(1), Fraction(0)))
        self.key = self.candidate(original_dimensions=sizes, original_boundaries=boundaries)
        self.assertIsNotNone(self.key)
        self.assertFalse(self.publish(original_dimensions=sizes))
        sidecar = self.stem.with_suffix(".ulsbs-boundaries")
        sidecar.write_text("0 0 1/2 0\n1/2 0 1 0\n")
        self.assertTrue(self.publish(original_dimensions=sizes))
        destination = self.root / "multi/t02"
        result = cache.restore(self.key, destination, env=self.env)
        self.assertEqual(result["validation"]["pdfs"], ["-1.pdf", "-2.pdf"])
        self.assertEqual(destination.with_suffix(".ulsbs-boundaries").read_bytes(), sidecar.read_bytes())
        self.assertTrue(destination.with_name("t02-2.pdf").is_file())
        sidecar.write_text("0 0 1/2 0\n3/4 0 1 0\n")
        self.assertFalse(self.publish(original_dimensions=sizes))
        sidecar.write_text("0 0 1 0\n")
        self.assertFalse(self.publish(original_dimensions=sizes))

    def test_concurrent_publication_and_nonfatal_io(self):
        self.artifacts()
        with ThreadPoolExecutor(max_workers=6) as pool:
            self.assertTrue(all(pool.map(lambda _: self.publish(), range(12))))
        self.assertIsNotNone(cache.restore(self.key, self.root / "new/t03", env=self.env))
        self.assertEqual([p.name for p in (self.root / "cache").iterdir()], [self.key])
        blocked = self.root / "blocked"
        blocked.write_text("not a directory")
        env = {**self.env, "ULSBS_SCORE_CACHE_DIR": str(blocked)}
        self.assertFalse(self.publish(env=env))
        self.assertIsNone(cache.restore(self.key, self.stem, env=env))
        self.assertIsNone(cache.restore(None, self.stem, env=self.env))


class ScoreCacheCliTests(unittest.TestCase):
    def run_cli(self, *, flag=True, in_container=False, delegate=False, special=None, failure=None):
        from ulsbs import cli
        from ulsbs.config import Config

        ui = Mock()
        project = SimpleNamespace(config_file=Path("ulsbs-config.toml"),
                                  project_root=Path("/project"), temp_dir=Path("/project/temp"),
                                  result_dir=Path("/project/result"))
        cfg = replace(Config(), use_container=delegate, clean_temp=False, deploy=False,
                      shell=special == "shell", deploy_last=special == "deploy-last",
                      deploy_common=special == "deploy-common",
                      runtime=SimpleNamespace(in_container=in_container, project_paths=project,
                                              unique_id="test"))
        events = []
        outcome = SimpleNamespace(successes=[Mock()], failures=[], total_warnings=0)
        mocks = dict(build_config=Mock(return_value=cfg), setup_temp_dir=Mock(),
                     build_job_queue=Mock(return_value=[Mock()]), require_tools=Mock(),
                     ensure_dir=Mock(), print_plan_summary=Mock(), deploy_results=Mock(),
                     resultlist=Mock(), run_self_in_container=Mock(return_value=0),
                     run_jobs_parallel=Mock(side_effect=lambda **kwargs: events.append("jobs") or outcome))
        mocks["resultlist"].resultfiles_in_dir.return_value = []
        def clear():
            events.append("clear")
            if failure:
                raise failure
            return Path("/cache/lilypond-scores"), 2
        args = (["--clear-score-cache"] if flag else []) + (["--" + special] if special else [])
        with patch.multiple(cli, **mocks), \
                patch.object(cli.ProjectPaths, "from_docs", return_value=project), \
                patch.object(cli.os, "execvp"), \
                patch.object(cache, "clear_cache", side_effect=clear) as cleared:
            result = cli._run_cli(ui, Mock(), args)
        return result, events, cleared, mocks, ui

    def test_clear_score_cache_runs_once_before_jobs_on_host_and_in_container(self):
        for in_container in (False, True):
            with self.subTest(in_container=in_container):
                result, events, cleared, _, ui = self.run_cli(in_container=in_container)
                self.assertEqual(result, 0)
                self.assertEqual(events, ["clear", "jobs"])
                cleared.assert_called_once_with()
                self.assertTrue(any("score cache cleared: 2" in call.args[0]
                                    for call in ui.info_line.call_args_list))

    def test_clear_score_cache_is_opt_in_and_forwarded_not_run_on_container_host(self):
        result, events, cleared, _, _ = self.run_cli(flag=False)
        self.assertEqual(result, 0)
        self.assertEqual(events, ["jobs"])
        cleared.assert_not_called()
        result, events, cleared, mocks, _ = self.run_cli(delegate=True)
        self.assertEqual(result, 0)
        self.assertEqual(events, [])
        cleared.assert_not_called()
        self.assertIn("--clear-score-cache",
                      mocks["run_self_in_container"].call_args.kwargs["passthrough_args"])

    def test_special_modes_do_not_clear_cache(self):
        for special in ("shell", "deploy-last", "deploy-common"):
            with self.subTest(special=special):
                result, events, cleared, mocks, _ = self.run_cli(special=special)
                self.assertEqual(result, 127 if special == "shell" else 0)
                self.assertEqual(events, [])
                cleared.assert_not_called()
                mocks["run_jobs_parallel"].assert_not_called()

    def test_clear_failure_stops_compilation_before_jobs(self):
        result, events, cleared, mocks, ui = self.run_cli(failure=PermissionError("read-only cache"))
        self.assertEqual(result, 1)
        self.assertEqual(events, ["clear"])
        cleared.assert_called_once_with()
        mocks["run_jobs_parallel"].assert_not_called()
        self.assertIn("Failed to clear LilyPond score cache", ui.error_line.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
