# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Real draft passes omit alternate ink, never requests or layout-bearing boxes."""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import Mock

import pikepdf

from test_lilypond_scores_integration import score_layer_drawings
from test_multikey_metadata import layer_page_dependencies
from test_pdf_transposition_layers import PdfStructure, rendered_pages, words_and_geometry
from test_tex_integration import TEX_ASSETS
from ulsbs import pipeline
from ulsbs.config import Config
from ulsbs.jobs import Job
from ulsbs.lilypond_scores import _minimum_scale_tex


INSTRUMENTATION = r"""
\makeatletter
\typeout{DRAFT-AUTO:\ifUL@pdfdraftpass true\else false\fi}
% The overrides are test-only: never publish the forced skeleton full PDF.
OVERRIDE
\ExplSyntaxOn
\int_new:N \g_draft_native_int
\int_new:N \g_draft_spell_int
\int_new:N \g_draft_score_int
\int_new:N \g_draft_scorealt_int
\int_new:N \g_draft_original_int
\box_new:N \l_draft_probe_box
\cs_new_eq:NN \draft_native:nnn \UL@pdfvisual
\cs_set_protected:Npn \UL@pdfvisual #1#2#3
  {
    \int_gincr:N \g_draft_native_int
    \group_begin:
    \hbox_set:Nn \l_draft_probe_box {\draft_native:nnn {#1}{#2}{#3}}
    \iow_term:x {DRAFT-BOX:N\int_use:N\g_draft_native_int \c_colon_str
      \dim_to_decimal_in_sp:n {\box_wd:N\l_draft_probe_box},
      \dim_to_decimal_in_sp:n {\box_ht:N\l_draft_probe_box},
      \dim_to_decimal_in_sp:n {\box_dp:N\l_draft_probe_box}}
    \box_use:N \l_draft_probe_box
    \group_end:
  }
\cs_new_eq:NN \draft_spell:n \UL@pdfspellprepare
\cs_set_protected:Npn \UL@pdfspellprepare #1
  {\int_gincr:N \g_draft_spell_int \draft_spell:n {#1}}
\cs_new_eq:NN \draft_score:nnn \UL_score_system:nnn
\cs_set_protected:Npn \UL_score_system:nnn #1#2#3
  {
    \int_gincr:N \g_draft_score_int
    \group_begin:
    \hbox_set:Nn \l_draft_probe_box {\draft_score:nnn {#1}{#2}{#3}}
    \iow_term:x {DRAFT-BOX:S\int_use:N\g_draft_score_int \c_colon_str
      \dim_to_decimal_in_sp:n {\box_wd:N\l_draft_probe_box},
      \dim_to_decimal_in_sp:n {\box_ht:N\l_draft_probe_box},
      \dim_to_decimal_in_sp:n {\box_dp:N\l_draft_probe_box}}
    \leavevmode\box_use:N \l_draft_probe_box
    \group_end:
  }
\cs_new_eq:NN \draft_scorealt:nnn \UL_score_alternative:nnn
\cs_set_protected:Npn \UL_score_alternative:nnn #1#2#3
  {\int_gincr:N \g_draft_scorealt_int \draft_scorealt:nnn {#1}{#2}{#3}}
\cs_new_eq:NN \draft_mark:nn \UL_pdf_mark:nn
\cs_set_protected:Npn \UL_pdf_mark:nn #1#2
  {\int_compare:nNnT {#1}={0}{\int_gincr:N \g_draft_original_int}
   \draft_mark:nn {#1}{#2}}
\AddToHook{enddocument/afterlastpage}{
  \iow_term:x {DRAFT-COUNT:native=\int_use:N\g_draft_native_int}
  \iow_term:x {DRAFT-COUNT:spell=\int_use:N\g_draft_spell_int}
  \iow_term:x {DRAFT-COUNT:score=\int_use:N\g_draft_score_int}
  \iow_term:x {DRAFT-COUNT:scorealt=\int_use:N\g_draft_scorealt_int}
  \iow_term:x {DRAFT-COUNT:original=\int_use:N\g_draft_original_int}
  \iow_term:x {DRAFT-COUNT:families=\prop_count:N\g_UL_pdf_allocated_layers_prop}
  \iow_term:x {DRAFT-COUNT:pages=\int_eval:n{\ReadonlyShipoutCounter}}
}
\ExplSyntaxOff
\makeatother
"""

