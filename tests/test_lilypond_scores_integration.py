# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Real score overlays, original geometry, source freshness, and occurrences."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pikepdf

from test_multikey_metadata import layer_page_dependencies
from test_tex_integration import compile_fixture

from ulsbs import lilypond_scores, pipeline, resultlist
from ulsbs.config import Config
from ulsbs.engine_assets import EngineAssets
from ulsbs.jobs import Job, build_job_basename


def score_layer_drawings(pdf, *, generic=False):
    drawings = {}
    for page in pdf.pages:
        stack = []
        properties = page.Resources.get('/Properties', {})
        xobjects = page.Resources.get('/XObject', {})
        for operands, operator in pikepdf.parse_content_stream(page):
            op = str(operator)
            if op in ('BDC', 'BMC'):
                names = []
                if op == 'BDC' and str(operands[0]) == '/OC':
                    prop = properties[str(operands[1])]
                    groups = prop.get('/OCGs', [prop])
                    if not isinstance(groups, (list, pikepdf.Array)):
                        groups = [groups]
                    names = [str(group.get('/Name', '')) for group in groups]
                stack.append(names)
            elif op == 'EMC':
                if not stack:
                    raise AssertionError('unbalanced optional content')
                stack.pop()
            elif op == 'Do':
                graphic = xobjects[str(operands[0])]
                fonts = graphic.get('/Resources', {}).get('/Font', {})
                if generic or any('emmentaler' in str(font.get('/BaseFont', '')).lower()
                                  for _, font in fonts.items()):
                    digest = hashlib.sha256(graphic.read_bytes()).hexdigest()
                    for name in (name for level in stack for name in level):
                        if name.startswith('ulsbs:transpose:v1:'):
                            drawings.setdefault(name, set()).add(digest)
        if stack:
            raise AssertionError('unclosed optional content')
    return drawings