SCORES = r"""
\ulScoreSystem{aaaaaa}{1}{score-a-1}\par
\ulScoreSystem{aaaaaa}{2}{score-a-2}\par
\ulScoreSystem{bbbbbb}{1}{score-b-1}\par
\ulScoreSystem{bbbbbb}{2}{score-b-2}
"""

BOOK = r"""
\def\ulPdfTranspositionLayers{LAYERS}
\def\ulMultikeyLilypondScores{true}
\documentclass[paper={a5paper},maintitle={Synthetic Draft Regression}]{ulsbs-songbook}
INSTRUMENTATION
\newindex{drafttitle}{draft-title}
\begin{document}
\songcolumns{1}
\begin{songs}{drafttitle}
\beginsong{A Deliberately Long Synthetic Header With Enough Words To Wrap Across Lines}
  [id={draft-repeat},key={C},by={Synthetic Author}]
\beginverse
\hypertarget{draft-first}{}\label{draft:first}
\[C/E]Opening anchor \[F#m7/C#]with longer lyric phrases.
\[<C D;E F>Am]Melody anchor \[G7]and a final cadence.
SCORES
\endverse
\endsong
\beginsong{Shared Page Neighbor}[id={draft-neighbor},key={Am}]
\beginverse
\hypertarget{draft-neighbor}{}\label{draft:neighbor}
\[Am]Neighbor anchor \[E7]shares the physical page.
\endverse
\endsong
\end{songs}
\clearpage
\begin{songs}{drafttitle}
\beginsong{Repeated Source In A Different Key}[id={draft-repeat},key={G}]
\beginverse
\hypertarget{draft-repeat}{}\label{draft:repeat}
\[G/B]Repeated anchor \[D7]keeps independent controls.
SCORES
\endverse
\endsong
\end{songs}
\hyperlink{draft-first}{Return to opening}; page \pageref{draft:first}.
\end{document}
"""


def vector_score(system: int, variant: int) -> bytes:
    """Small real vector systems with distinct alternate ink and fixed dimensions."""
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(150, 18 + system))
        staff = " ".join(f"0 {y} m 150 {y} l S" for y in (3, 6, 9, 12, 15))
        notes = " ".join(
            f"{x} {4 + (variant + system + x) % 9} {3 + variant / 20} 2 re f"
            for x in (12, 40, 68, 96, 124)
        )
        page.Contents = pikepdf.Stream(pdf, f"0.3 w {staff} {notes}\n".encode())
        buffer = io.BytesIO()
        pdf.save(buffer)
        return buffer.getvalue()


def navigation(pdf_bytes: bytes) -> tuple:
    """Compare named targets and link actions without unstable PDF object numbers."""
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        pages = {page.obj.objgen: index for index, page in enumerate(pdf.pages)}

        def normalized(value):
            if isinstance(value, pikepdf.Object) and value.objgen in pages:
                return ("page", pages[value.objgen])
            if isinstance(value, pikepdf.Dictionary):
                if value.get('/Type') == '/OCG':
                    return ("layer", str(value.Name))
                return tuple(sorted((str(key), normalized(item)) for key, item in value.items()))
            if isinstance(value, (pikepdf.Array, list)):
                return tuple(normalized(item) for item in value)
            return str(value)

        def names(tree):
            pairs = list(tree.get('/Names', []))
            result = [(str(pairs[i]), normalized(pairs[i + 1])) for i in range(0, len(pairs), 2)]
            for kid in tree.get('/Kids', []):
                result.extend(names(kid))
            return result

        targets = names(pdf.Root.get('/Names', {}).get('/Dests', {}))
        links = [
            (index, normalized(annotation.get('/Rect')), normalized(annotation.get('/A')),
             normalized(annotation.get('/Dest')))
            for index, page in enumerate(pdf.pages)
            for annotation in page.get('/Annots', [])
            if annotation.get('/Subtype') == '/Link'
        ]
        return sorted(targets), links