class LilyPondScoreIntegrationTests(unittest.TestCase):
    def test_generated_minimum_scale_controls_real_tex_graphic_fallback(self):
        if shutil.which('lualatex') is None:
            self.skipTest('lualatex is not installed')
        files = {}
        sizes = {'original': (60, 30), 'exact': (100, 30), 'larger': (80, 30),
                 'below': (101, 30), 'height-exact': (60, 50),
                 'height-below': (60, 51), 'height-larger': (60, 40)}
        alternatives = {1: 'exact', 2: 'larger', 3: 'below', 4: 'height-exact',
                        5: 'height-below', 6: 'height-larger'}
        for name, (width, height) in sizes.items():
            with pikepdf.Pdf.new() as graphic:
                page = graphic.add_blank_page(page_size=(width, height))
                page.Contents = pikepdf.Stream(
                    graphic, f'0.2 0.4 0.6 rg 0 0 {width} {height} re f\n'.encode())
                buffer = io.BytesIO()
                graphic.save(buffer)
                files[name + '-1.pdf'] = buffer.getvalue()
        prefix = 'ulsbs:transpose:v1:id:scale-policy'
        dispatch = ''.join(
            rf'\expandafter\def\csname ULScoreVariant:{prefix}:abcdef:0-0-0:t{offset:02d}\endcsname'
            + '{' + name + '}\n'
            for offset, name in alternatives.items()
        )
        for minimum in (0.60, 0.75):
            with self.subTest(minimum=minimum), patch.object(lilypond_scores, 'LILYPOND_SCORE_MIN_SCALE', minimum):
                files['score-minimum-scale.ulsbs-score-variants.tex'] = (
                    lilypond_scores._minimum_scale_tex() + dispatch).encode()
                output, contents = compile_fixture('score-minimum-scale', files=files, passes=3)
                scales = {int(offset): float(value) for offset, value in re.findall(
                    r'ULSBS-TEST-SCALE (\d+) = ([0-9.]+)', output)}
                for offset, name in alternatives.items():
                    width, height = sizes[name]
                    self.assertAlmostEqual(scales[offset], min(1, 60 / width, 30 / height), places=6)
                with pikepdf.open(io.BytesIO(contents)) as pdf:
                    # Generic vectors have no Emmentaler font. Inspect the actual
                    # Do operations inside OCGs, not page text or changing badges.
                    drawings = score_layer_drawings(pdf, generic=True)
                self.assertEqual(set(drawings), {f'{prefix}:t{offset:02d}' for offset in range(12)})
                self.assertTrue(all(len(hashes) == 1 for hashes in drawings.values()))
                original = drawings[prefix + ':t00']
                self.assertEqual(drawings[prefix + ':t03'], original)  # 60/101 < .60
                self.assertEqual(drawings[prefix + ':t05'], original)  # 30/51 < .60
                self.assertNotEqual(drawings[prefix + ':t02'], original)  # 60/80 = .75
                self.assertNotEqual(drawings[prefix + ':t06'], original)  # 30/40 = .75
                if minimum == 0.60:
                    self.assertNotEqual(drawings[prefix + ':t01'], original, scales)  # 60/100 = .60
                    self.assertNotEqual(drawings[prefix + ':t04'], original, scales)  # 30/50 = .60
                    self.assertNotEqual(drawings[prefix + ':t01'], drawings[prefix + ':t02'])
                else:
                    self.assertEqual(drawings[prefix + ':t01'], original)
                    self.assertEqual(drawings[prefix + ':t04'], original)
                self.assertIn('is too small', output)
                for offset in range(7, 12):
                    self.assertEqual(drawings[f'{prefix}:t{offset:02d}'], original)

    def test_nested_imports_warm_edits_dependencies_removals_and_original_failure(self):
        for tool in ('lilypond-book', 'lilypond', 'lualatex', 'pdftoppm'):
            if shutil.which(tool) is None:
                self.skipTest(f'{tool} is not installed')
        with tempfile.TemporaryDirectory(prefix='ulsbs-score-sources-') as temporary:
            root = Path(temporary)
            for child in ('content', 'include', 'job', 'texmf-cache'):
                (root / child).mkdir()
            doc = root / 'book.tex'
            original = (r'\documentclass{article}\usepackage{graphicx}\input{include/layout.tex}' + '\n'
                        r'\begin{document}\input{ulsbs/assets/tex/lookup-probe.tex}' + '\n'
                        r'\input{content/section.tex}' + '\n'
                        r'\input{content/section.tex}\end{document}' + '\n')
            doc.write_text(original, encoding='utf-8')
            section = root / 'content/section.tex'
            section.write_text(r'\input{content/music.tex}' + '\n'
                               r'\input{content/music}\relax' + '\n'
                               r'\lilypondfile{content/external.ly}' + '\n'
                               r'\lilypondfile{include/external.ly}' + '\n', encoding='utf-8')
            external = root / 'content/external.ly'
            external.write_text("\\score { \\new Staff { e'4 f' g' a' } \\layout {} }\n", encoding='utf-8')
            (root / 'include/external.ly').write_text(
                "\\score { \\new Staff { c'4 e' g' c'' } \\layout {} }\n", encoding='utf-8')
            music = root / 'content/music.tex'
            music.write_text('\\begin{lilypond}[]\n\\include "notes.ily"\n'
                             '\\include "ulsbs/src/ulsbs/assets/ly/lookup-probe.ily"\n'
                             '\\score { \\new Staff { \\melody } \\layout {} }\n'
                             '\\end{lilypond}\n', encoding='utf-8')
            dependency = root / 'include/notes.ily'
            dependency.write_text("melody = { c'4 d' e' f' }\n", encoding='utf-8')
            layout = root / 'include/layout.tex'
            layout.write_text(r'\setlength{\textwidth}{200pt}' + '\n', encoding='utf-8')
            paths = SimpleNamespace(project_root=root, host_project_root=root, result_dir=root / 'result',
                                    content_dir=root / 'content', include_dir=root / 'include')
            cfg = replace(Config(), runtime=SimpleNamespace(project_paths=paths, in_container=False))
            job = Job(doc, doc.stem, 'default', root / 'job')
            ui = Mock()
            pipeline.prepare_compile_dir(ui, EngineAssets(), cfg, job)
            (job.compile_dir / 'ulsbs-assets/tex/lookup-probe.tex').write_text('\\relax\n', encoding='utf-8')
            (job.compile_dir / 'ulsbs-assets/ly/lookup-probe.ily').write_text("probe = { c'4 }\n", encoding='utf-8')

            def build():
                sources = {p: p.read_bytes() for p in root.rglob('*')
                           if p.is_file() and not p.is_relative_to(job.compile_dir)
                           and not p.is_relative_to(root / 'texmf-cache')}
                input_tex = pipeline.make_variant_tex(job, cfg)
                env, includes, _ = pipeline.build_include_paths(cfg, job)
                env.update(TEXMFVAR=str(root / 'texmf-cache'), TEXMFCACHE=str(root / 'texmf-cache'))
                try:
                    processed, _, _ = pipeline.step_lilypond_book(ui, job, input_tex, env, includes, 1)
                except pipeline.CompileError as error:
                    raise pipeline.CompileError(f'{error}\n{error.log_path.read_text()}', error.log_path) from error
                self.assertEqual({p: p.read_bytes() for p in root.rglob('*')
                                  if p.is_file() and not p.is_relative_to(job.compile_dir)
                                  and not p.is_relative_to(root / 'texmf-cache')}, sources)
                self.assertTrue((job.compile_dir / 'ulsbs/assets/tex/lookup-probe.tex').is_file())
                # Resolve every generated reference, including external scores,
                # before wrapping the graphics for orchestration-only checks.
                if r'\input{content/section.tex}' in doc.read_text():
                    pipeline.step_lualatex_pass(ui, cfg, job, processed.stem, env, 2, 1, False)
                prepared = lilypond_scores.prepare_scores(job.compile_dir, processed.stem)
                if not prepared:
                    return None
                self.assertEqual(len(prepared), 3)
                self.assertEqual((job.compile_dir / 'content/section.tex').read_text().count(r'\input{content/music'), 2)
                self.assertEqual((job.compile_dir / 'content/music.tex').read_text().count(r'\includegraphics'), 0)
                rasters = {}
                for score in prepared.values():
                    fragment = score.source.with_name(score.source.stem + '-systems.tex')
                    self.assertEqual(fragment.read_text().count(r'\ulScoreSystem'), 1)
                    graphic = job.compile_dir / (score.graphics[0] + '.pdf')
                    source = score.source.read_text()
                    role = ('external' if 'content/external.ly' in source else
                            'other' if 'include/external.ly' in source else 'inline')
                    rasters[role] = subprocess.check_output([
                        'pdftoppm', '-r', '96', '-singlefile', '-png', str(graphic)])
                    if role == 'inline':
                        width = re.search(r'line-width\s*=\s*[^\n]+', source)
                        self.assertIsNotNone(width)
                return rasters, width[0]

            cold = build()
            self.assertIsNotNone(cold)
            self.assertEqual(set(cold[0]), {'inline', 'external', 'other'})
            self.assertNotEqual(cold[0]['external'], cold[0]['other'])
            root.chmod(0o555)
            try:
                self.assertEqual(build(), cold)
            finally:
                root.chmod(0o755)
            layout.write_text(r'\setlength{\textwidth}{300pt}' + '\n', encoding='utf-8')
            changed_layout = build()
            self.assertNotEqual(changed_layout[1], cold[1])
            dependency.write_text("melody = { g'4 a' b' c'' }\n", encoding='utf-8')
            changed_dependency = build()
            self.assertNotEqual(changed_dependency[0]['inline'], changed_layout[0]['inline'])
            music.write_text(music.read_text().replace(r'\melody', r'\transpose c d \melody'), encoding='utf-8')
            changed_inline = build()
            self.assertNotEqual(changed_inline[0]['inline'], changed_dependency[0]['inline'])
            external.write_text("\\score { \\new Staff { c''4 d'' e'' f'' } \\layout {} }\n", encoding='utf-8')
            changed_external = build()
            self.assertNotEqual(changed_external[0]['external'], changed_inline[0]['external'])
            self.assertEqual(changed_external[0]['inline'], changed_inline[0]['inline'])
            self.assertEqual(changed_external[0]['other'], changed_inline[0]['other'])
            self.assertEqual(doc.read_text(), original)
            dependency.unlink()
            with self.assertRaisesRegex(pipeline.CompileError, 'lilypond-book failed'):
                build()
            doc.write_text(r'\documentclass{article}\begin{document}No scores.\end{document}' + '\n',
                           encoding='utf-8')
            self.assertIsNone(build())
            self.assertTrue(list(job.compile_dir.rglob('*-systems.tex')))

    def test_opt_in_pipeline_preserves_default_and_switches_score_graphics(self):
        for tool in ('lilypond-book', 'lilypond', 'lualatex', 'pdftoppm'):
            if shutil.which(tool) is None:
                self.skipTest(f'{tool} is not installed')
        with tempfile.TemporaryDirectory(prefix='ulsbs-score-integration-') as temporary:
            root = Path(temporary)
            for child in ('content', 'include', 'result', 'texmf-cache'):
                (root / child).mkdir()
            doc = root / 'ul-selection_score_A5.tex'
            doc.write_text(
                r'\documentclass[maintitle={Score Milestone}]{ulsbs-songbook}' + '\n'
                r'\begin{document}\begin{songs}{}' + '\n'
                r'\input{content/song.tex}' + '\n'
                r'\input{content/song.tex}' + '\n'
                r'\input{content/custom.tex}' + '\n'
                r'\input{content/long.tex}' + '\n'
                r'\end{songs}\end{document}' + '\n',
                encoding='utf-8',
            )
            song = (
                r'\beginsong{Score Song}[id={score-song},key={C}]' + '\n'
                r'\beginverse\[C/E]Surrounding lyrics.\endverse' + '\n'
                r'\begin{lilywrap}\begin{lilypond}[]' + '\n'
                r'\include "ulsbs-include-head.ly"' + '\n'
                r'theMelody = \transpose d c \relative d\prime {'
                r' \key d \major \time 4/4 fis4 g a fis }'.replace(r'd\prime', "d'") + '\n'
                r'theChords = \transpose d c \chordmode { d1/fis }' + '\n'
                r'\include "ulsbs-include-tail.ly"' + '\n'
                r'\end{lilypond}\end{lilywrap}\endsong' + '\n'
            )
            (root / 'content/song.tex').write_text(song, encoding='utf-8')
            (root / 'content/custom.tex').write_text(
                r'\beginsong{Custom Score}[id={custom-score},key={C}]' + '\n'
                r'\beginverse\[C]Original-only fallback.\endverse' + '\n'
                r'\begin{lilywrap}\begin{lilypond}[]' + '\n'
                r'\include "ulsbs-include-head.ly"' + '\n'
                r'\score { \new Staff { \key c \major c\prime4 d\prime e\prime c\prime } \layout {} }'.replace(r'\prime', "'")
                + '\n' + r'\end{lilypond}\end{lilywrap}\endsong' + '\n', encoding='utf-8',
            )
            # Twelve independently breakable systems force a score across pages.
            # The pickup, initial grace and internal grace notes exercise exact
            # musical timing, not bar counts or main-time-only boundary checks.
            (root / 'content/long.tex').write_text(
                r'\beginsong{Long Score}[id={long-score},key={Am}]' + '\n'
                r'\beginverse\[Am]Before the long score.\endverse' + '\n'
                r'\begin{lilywrap}\begin{lilypond}[]' + '\n'
                r'\include "ulsbs-include-head.ly"' + '\n'
                r'theMelody = { \key a \minor \time 4/4 \partial 4 '
                r'\grace { g\prime8 } e\prime4 '.replace(r'\prime', "'")
                + (r'\grace { g\prime8 } a\prime4 \grace { f\prime16 g\prime } b\prime c\prime\prime d\prime\prime | '
                   r'e\prime\prime4 d\prime\prime c\prime\prime b\prime | \break '.replace(r'\prime', "'")) * 11
                + r'a\prime1 | }'.replace(r'\prime', "'") + '\n'
                r'theChords = \chordmode { \partial 4 a4:m ' + 'a1:m e:7 ' * 11 + 'a1:m }\n'
                r'\include "ulsbs-include-tail.ly"' + '\n'
                r'\end{lilypond}\end{lilywrap}' + '\n'
                r'\beginverse\[Am]After the long score.\endverse\endsong' + '\n', encoding='utf-8')
            paths = SimpleNamespace(project_root=root, host_project_root=root, result_dir=root / 'result',
                                    content_dir=root / 'content', include_dir=root / 'include')
            cfg = replace(Config(), runtime=SimpleNamespace(project_paths=paths, in_container=False),
                          multikey_books=True, create_printouts=False, coverimage=False, audiofiles=False,
                          midifiles=False, json=False, clean_temp=False)
            ui = Mock()
            ui.fmt_doc.return_value = '[score integration]'
            ui.colorize.side_effect = lambda text, color: text
            prepare = pipeline.prepare_compile_dir
            engrave = lilypond_scores.run_cmd

            def engrave_fixture(command, **kwargs):
                source = Path(command[-1])
                text = source.read_text()
                position = text.index('\\include "ulsbs-include-tail.ly"')
                dump = '''#(music-map (lambda (music)
  (let ((pitch (ly:music-property music 'pitch)))
    (when (ly:pitch? pitch)
      (ly:message "ULSBS-TEST-PITCH ~a" (+ 60 (ly:pitch-semitones pitch)))))
  music) theMelody)
'''
                source.write_text(text[:position] + dump + text[position:])
                return engrave(command, **kwargs)

            def prepare_fixture(*args, **kwargs):
                prepare(*args, **kwargs)
                job = kwargs.get('job') or args[3]
                tail = job.compile_dir / 'ulsbs-assets/ly/ulsbs-internal-common-tail.ly'
                # This is a fixture-only compatibility conversion. Production
                # 2.24 uses the assets unchanged; host 2.26 removed set-global-fonts.
                version = subprocess.check_output(['lilypond', '--version'], text=True)
                if '2.24.' not in version:
                    subprocess.run(['convert-ly', '-e', '-f', '2.24.4', str(tail)], check=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

            pdfs = []
            cold_engraving_count = None
            resultlist.initialize(root / 'result', 'score-integration')
            try:
                ordinary_job = None
                for enabled, build in ((False, 'cold'), (True, 'cold'), (True, 'warm')):
                    # A fresh warm job proves that copying sources and deleting
                    # compilation output does not prevent persistent cache hits.
                    job = Job(doc, doc.stem, 'default', root / f'job-{enabled}-{build}', multikey=True)
                    job.compile_dir.mkdir(exist_ok=True)
                    with patch.dict(os.environ, {'TEXMFVAR': str(root / 'texmf-cache'),
                                                 'TEXMFCACHE': str(root / 'texmf-cache'),
                                                 'ULSBS_SCORE_CACHE_DIR': str(root / 'score-cache')}), \
                            patch.object(pipeline, 'prepare_compile_dir', side_effect=prepare_fixture), \
                            patch.object(lilypond_scores, 'run_cmd', side_effect=engrave_fixture):
                        try:
                            if ordinary_job is None:
                                # Packaging needs the matching ordinary edition;
                                # reuse it across disabled, cold, and warm runs.
                                ordinary_job = Job(doc, doc.stem, 'default', root / 'job-ordinary')
                                ordinary_job.compile_dir.mkdir()
                                pipeline.compile_one_job(ui, EngineAssets(), cfg, ordinary_job)
                            job_cfg = replace(cfg, multikey_lilypond_scores=enabled)
                            compilation = pipeline.compile_one_job(ui, EngineAssets(), job_cfg, job)
                            pipeline.finish_multikey_job(ui, job_cfg, job, ordinary_job, compilation)
                        except (pipeline.CompileError, SystemExit) as error:
                            logs = '\n'.join(str(p) + '\n' + p.read_text(errors='replace')[-5000:]
                                             for p in job.compile_dir.glob('*.log'))
                            self.fail(f'{error}\n{logs}')
                    basename = build_job_basename(job)
                    self.assertEqual({p.name for p in root.iterdir() if p.is_file() and p.suffix != '.pdf'},
                                     {doc.name})
                    snapshot = root / f'{enabled}-{build}.pdf'
                    shutil.copy2(job.compile_dir / (basename + '.pdf'), snapshot)
                    manifest = json.loads((job.compile_dir / (basename + '.ulsbs-multikey.json')).read_text())
                    self.assertEqual(manifest['multikey_info']['schema_version'], 2)
                    with pikepdf.open(snapshot) as pdf:
                        self.assertEqual(layer_page_dependencies(pdf), {
                            song['layer_prefix']: song['layer_page_indices']
                            for song in manifest['multikey_info']['songs']
                        })
                    pdfs.append(snapshot)
                    processed_song = (job.compile_dir / 'content/song.tex').read_text()
                    self.assertEqual(processed_song.count(r'\beginsong'), 1)
                    for fragment in job.compile_dir.rglob('*-systems.tex'):
                        if 'ulsbs-score-variants' not in fragment.parts:
                            text = fragment.read_text()
                            count = text.count(r'\includegraphics{') + text.count(r'\ulScoreSystem{')
                            self.assertIn(count, (1, 12), f'{build}: {fragment}\n{text}')
                    self.assertEqual(list(job.compile_dir.rglob('*.midi')), [])
                    if enabled:
                        self.assertTrue((job.compile_dir / (basename + '.ulsbs-score-variants.tex'))
                                        .read_text().startswith(lilypond_scores._minimum_scale_tex()))
                        report = json.loads((job.compile_dir / (basename + '.ulsbs-score-results.json')).read_text())
                        self.assertEqual(len(report['scores']), 4)
                        first = report['scores'][0]['offsets'][0]
                        diagnostics = [first]
                        if first['attempts']:
                            diagnostics.append((job.compile_dir / first['attempts'][0]['log']).read_text()[-4000:])
                        else:
                            source = job.compile_dir / report['scores'][0]['source']
                            diagnostics.append(source.with_name(source.stem + '-systems.tex').read_text())
                        self.assertEqual(report['successful_offsets'], 33, report)
                        self.assertEqual(report['fallback_offsets'], 11)
                        if build == 'warm':
                            self.assertEqual(report['cache_hits'], 22)
                            self.assertLess(report['engravings'], cold_engraving_count)
                        else:
                            cold_engraving_count = report['engravings']
                            self.assertEqual(report['cache_hits'], 0)
                        self.assertEqual(report['scores'][0]['offsets'][6]['attempts'][0]['interval'], -5)
                        self.assertEqual(report['scores'][0]['offsets'][6]['attempts'][1]['interval'], 7)
                        for outcome in report['scores'][0]['offsets']:
                            for attempt in outcome['attempts']:
                                pitches = [int(value) for value in re.findall(
                                    r'ULSBS-TEST-PITCH (\d+)',
                                    (job.compile_dir / attempt['log']).read_text())]
                                self.assertEqual(pitches, [pitch + attempt['interval']
                                                            for pitch in (64, 65, 67, 64)])
                        long = report['scores'][3]
                        original = lilypond_scores._boundaries(
                            (job.compile_dir / long['source']).with_suffix('.ulsbs-boundaries'))
                        self.assertEqual(len(original), 12)
                        self.assertEqual(str(original[0][1]), '-1/8')
                        self.assertTrue(any(row[3] for row in original[:-1]),
                                        'fixture must exercise internal grace-time breaks')
                        for outcome in long['offsets']:
                            self.assertEqual(outcome['status'], 'transposed', outcome)
                            self.assertEqual(lilypond_scores._boundaries(
                                job.compile_dir / (outcome['graphic'] + '.ulsbs-boundaries')), original)
                    else:
                        self.assertFalse((job.compile_dir / (basename + '.ulsbs-scores.json')).exists())
            finally:
                resultlist.delete()

            with pikepdf.open(pdfs[0]) as before, pikepdf.open(pdfs[1]) as after:
                self.assertEqual(len(before.pages), len(after.pages))
                self.assertGreater(len(after.pages), 1)
                self.assertEqual(len(after.Root.OCProperties.OCGs), 48)
                configuration = after.Root.OCProperties.D
                on = {group.objgen for group in configuration.get('/ON', [])}
                off = {group.objgen for group in configuration.get('/OFF', [])}
                base_on = str(configuration.get('/BaseState', '/ON')) == '/ON'
                visible = [group for group in after.Root.OCProperties.OCGs
                           if group.objgen in on or base_on and group.objgen not in off]
                self.assertEqual(len(visible), 4)
                self.assertTrue(all(str(group.Name).endswith(':t00') for group in visible))
                for group in after.Root.OCProperties.OCGs:
                    self.assertEqual(str(group.Usage.Print.PrintState),
                                     '/ON' if str(group.Name).endswith(':t00') else '/OFF')
                drawings = score_layer_drawings(after)
                with pikepdf.open(pdfs[2]) as warm:
                    self.assertEqual(len(warm.pages), len(after.pages))
                    self.assertEqual(score_layer_drawings(warm), drawings)
                prefix = 'ulsbs:transpose:v1:id:score-song'
                self.assertNotEqual(drawings[prefix + ':t00'], drawings[prefix + ':t01'])
                self.assertEqual(drawings[prefix + ':t01'], drawings[prefix + ':o02:t01'])
                long = 'ulsbs:transpose:v1:id:long-score'
                self.assertNotEqual(drawings[long + ':t00'], drawings[long + ':t01'])
                score_pages = []
                for index, page in enumerate(after.pages):
                    if long + ':t00' in score_layer_drawings(SimpleNamespace(pages=[page])):
                        score_pages.append(index)
                self.assertGreater(len(score_pages), 1, 'long score must cross a page boundary')
                fallback = 'ulsbs:transpose:v1:id:custom-score'
                for offset in range(12):
                    self.assertEqual(drawings[fallback + ':t00'], drawings[f'{fallback}:t{offset:02d}'])
                for page in range(1, len(after.pages) + 1):
                    command = ['pdftoppm', '-r', '96', '-f', str(page), '-singlefile', '-png']
                    self.assertEqual(subprocess.check_output(command + [str(pdfs[0])]),
                                     subprocess.check_output(command + [str(pdfs[1])]))
                    self.assertEqual(subprocess.check_output(command + [str(pdfs[1])]),
                                      subprocess.check_output(command + [str(pdfs[2])]))
            selections = []
            for offset in range(12):
                selected = root / f'selected-{offset:02d}.pdf'
                with pikepdf.open(pdfs[1]) as pdf:
                    groups = pdf.Root.OCProperties.OCGs
                    configuration = pdf.Root.OCProperties.D
                    configuration.BaseState = pikepdf.Name.OFF
                    configuration.ON = pikepdf.Array([
                        group for group in groups if str(group.Name).endswith(f':t{offset:02d}')])
                    configuration.OFF = pikepdf.Array([
                        group for group in groups if not str(group.Name).endswith(f':t{offset:02d}')])
                    pdf.save(selected)
                rendered = subprocess.run(
                    ['pdftoppm', '-r', '72', '-singlefile', '-png', str(selected)],
                    check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertNotIn(b'Syntax Error', rendered.stderr)
                selections.append(hashlib.sha256(rendered.stdout).hexdigest())
            self.assertEqual(len(set(selections)), 12, 'all twelve selections must render distinctly')