class MultikeyDraftIntegrationTests(unittest.TestCase):
    """Keep one-draft/two-full layout and requests invariant while omitting ink."""

    @classmethod
    def setUpClass(cls) -> None:
        missing = [tool for tool in ('lualatex', 'qpdf', 'pdftotext', 'pdftoppm')
                   if shutil.which(tool) is None]
        if missing:
            raise unittest.SkipTest('PDF integration tools unavailable: ' + ', '.join(missing))
        cls.results = {}
        for mode, override in (
            ('reference', r'\UL@pdfdraftpassfalse'),
            ('automatic', ''),
            ('skeleton', r'\UL@pdfdraftpasstrue'),
        ):
            # Give every comparison the production one-draft/two-full history;
            # otherwise fresh auxiliary references can obscure layout evidence.
            cls.results[mode] = cls.compile_book(override)

    @classmethod
    def compile_book(cls, override: str) -> dict:
        """Run the production pass sequence with an optional test-only visual override."""
        with tempfile.TemporaryDirectory(prefix='ulsbs-test-draft-') as temporary:
            root = Path(temporary)
            cache = root / 'texmf-cache'
            cache.mkdir()
            source = root / 'draft.tex'
            instrumentation = INSTRUMENTATION.replace('OVERRIDE', override)
            source.write_text(BOOK.replace('INSTRUMENTATION', instrumentation)
                              .replace('SCORES', SCORES)
                              .replace('LAYERS', 'true'))
            bindings = [_minimum_scale_tex().rstrip()]
            for snippet, stem in (('aaaaaa', 'score-a'), ('bbbbbb', 'score-b')):
                for system in (1, 2):
                    (root / f'{stem}-{system}.pdf').write_bytes(vector_score(system, 0))
                for offset in range(1, 12):
                    for system in (1, 2):
                        (root / f'{stem}-t{offset:02d}-{system}.pdf').write_bytes(
                            vector_score(system, offset))
                    for prefix, signature in (
                        ('ulsbs:transpose:v1:id:draft-repeat', '0-0-0'),
                        ('ulsbs:transpose:v1:id:draft-repeat:o02', '4-7-0'),
                    ):
                        bindings.append(
                            rf'\expandafter\def\csname ULScoreVariant:{prefix}:{snippet}:'
                            rf'{signature}:t{offset:02d}\endcsname{{{stem}-t{offset:02d}}}'
                        )
            (root / 'draft.ulsbs-score-variants.tex').write_text('\n'.join(bindings))
            env = os.environ.copy()
            env.update(TEXINPUTS=f'{TEX_ASSETS}//{os.pathsep}' + env.get('TEXINPUTS', ''),
                       TEXMFVAR=str(cache), TEXMFCACHE=str(cache))
            job = Job(source, source.stem, 'default', root)
            result = {}
            step = 1
            # Separate real draft invocations from full passes: no helper that
            # requires a PDF is used, and a stale PDF cannot mask draft behavior.
            for phase, count in (('draft', 1), ('full', 2)):
                for number in range(1, count + 1):
                    try:
                        log, step = pipeline.step_lualatex_pass(
                            Mock(), Config(), job, source.stem, env, step, number, phase == 'draft')
                    except pipeline.CompileError as error:
                        raise AssertionError(error.log_path.read_text()) from error
                    # OCG object reservation may leave a zero-byte output stub
                    # in LuaTeX; draft mode must not produce an actual PDF.
                    pdf = root / 'draft.pdf'
                    if phase == 'draft' and pdf.exists() and pdf.stat().st_size:
                        raise AssertionError('Actual -draftmode unexpectedly wrote PDF content')
                output = log.read_text()
                artifacts = {
                    'counts': {key: int(value) for key, value in
                               re.findall(r'DRAFT-COUNT:(\w+)=(\d+)', output)},
                    'boxes': re.findall(r'DRAFT-BOX:([NS]\d+):\s*(-?\d+),(-?\d+),(-?\d+)', output),
                    'auto': re.findall(r'DRAFT-AUTO:(true|false)', output),
                    'aux': re.findall(r'\\newlabel[^\n]+', (root / 'draft.aux').read_text()),
                    'index': (root / 'draft-title.sxd').read_text(),
                    'requests': json.loads((root / 'draft.ulsbs-scores.json').read_text()),
                    'manifest': json.loads((root / 'draft.ulsbs-multikey.json').read_text()),
                }
                result[phase] = artifacts
            result['pdf'] = (root / 'draft.pdf').read_bytes()
            return result

    def test_actual_drafts_keep_requests_references_and_physical_pages(self):
        reference = self.results['reference']['draft']
        automatic = self.results['automatic']['draft']
        self.assertEqual(automatic['auto'], ['true'])
        for field in ('requests', 'aux', 'index', 'manifest', 'boxes'):
            self.assertTrue(reference[field], field)
            self.assertEqual(reference[field], automatic[field], field)
        self.assertEqual(reference['counts']['pages'], automatic['counts']['pages'])
        self.assertGreaterEqual(automatic['counts']['pages'], 2)
        for label in ('draft:first', 'draft:neighbor', 'draft:repeat'):
            self.assertTrue(any(label in entry for entry in automatic['aux']), label)
        self.assertIn('Shared Page Neighbor', automatic['index'])
        self.assertIn('Repeated Source In A Different Key', automatic['index'])
        self.assertEqual(len(automatic['requests']['requests']), 4)
        self.assertEqual(
            {(request['layer_prefix'], request['snippet_id'])
             for request in automatic['requests']['requests']},
            {(prefix, snippet) for prefix in (
                'ulsbs:transpose:v1:id:draft-repeat',
                'ulsbs:transpose:v1:id:draft-repeat:o02',
            ) for snippet in ('aaaaaa', 'bbbbbb')},
        )
        for request in automatic['requests']['requests']:
            self.assertEqual(len(request['targets']), 12)
            self.assertEqual([target['pitch'] for target in request['targets']],
                             [(request['key']['pitch'] + offset) % 12 for offset in range(12)])
            self.assertTrue(all(0 <= target['letter'] <= 6 for target in request['targets']))

    def test_only_alternate_rendering_is_skipped_in_actual_draft(self):
        reference = self.results['reference']['draft']['counts']
        automatic = self.results['automatic']['draft']['counts']
        self.assertGreater(reference['native'], 10)
        self.assertEqual(reference['score'], 8)
        self.assertEqual(reference['spell'], 11 * reference['native'])
        self.assertEqual(reference['scorealt'], 11 * reference['score'])
        self.assertEqual(automatic['spell'], 0)
        self.assertEqual(automatic['scorealt'], 0)
        for counts in (reference, automatic):
            self.assertEqual(counts['original'], counts['native'] + counts['score'])
            self.assertEqual(counts['families'], 3)
        for key in ('native', 'score', 'original', 'families'):
            self.assertEqual(reference[key], automatic[key], key)

    def test_actual_draft_without_layers_does_not_enable_fast_path(self):
        with tempfile.TemporaryDirectory(prefix='ulsbs-test-draft-disabled-') as temporary:
            root = Path(temporary)
            source = root / 'disabled.tex'
            source.write_text(
                r'\def\ulPdfTranspositionLayers{false}' '\n'
                r'\documentclass{ulsbs-songbook}' '\n'
                r'\makeatletter\typeout{DRAFT-AUTO:\ifUL@pdfdraftpass true\else false\fi}'
                r'\makeatother\begin{document}Synthetic text.\end{document}' '\n'
            )
            env = os.environ.copy()
            env['TEXINPUTS'] = f'{TEX_ASSETS}//{os.pathsep}' + env.get('TEXINPUTS', '')
            cache = root / 'texmf-cache'
            cache.mkdir()
            env.update(TEXMFVAR=str(cache), TEXMFCACHE=str(cache))
            try:
                log, _ = pipeline.step_lualatex_pass(
                    Mock(), Config(), Job(source, source.stem, 'default', root),
                    source.stem, env, 1, 1, True)
            except pipeline.CompileError as error:
                self.fail(error.log_path.read_text())
            self.assertIn('DRAFT-AUTO:false', log.read_text())
            pdf = root / 'disabled.pdf'
            self.assertFalse(pdf.exists() and pdf.stat().st_size)

    def test_final_full_pass_restores_every_layer_and_manifest(self):
        reference, automatic = (self.results[mode] for mode in ('reference', 'automatic'))
        self.assertEqual(automatic['full']['auto'], ['false'])
        for field in ('counts', 'boxes', 'requests', 'aux', 'index', 'manifest'):
            self.assertEqual(reference['full'][field], automatic['full'][field], field)
        counts = automatic['full']['counts']
        self.assertEqual(counts['spell'], 11 * counts['native'])
        self.assertEqual(counts['scorealt'], 11 * counts['score'])
        info = automatic['full']['manifest']['multikey_info']
        songs = info['songs']
        self.assertEqual([song['occurrence'] for song in songs], [1, 1, 2])
        self.assertEqual(songs[0]['layer_page_indices'], songs[1]['layer_page_indices'])
        self.assertNotEqual(songs[0]['layer_page_indices'], songs[2]['layer_page_indices'])
        self.assertTrue(all(song['layer_page_indices'] for song in songs))
        structure = PdfStructure(automatic['pdf'])
        expected = {f"{song['layer_prefix']}:t{offset:02d}"
                    for song in songs for offset in range(12)}
        self.assertEqual(set(structure.names.values()), expected)
        with pikepdf.open(io.BytesIO(automatic['pdf'])) as pdf:
            actual_layers = set()
            for page in pdf.pages:
                properties = page.Resources.get('/Properties', {})
                for operands, operator in pikepdf.parse_content_stream(page):
                    if str(operator) == 'BDC' and str(operands[0]) == '/OC':
                        actual_layers.add(str(properties[operands[1]].Name))
            self.assertEqual(actual_layers, expected)
            self.assertEqual(len(pdf.pages), automatic['full']['counts']['pages'])
            self.assertEqual(layer_page_dependencies(pdf),
                             {song['layer_prefix']: song['layer_page_indices'] for song in songs})
            drawings = score_layer_drawings(pdf, generic=True)
        for song in (songs[0], songs[2]):
            for offset in range(12):
                name = f"{song['layer_prefix']}:t{offset:02d}"
                self.assertEqual(len(drawings[name]), 2)
                if offset:
                    self.assertNotEqual(drawings[name], drawings[f"{song['layer_prefix']}:t00"])
        selected = structure.selected_pdf(automatic['pdf'], {1: 5, 3: 7})
        self.assertNotEqual(rendered_pages(selected), rendered_pages(automatic['pdf']))

    def test_forced_skeleton_preserves_original_geometry_and_navigation(self):
        baseline, automatic, skeleton = (self.results[mode]
                                         for mode in ('reference', 'automatic', 'skeleton'))
        for field in ('boxes', 'requests', 'aux', 'index', 'manifest'):
            self.assertEqual(baseline['full'][field], skeleton['full'][field], field)
        self.assertEqual(skeleton['full']['auto'], ['false'])
        self.assertEqual(skeleton['full']['counts']['spell'], 0)
        self.assertEqual(skeleton['full']['counts']['scorealt'], 0)
        self.assertTrue(baseline['full']['boxes'])
        original_words = words_and_geometry(baseline['pdf'])
        original_pixels = rendered_pages(baseline['pdf'])
        original_navigation = navigation(baseline['pdf'])
        self.assertTrue(original_navigation[0])
        self.assertTrue(original_navigation[1])
        # Both real full outputs include the same hidden words and must match
        # exactly. The test-only skeleton contains only original-view text;
        # Poppler may extract extra hidden key-badge words from the full PDF.
        self.assertEqual(words_and_geometry(automatic['pdf']), original_words)
        self.assertFalse(Counter(words_and_geometry(skeleton['pdf'])) - Counter(original_words))
        for result in (automatic, skeleton):
            self.assertEqual(rendered_pages(result['pdf']), original_pixels)
            self.assertEqual(navigation(result['pdf']), original_navigation)


if __name__ == '__main__':
    unittest.main()
