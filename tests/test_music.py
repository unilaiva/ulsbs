# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Token transposition and independently composed music ink."""

import os
from pathlib import Path
import re
import unittest

import test_song_lifecycle as helpers
from test_tex_integration import ROOT, compile_fixture


ADAPTER = r"""
\ExplSyntaxOn
\NewDocumentCommand\MusicProbe{m}
 {\__ulsbs_music_transpose:nN {#1}\l_tmpa_tl
  \iow_term:x {MUSIC=[\tl_to_str:V \l_tmpa_tl]}}
\NewDocumentCommand\MusicAnnotation{m}
 {\__ulsbs_music_annotation:n {#1}\box_use:N \l__ulsbs_chord_box}
\ExplSyntaxOff
"""


REPEAT_PROBE = r"""
\newbox\RepeatProbeBox
\newdimen\RepeatRuleWidth
\newdimen\ExpectedRepeatHeight
\newcommand\ProbeRepeat[1]{%
 \ifulShowChords
  \ExpectedRepeatHeight=\dimexpr\baselineskip+\ulRepeatBarHeightAdjustmentWithChords\relax
 \else
  \settoheight\ExpectedRepeatHeight{A}%
  \advance\ExpectedRepeatHeight\ulRepeatBarHeightAdjustmentNoChords
 \fi
 \setbox\RepeatProbeBox=\hbox{\lrep\rrep}%
 \RepeatRuleWidth=1.618034\ulRepeatBarWidth
 \directlua{
  local colons, rules = 0, 0
  local function walk(head)
   for n in node.traverse(head) do
    if n.id == node.id('glyph') and n.char == 58 then colons = colons + 1 end
    if n.id == node.id('rule') then
     rules = rules + 1
     assert(n.width == tex.dimen.RepeatRuleWidth, 'repeat rule width')
     assert(n.height == tex.dimen.ExpectedRepeatHeight, 'repeat rule height')
     assert(n.depth == tex.dimen.ulRepeatBarDepth, 'repeat rule depth')
    end
    if n.id == node.id('hlist') or n.id == node.id('vlist') then walk(n.list) end
   end
  end
  walk(tex.box.RepeatProbeBox.list)
  assert(rules == 2, 'repeat rule count')
  texio.write_nl('REPEAT:#1:' .. colons)
 }%
 \typeout{REPEAT-DIMS:#1:\the\wd\RepeatProbeBox/\the\ht\RepeatProbeBox/\the\dp\RepeatProbeBox}}
"""


class MusicTests(unittest.TestCase):
    compile_source = helpers.SongLifecycleTests.compile_source
    pdf_text = helpers.SongLifecycleTests.pdf_text
    setUp = helpers.SongLifecycleTests.setUp

    @classmethod
    def setUpClass(cls):
        helpers.SongLifecycleTests.setUpClass.__func__(cls)
        cls.diagnostics = Path(os.environ.get(
            "ULSBS_MUSIC_DIAGNOSTICS", ROOT / "build/music"))
        cls.diagnostics.mkdir(parents=True, exist_ok=True)

    def test_transpose_preserves_groups_spaces_and_unexpanded_effects(self):
        output = self.compile_source(helpers.document(r"""
\transpose{2}
\MusicProbe{C m/G \textbf{F} \Effect}
\typeout{MUSIC-EFFECTS=\the\Effects}
Text.
""", ADAPTER + r"\newcount\Effects\def\Effect{\global\advance\Effects1 X}"))
        self.assertIn(r"MUSIC=[D m/A \textbf {F} \Effect ]", output)
        self.assertEqual(re.findall(r"MUSIC-EFFECTS=(\d+)", output), ["0"])

    def test_effective_key_major_minor_and_enharmonic_fallback(self):
        output = self.compile_source(helpers.document(r"""
\begin{ulSongs}{}
\beginsong{Major}[key={D}]
\transpose{2}\MusicProbe{C F G B}
\endsong
\beginsong{Minor}[key={F#m}]
\transpose{-2}\MusicProbe{G A B C D E F}
\endsong
\end{ulSongs}
""", ADAPTER))
        self.assertIn("MUSIC=[D G A C\\shrp ]", output)
        self.assertIn("MUSIC=[F G A B\\flt  C D E\\flt ]", output)

    def test_zero_preserves_enharmonic_notes_and_explicit_accidentals(self):
        output = self.compile_source(helpers.document(r"""
\MusicProbe{B\shrp C\flt F\shrp{}m/C\shrp{}}
Text.
""", ADAPTER))
        self.assertIn(r"MUSIC=[B\shrp C\flt F\shrp {}m/C\shrp {}]", output)

    def test_transposition_matches_current_policy_all_offsets_and_keys(self):
        body = [r"\begin{ulSongs}{}"]
        for key in ("C", "D", "B&", "F#", "Am", "F#m", "B&m"):
            for offset in range(-6, 7):
                body.extend((rf"\beginsong{{Policy}}[key={{{key}}}]",
                             rf"\transpose{{{offset}}}",
                             r"\MusicProbe{C C\shrp D E\flt E F F\shrp G A\flt A B\flt B}",
                             r"\endsong"))
        body.append(r"\end{ulSongs}")
        source = helpers.document("\n".join(body), ADAPTER)
        output = self.compile_source(source, label="transposition")
        rows = re.findall(r"MUSIC=\[([^\n]*)\]", output)
        self.assertEqual(len(rows), 7 * 13)
        for start in range(0, len(rows), 13):
            self.assertEqual(rows[start], rows[start + 12])
            self.assertEqual(rows[start + 6], r"C C\shrp D E\flt E F F\shrp G A\flt A B\flt B")

    def test_melody_voices_beats_offsets_and_unpitched_marks(self):
        self.compile_source(helpers.document(r"""
\begin{ulSongs}{}
\beginsong{Music}[key={C}]
\beginverse*
\MusicAnnotation{<* CDE; G_/@1em>Am} First
\ulMelodyPrimaryPosition{low}\ulMelodySecondaryPosition{below}
\MusicAnnotation{<!* C; /@-1em>G} Second
\notesoff\MusicAnnotation{<* CDE>F} Hidden
\beatsoff\MusicAnnotation{<* CDE>} Empty
\noteson\beatson\ulMelodyStyleMapping{swapped}
\MusicAnnotation{<C; G>} Last
\endverse
\endsong
\end{ulSongs}
""", ADAPTER))
        text = self.pdf_text()
        self.assertIn("First", text)
        self.assertIn("Last", text)
        self.assertIn("/", text)

    def compile_checked(self, body, preamble=""):
        source = helpers.document(body, preamble)
        output = self.compile_source(source)
        self.assertTrue(self.pdf_text().strip())
        self.assertNotIn("Missing character:", output)

    def test_melody_annotation_positions_compile(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Melody}[key={D}]
\transpose{2}
\beginverse*+
\[<* CDE; G_/@1em>Am]First \[<!* C; /@-1em>G]Second
\ulMelodyPrimaryPosition{low}\ulMelodySecondaryPosition{below}
\[<* FG; C/>F]Low \[<*>]Beat
\notesoff\[<* CDE>F]Hidden \beatsoff\[<CDE>]Invisible
\noteson\beatson\ulMelodyStyleMapping{swapped}
\[<C; G>]Last
\endverse
\endsong
\end{ulSongs}
""")

    def test_nested_repeat_and_meter_compile(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Repeats}
\beginverse*
\beginrep\prep{3}
\[C]First | \[G]Second \rep{2}
\beginrep
\lrep \[Am]Nested \rrep
\endrep
\meter{3}{4}| \[F]Last
\endrep
Outside.
\endverse
\endsong
\end{ulSongs}
""")

    def test_inline_repeat_owner_is_unique_and_uses_effective_chord_policy(self):
        entry = (ROOT / "src/ulsbs/assets/tex/ulsbs.sty").read_text()
        music = (ROOT / "src/ulsbs/assets/tex/ulsbs-music.code.tex").read_text()
        for name in ("lrep", "rrep"):
            self.assertNotRegex(entry, r"\\(?:DeclareDocumentCommand|newcommand)\\" + name)
            self.assertEqual(music.count("\\cs_set_protected:Npn \\" + name), 1)
        inline = music.split("% Inline left/right signs", 1)[1].split("% #1 is repeat-count", 1)[0]
        self.assertEqual(inline.count(r"\ifulShowChords"), 2)

    def test_inline_repeat_effective_chord_row_and_authored_rules_on_both_entry_paths(self):
        # Deliberately non-default metrics: compare real rules, not just predicates.
        preamble = REPEAT_PROBE + r"""
\ulRepeatBarWidth=2.1pt\ulRepeatBarDepth=3.2pt
\ulRepeatBarHeightAdjustmentWithChords=4.3pt
\ulRepeatBarHeightAdjustmentNoChords=5.4pt
\renewcommand\ulChordLineBaselineSkip{12.3pt}
\ProbeRepeat{preset}
"""
        for variant in ("default", "lyric", "charango", "bassclef", "package"):
            for allow in (False, True):
                with self.subTest(variant=variant, allow=allow):
                    permission = str(allow).lower()
                    setup = preamble + (rf"\ulShowChords{{{permission}}}"
                                        + r"\ulShowNotes{true}\ulShowBeats{true}")
                    body = []
                    expected = {"preset": 4 if variant in ("default", "charango", "package") else 2}
                    for chords in (False, True):
                        for notes in (False, True):
                            for beats in (False, True):
                                label = f"c{int(chords)}n{int(notes)}b{int(beats)}"
                                controls = (rf"\ulLocalShow{{chords}}{{{str(chords).lower()}}}"
                                            rf"\ulLocalShow{{notes}}{{{str(notes).lower()}}}"
                                            rf"\ulLocalShow{{beats}}{{{str(beats).lower()}}}")
                                body.append("{" + controls + rf"\ProbeRepeat{{{label}}}" + "}")
                                expected[label] = 4 if allow and chords else 2
                    body.append(r"\ProbeRepeat{restored}\begin{ulSongs}{}\beginsong{Scope}[key={C}]")
                    body.append(r"\beginverse*\chordsoff\ProbeRepeat{verseoff}Scope\endverse")
                    body.append(r"\ProbeRepeat{afterverse}\chordsoff\ProbeRepeat{songoff}")
                    body.append(r"\endsong\end{ulSongs}\ProbeRepeat{aftersong}Text.")
                    expected.update(restored=4 if allow else 2, verseoff=2,
                                    afterverse=4 if allow else 2, songoff=2, aftersong=4 if allow else 2)
                    source = helpers.document("\n".join(body), setup)
                    if variant == "package":
                        source = source.replace("{ulsbs-songbook}", "{book}\\usepackage{ulsbs}")
                    else:
                        source = (rf"\def\ulBuildVariant{{{variant}}}" + source.replace(
                            "[oneside,", "[variants={default,lyric,charango,bassclef},oneside,"))
                    output = self.compile_source(source, label=f"{variant}-{permission}")
                    self.assertEqual(dict((key, int(value)) for key, value in re.findall(
                        r"REPEAT:([\w]+):(\d+)", output)), expected)
                    dims = dict(re.findall(r"REPEAT-DIMS:(\w+):([^\n]+)", output))
                    for chords in (0, 1):
                        # No pitch/beat state manufactures a repeat annotation row.
                        self.assertEqual(len({dims[f"c{chords}n{notes}b{beats}"]
                                              for notes in (0, 1) for beats in (0, 1)}), 1)
                    # Both authored height branches use the common helper unchanged.
                    self.assertEqual(dims["restored"], dims["aftersong"])

    def test_inline_repeats_keep_compact_real_annotation_ink_and_once_only_effects(self):
        preamble = r"""
\ulShowChords{true}\ulShowNotes{true}\ulShowBeats{true}
\newcount\ChordEffects\newcount\OffsetEffects\newcount\LyricEffects
\def\RepeatChordEffect{\global\advance\ChordEffects1 C}
\def\RepeatOffsetEffect{\directlua{tex.setcount('global','OffsetEffects',tex.count.OffsetEffects+1)}0pt}
\def\RepeatLyricEffect{\global\advance\LyricEffects1 }
\newbox\RepeatStanzaBox
\long\def\ProbeStanza#1#2{\setbox\RepeatStanzaBox=\vbox{\csname __ulsbs_verse_reset:\endcsname#2}%
 \typeout{STANZA:#1:\the\wd\RepeatStanzaBox/\the\ht\RepeatStanzaBox/\the\dp\RepeatStanzaBox}%
 \box\RepeatStanzaBox}
"""
        body = [r"\begin{ulSongs}{}\beginsong{Retained repeats}[id={retained},key={C}]"]
        for mode, controls, annotation in (
            ("hidden", r"\chordsoff\notesoff\beatsoff", r"<C@\RepeatOffsetEffect>\RepeatChordEffect"),
            ("beat", r"\chordsoff\notesoff\beatson", r"<* @\RepeatOffsetEffect>\RepeatChordEffect"),
            ("pitch", r"\chordsoff\noteson\beatsoff", r"<C;G@\RepeatOffsetEffect>\RepeatChordEffect"),
            ("chord", r"\chordson\notesoff\beatsoff", r"<C@\RepeatOffsetEffect>\RepeatChordEffect"),
        ):
            for marks in (False, True):
                label = mode + ("marks" if marks else "plain")
                left, right = (r"\lrep ", r" \rrep") if marks else ("", "")
                body.append("{" + controls + rf"\ProbeStanza{{{label}}}{{\beginverse*" + "\n"
                            + r"Beforeline\par " + left + rf"\[{annotation}]\RepeatLyricEffect Anchor"
                            + right + r"\par Afterline\par" + "\n" + r"\endverse}}")
        body.append(r"\endsong\end{ulSongs}\typeout{EFFECTS:\the\ChordEffects/\the\OffsetEffects/\the\LyricEffects}")
        results = []
        for layers in (False, True):
            source = (r"\def\ulPdfTranspositionLayers{" + str(layers).lower() + "}"
                      + helpers.document("\n".join(body), preamble))
            output = self.compile_source(source, label=f"layers-{layers}", passes=3)
            rows = dict((key, tuple(float(v) for v in values)) for key, *values in re.findall(
                r"STANZA:(\w+):([\d.]+)pt/([\d.]+)pt/([\d.]+)pt", output))
            self.assertEqual(re.findall(r"EFFECTS:([\d/]+)", output), ["2/4/8"] * 3)
            # No upper repeat row is manufactured for independent pitches/beats.
            # Tighter A-based leading can expose the existing inline sign's real
            # .25pt low hang in any compact mode; it must not add an annotation row.
            for mode in ("hidden", "beat", "pitch"):
                self.assertAlmostEqual(rows[mode + "marks"][1], rows[mode + "plain"][1], delta=.25)
                self.assertEqual(rows[mode + "marks"][2], rows[mode + "plain"][2])
            # Compact beat ink may fit within the lyric-leading lower bound.
            self.assertLessEqual(rows["hiddenmarks"][1], rows["beatmarks"][1])
            self.assertLess(rows["beatmarks"][1], rows["pitchmarks"][1])
            self.assertGreater(rows["chordmarks"][1], rows["hiddenmarks"][1])
            self.assertNotIn("Missing character:", output)
            results.append(rows)
        self.assertEqual(*results)

    def test_measure_ink_uses_effective_policy_and_consumes_pending_meter_once(self):
        preamble = r"""
\newcount\Effects
\def\Effect{\global\advance\Effects1 3}
\newbox\MeasureProbe
\def\ProbeMeasure#1#2{\setbox\MeasureProbe=\hbox{#2}%
 \typeout{MEASURE:#1:\the\wd\MeasureProbe/\the\ht\MeasureProbe/\the\dp\MeasureProbe}}
"""
        body = r"""
\meter{\Effect}{\Effect}
\measuresoff
\ProbeMeasure{hidden}{\measurebar\mbar{\iftrue}{\input{missing-meter}}\e}
\typeout{EFFECTS-HIDDEN=\the\Effects}
\measureson
\ProbeMeasure{pending}{\measurebar}
\ProbeMeasure{consumed}{\measurebar}
\typeout{EFFECTS-VISIBLE=\the\Effects}
{\ulLocalShow{measures}{false}
 \meter{\iftrue}{\input{missing-meter}}
 \ProbeMeasure{opaque}{\measurebar}
 \meter{}{}}
\ProbeMeasure{restored}{\mbar{\Effect}{\Effect}}
\typeout{EFFECTS-RESTORED=\the\Effects}
\ProbeMeasure{adjacent}{\measurebar\measurebar}
{\ExplSyntaxOn\bool_set_true:N\l__ulsbs_chord_in_altchords_bool\ExplSyntaxOff
 \ProbeMeasure{adjacentalt}{\measurebar\measurebar}}
Text.
"""
        rows = []
        for label, prefix in (("ordinary", ""),
                              ("layers", r"\def\ulPdfTranspositionLayers{true}")):
            with self.subTest(mode=label):
                output = self.compile_source(prefix + helpers.document(body, preamble), label=label)
                metrics = dict((name, tuple(float(v) for v in values)) for name, *values in re.findall(
                    r"MEASURE:(\w+):([\d.]+)pt/([\d.]+)pt/([\d.]+)pt", output))
                self.assertEqual(metrics["hidden"], (0., 0., 0.))
                self.assertEqual(metrics["opaque"], (0., 0., 0.))
                self.assertGreater(metrics["pending"][0], metrics["consumed"][0])
                self.assertGreater(metrics["consumed"][1], 0)
                self.assertEqual(metrics["pending"], metrics["restored"])
                self.assertEqual(metrics["adjacent"], metrics["adjacentalt"])
                self.assertIn("EFFECTS-HIDDEN=0", output)
                self.assertIn("EFFECTS-VISIBLE=2", output)
                self.assertIn("EFFECTS-RESTORED=4", output)
                rows.append(metrics)
        self.assertEqual(*rows)
        denied = self.compile_source(helpers.document(body, preamble + r"\ulShowMeasures{false}"),
                                     label="denied")
        self.assertEqual(re.findall(r"EFFECTS-(?:HIDDEN|VISIBLE|RESTORED)=(\d+)", denied),
                         ["0", "0", "0"])
        self.assertEqual(set(re.findall(r"MEASURE:\w+:([^\n]+)", denied)), {"0.0pt/0.0pt/0.0pt"})

    def test_measure_bars_follow_actual_annotations_on_each_wrapped_line(self):
        preamble = r"""
\newcount\ChordEffects
\newcount\LyricEffects
\newcount\OffsetEffects
\newcount\MeterEffects
\def\ChordEffect{\global\advance\ChordEffects1 C}
\def\LyricEffect{\global\advance\LyricEffects1 Anchor}
\def\OffsetEffect{\directlua{tex.setcount('global','OffsetEffects',tex.count.OffsetEffects+1)}4pt}
\def\MeterEffect{\global\advance\MeterEffects1 4}
\ulDeclareLyricChar{\LyricEffect}
\ulSongColumns{1}
\ulSongPosition{0}
% This fixture checks relative ordering under an explicit policy, not shipped
% presentation defaults. The separate policy matrix audits the live defaults.
\ulMeasureBarTop{0}{0}{1.25}\ulMeasureBarTop{1}{1}{1.25}
\ulMeasureBarTop{2}{2}{.75}\ulMeasureBarTop{3}{2}{.75}
\ulRepeatBarTop{0}{0}{1.2}\ulRepeatBarTop{1}{1}{1.2}
\ulRepeatBarTop{2}{2}{.8}\ulRepeatBarTop{3}{2}{.8}
\renewcommand\ulEveryVerse{\directlua{measure_base = tex.skip.baselineskip.width}}
\newcommand\MeasureCase[1]{\directlua{measure_case = '#1'; measure_line = 0}}
% post_linebreak_filter executes its explicitly ordered callback list in reverse.
\directlua{
 local hlist, vlist, rule = node.id('hlist'), node.id('vlist'), node.id('rule')
 local attribute = \number\csname c__ulsbs_music_measure_attribute_int\endcsname
 local annotation = \number\csname c__ulsbs_chord_annotation_attribute_int\endcsname
   local repetition = \csname ulsbs@rep@attribute\endcsname
 local normal_height = \csname ulsbs@rep@heightattribute\endcsname
 local center_attribute = \number\csname c__ulsbs_music_note_center_attribute_int\endcsname
 local before, before_rules
 luatexbase.add_to_callback('post_linebreak_filter', function(head)
   before = {}
   before_rules = {}
   local function snapshot(list)
     for n in node.traverse(list) do
       if n.id == rule and node.has_attribute(n, repetition) then
         before_rules[node.direct.todirect(n)] = {n.height, node.has_attribute(n, normal_height)}
       elseif n.id == hlist then snapshot(n.list) end
     end
   end
   for line in node.traverse_id(hlist, head) do
     table.insert(before, {line.width, line.height, line.depth})
     snapshot(line.list)
   end
   return head
 end, 'ulsbs-test-measure-before')
 luatexbase.add_to_callback('post_linebreak_filter', function(head)
   if not measure_case then return head end
   local index = 0
   for line in node.traverse_id(hlist, head) do
     index = index + 1
     assert(line.width == before[index][1] and line.height == before[index][2] and
       line.depth == before[index][3], 'measure reach must not alter line dimensions')
     local top, bars, repetitions = 0, {}, {}
     local upper_top, upper_mid = 0, 0
     local function notes(list, baseline)
       for n in node.traverse_id(hlist, list) do
         local raised = baseline - n.shift
         local center = node.has_attribute(n, center_attribute)
         if center then
           if raised + n.height > upper_top then
             upper_top, upper_mid = raised + n.height, raised + center
           end
         elseif not (n.width == 0 and n.height == 0 and n.depth == 0) then notes(n.list, raised) end
       end
     end
     local function inspect(list, baseline)
       for n in node.traverse(list) do
         if n.id == rule and node.has_attribute(n, repetition) then
           table.insert(repetitions, {box = n, baseline = baseline})
         elseif n.id == vlist or n.id == hlist then
           local raised = baseline - n.shift
           if node.has_attribute(n, attribute) == 1 then
             table.insert(bars, {box = n, baseline = raised})
           elseif node.has_attribute(n, annotation) then
             top = math.max(top, n.height + raised)
             if n.id == vlist then
               for row in node.traverse_id(hlist, n.list) do
                 notes(row.list, raised + n.height - row.height)
                 break
               end
             else notes(n.list, raised) end
           elseif n.id == hlist then inspect(n.list, raised) end
         end
       end
     end
     inspect(line.list, 0)
     if \string#bars > 0 or (\string#repetitions > 0 and top > 0) then
       measure_line = measure_line + 1
        local data = node.getproperty(line).ulsbs_music
        local level = data.level
         local function selected(kind)
           local prefix='ulsbs@'..kind..'@'
           local reference=tonumber(token.get_macro(prefix..'level@'..level))
           local scale=tonumber(token.get_macro(prefix..'scale@'..level))
           local ref=assert(data.references[reference])
           return math.floor(ref.bottom+ref.base*scale+.5)
         end
         local expected, repeat_target = selected('measure'), selected('repeat')
       for _, entry in ipairs(bars) do
         local bar, meter, last = entry.box, 0
         for row in node.traverse_id(hlist, bar.list) do
           if last then meter = meter + last.height + last.depth end
           last = row
         end
         if meter > 0 then meter = meter + tex.sp('.75pt') end
         local target = math.max(meter, expected - entry.baseline)
         assert(math.abs(bar.height - target) < 2,
           'bar must reach actual line annotation top: ' .. measure_case .. ':' ..
           bar.height .. '/' .. target .. '/' .. top)
         local rules = 0
         for row in node.traverse_id(hlist, bar.list) do
           for ink in node.traverse_id(rule, row.list) do
             rules = rules + 1
             assert(math.abs(ink.height + meter - bar.height) < 2,
               'bar ink plus retained meter must match its extent')
           end
         end
         assert(rules == 1, 'one measure rule')
       end
       if measure_line == 1 then assert(\string#repetitions > 0, 'verse-left repeat present') end
       for _, entry in ipairs(repetitions) do
         local bar = entry.box
         local prior = before_rules[node.direct.todirect(bar)]
          local target = math.max(0, repeat_target - entry.baseline)
          assert(bar.height == target + math.max(0, prior[1] - prior[2]),
            'repeat rule must use its own policy and preserve authored overlap')
          assert(node.has_attribute(bar, normal_height) == target,
            'incoming continuation metadata must retain adjusted reach')
           assert(bar.depth == math.floor(data.references[0].base * tonumber(token.get_macro('ulsbs@repeat@bottomscale')) + .5),
            'repeat depth must scale from the lyric capital A')
         if measure_case == 'empty' and measure_line == 1 then
           assert(node.has_attribute(bar, normal_height) < bars[1].box.height,
             'repeat height must not inherit the ordinary measure height')
         end
       end
       texio.write_nl('BAR-LINE:' .. measure_case .. ':' .. measure_line .. ':' ..
         expected .. '/' .. line.height .. '/' .. line.depth .. '/' .. line.width)
     end
   end
   return head
 end, 'ulsbs-test-measure-reach')
 luatexbase.declare_callback_rule('post_linebreak_filter',
   'ulsbs-test-measure-reach', 'before', 'ulsbs-measure-reach')
 luatexbase.declare_callback_rule('post_linebreak_filter',
   'ulsbs-test-measure-before', 'after', 'ulsbs-measure-reach')
}
"""
        body = [r"\begin{ulSongs}{}\beginsong{Bar reach}[key={C}]"]
        for label, controls, modifier, annotation in (
            ("empty", "", "", ""),
            ("chord", "", "", r"\[\ChordEffect]"),
            ("chordnotesoff", r"\notesoff", "", r"\[\ChordEffect]"),
            ("pitch", r"\chordsoff", "", r"\[<C;G@\OffsetEffect>\ChordEffect]"),
            ("beat", r"\chordsoff\notesoff", "", r"\[<*>\ChordEffect]"),
            ("hidden", r"\chordsoff\notesoff\beatsoff", "", r"\[<C@\OffsetEffect>\ChordEffect]"),
            ("plus", "", "+", r"\[C]"),
            ("spacing", r"\renewcommand{\ulChordLineParams}{\baselineskip=24pt}", "", r"\[C]"),
            ("raw", "", "", r"{\nolyrics \[<C@4pt>]}"),
            ("nested", "", "", r"\raisebox{3pt}{\hbox{|\[<C>]Nested |}}"),
            ("meter", "", "", r"\[C]"),
            ("unrelated", "", "", r"\rule{0pt}{40pt}"),
            ("chordnote", "", "", r"\[<C>C]"),
            ("chordtwonotes", "", "", r"\[<C;G>C]"),
            ("notesofftwo", r"\notesoff", "", r"\[<C;G>C]"),
            ("samerow", r"\ulMelodySecondaryPosition{same}", "", r"\[<C;G>C]"),
            ("below", r"\ulMelodySecondaryPosition{below}", "", r"\[<C;G>C]"),
            ("restsecondary", "", "", r"\[<C;_>C]"),
            ("restprimary", "", "", r"\[<_;G>C]"),
            ("adjacent", "", "", r"\[<!C;G>]\[C]"),
            ("repeatonly", r"\measuresoff", "", r"\[<C>C]"),
            ("continuing", r"\renewcommand{\ulRepeatBarContinuingOverlap}{60pt}", "", r"\[<C;G>C]"),
        ):
            meter = r"\meter{\MeterEffect}{\MeterEffect}" if label == "meter" else r"\meter{}{}"
            body.extend((r"{\MeasureCase{" + label + "}" + controls,
                         r"\beginverse*" + modifier,
                         r"\beginrep" + ("\nPrelude." if label == "continuing" else ""),
                         meter + "|" + annotation + r"\LyricEffect |tail\hfil\break"
                         r"|Plain wrapped continuation |tail.",
                         r"\endrep\endverse}"))
        body.extend((r"\directlua{measure_case = nil}", r"\endsong\end{ulSongs}",
                     r"\typeout{BAR-EFFECTS:\the\ChordEffects/\the\LyricEffects/\the\OffsetEffects/\the\MeterEffects}"))
        results = []
        for variant, layers in ((variant, layers)
                                for variant in ("default", "charango", "bassclef")
                                for layers in (False, True)):
            override = (r"\ulShowChords{true}\ulShowNotes{true}\ulShowBeats{true}"
                        if variant == "bassclef" else "")
            source = (r"\def\ulPdfTranspositionLayers{" + str(layers).lower() + "}"
                      + (rf"\def\ulBuildVariant{{{variant}}}" if variant != "default" else "")
                      + helpers.document("\n".join(body), override + preamble).replace(
                          "[oneside,", "[variants={default,charango,bassclef},oneside,", 1))
            output = self.compile_source(source, label=f"reach-{variant}-{layers}", passes=3)
            rows = dict((label + number, tuple(map(int, values)))
                        for label, number, *values in re.findall(
                            r"BAR-LINE:(\w+):(\d+):(\d+)/(\d+)/(\d+)/(\d+)", output))
            self.assertEqual(len(rows), 43)
            self.assertEqual(re.findall(r"BAR-EFFECTS:([\d/]+)", output), ["2/22/1/2"] * 3)
            self.assertEqual(rows["chord1"], rows["chordnotesoff1"])
            self.assertEqual(rows["chord1"], rows["notesofftwo1"])
            self.assertEqual(rows["empty1"], rows["hidden1"])
            self.assertGreater(rows["chord1"][0], rows["empty1"][0])
            self.assertGreater(rows["pitch1"][0], rows["chord1"][0])
            self.assertLess(rows["beat1"][0], rows["chord1"][0])
            self.assertGreater(rows["spacing1"][0], rows["chord1"][0])
            self.assertEqual(rows["plus2"], rows["chord2"])
            self.assertEqual(rows["chord2"], rows["empty2"])
            self.assertEqual(rows["unrelated1"][0], rows["empty1"][0])
            self.assertGreater(rows["raw1"][0], rows["empty1"][0])
            self.assertGreater(rows["nested1"][0], rows["chord1"][0])
            self.assertNotIn("Missing character:", output)
            results.append(rows)
            if layers:
                self.assertEqual(results[-2], results[-1])

    def test_annotation_stacks_align_per_physical_line_without_moving_lyrics(self):
        # Inspect owned nodes independently of the runtime's geometry collector.
        preamble = r"""
\ulShowChords{true}\ulShowNotes{true}\ulShowBeats{true}
\ulSongColumns{1}\ulSongPosition{0}
\renewcommand\ulMelodySize{\ulMicroSize}
\newcount\AlignEffects
\def\AlignEffect{\global\advance\AlignEffects1 Fmaj7}
\newcommand\AlignCase[1]{\directlua{align_case = '#1'; align_line = 0}}
\directlua{
 local hlist, vlist, kern = node.id('hlist'), node.id('vlist'), node.id('kern')
 local annotation = \number\csname c__ulsbs_chord_annotation_attribute_int\endcsname
 local measure = \number\csname c__ulsbs_music_measure_attribute_int\endcsname
 local center = \number\csname c__ulsbs_music_note_center_attribute_int\endcsname
 local radius = \number\csname c__ulsbs_music_note_radius_attribute_int\endcsname
 local function visible(n) return not (n.width == 0 and n.height == 0 and n.depth == 0) end
 local function snapshot(line)
  local result = {stacks = {}, raw = {}, groups = {}, bars = {}, notes = {}}
  local function circles(list, baseline)
   for n in node.traverse_id(hlist, list) do
    local b = baseline - n.shift
    local c = node.has_attribute(n, center)
    if c then
     result.notes[\string#result.notes + 1] = {bottom = b + c - node.has_attribute(n, radius),
       base = 2 * node.has_attribute(n, radius)}
    elseif visible(n) then circles(n.list, b) end
   end
  end
  local function collect(list, parent)
   for n in node.traverse(list) do
    if n.id == hlist or n.id == vlist then
     if node.has_attribute(n, annotation) then
      if n.id == vlist then
       local rows, cursor, first = {}, n.height
       for row in node.traverse(n.list) do
        if row.id == hlist then
         rows[\string#rows + 1] = {id = node.direct.todirect(row),
           baseline = cursor - row.height, width = row.width,
           height = row.height, depth = row.depth, shift = row.shift}
         if not first then first = row end
         cursor = cursor - row.height - row.depth
        elseif row.id == kern then cursor = cursor - row.kern
        elseif row.id == node.id('glue') then cursor = cursor - row.width end
       end
       assert(first and \string#rows >= 2, 'owned stack has annotation and lyric rows')
       local b = n.height - first.height
       result.stacks[node.direct.todirect(n)] = {box = n, baseline = b,
         parent = parent, height = n.height, depth = n.depth, width = n.width,
         shift = n.shift, rows = rows}
       result.groups[parent] = math.max(result.groups[parent] or -math.huge, b)
       circles(first.list, parent + b)
      else
       result.raw[node.direct.todirect(n)] = {n.width, n.height, n.depth, n.shift}
      end
     elseif node.has_attribute(n, measure) == 1 then
      local rows = {}
      for row in node.traverse_id(hlist, n.list) do
       rows[\string#rows + 1] = {row.width, row.height, row.depth, row.shift}
      end
      result.bars[\string#result.bars + 1] = {box = n, baseline = parent - n.shift, rows = rows}
     elseif n.id == hlist and visible(n) then collect(n.list, parent - n.shift) end
    end
   end
  end
  collect(line.list, 0)
  return result
 end
 local before = {}
 luatexbase.add_to_callback('post_linebreak_filter', function(head)
  before = {}
  if align_case then
   for line in node.traverse_id(hlist, head) do
    before[node.direct.todirect(line)] = snapshot(line)
   end
  end
  return head
 end, 'ulsbs-test-align-before')
 luatexbase.add_to_callback('post_linebreak_filter', function(head)
  if not align_case then return head end
  for line in node.traverse_id(hlist, head) do
   local old, now = assert(before[node.direct.todirect(line)]), snapshot(line)
   local count, moved, group_count = 0, 0, 0
   for _ in pairs(old.groups) do group_count = group_count + 1 end
   for id, prior in pairs(old.stacks) do
    local current = assert(now.stacks[id], 'same owned stack retained')
    local expected = old.groups[prior.parent]
    local delta = expected - prior.baseline
    assert(current.baseline == expected, 'annotation baseline must equal physical-line group maximum: '
      .. align_case .. ':' .. current.baseline .. '/' .. expected)
    assert(delta >= 0 and current.height == prior.height + delta, 'raise only; grow stack by exact delta')
    assert(current.width == prior.width and current.depth == prior.depth and current.shift == prior.shift,
      'alignment preserves horizontal width, lyric depth and wrapper shift')
    assert(\string#current.rows == \string#prior.rows, 'no phantom annotation/lyric row')
    for index, row in ipairs(prior.rows) do
     local retained = current.rows[index]
     assert(retained.id == row.id and retained.width == row.width and retained.height == row.height
       and retained.depth == row.depth and retained.shift == row.shift, 'row geometry unchanged')
     assert(retained.baseline == row.baseline + (index == 1 and delta or 0),
       'only annotation row moves; lyric baseline unchanged')
    end
    count = count + 1
    if delta > 0 then moved = moved + 1 end
   end
   for id, prior in pairs(old.raw) do
    local current = assert(now.raw[id], 'raw annotation retained')
    for i, value in ipairs(prior) do assert(current[i] == value, 'raw nolyrics hlist unchanged') end
   end
   for index, prior in ipairs(old.bars) do
    local current = assert(now.bars[index])
    assert(current.box == prior.box and current.baseline == prior.baseline, 'measure wrapper retained')
    for row = 1, \string#prior.rows - 1 do
     for field, value in ipairs(prior.rows[row]) do
      assert(current.rows[row][field] == value, 'pending meter row geometry unchanged')
     end
    end
   end
   if count > 0 or \string#now.bars > 0 then
    align_line = align_line + 1
    local maximum = old.groups[0] or 0
    if align_case == 'wrappers' then
     assert(group_count == 3 and old.groups[tex.sp('3pt')] and old.groups[-tex.sp('3pt')],
       'intentional raised/lowered horizontal wrappers retain separate lyric baselines')
    end
    if align_case == 'hidden' or align_case == 'empty' then
     assert(count == 0 and \string#now.notes == 0, 'hidden/empty source has no phantom anchors')
    end
    if align_case == 'beat' then
     for _, entry in pairs(now.stacks) do
      assert(entry.height < tex.sp('13pt'), 'beat-only stack stays compact, not a full chord row')
     end
    end
    local data = (node.getproperty(line) or {}).ulsbs_music
    if data and \string#now.notes > 0 then
     local selected = tonumber(token.get_macro('ulsbs@measure@level@' .. data.level))
     local scale = tonumber(token.get_macro('ulsbs@measure@scale@' .. data.level))
     if selected == 2 then
      local highest
      for _, circle in ipairs(now.notes) do
       if not highest or circle.bottom + circle.base > highest.bottom + highest.base then highest = circle end
      end
      local target = math.floor(highest.bottom + highest.base * scale + .5)
      for _, entry in ipairs(now.bars) do
       if not (align_case == 'meter') then
        assert(math.abs(entry.box.height + entry.baseline - target) <= 1,
          'bar follows aligned actual circle and current configured scale')
       end
      end
     end
    end
    texio.write_nl('ALIGN:' .. align_case .. ':' .. align_line .. ':' .. count .. '/' .. moved
      .. '/' .. group_count .. '/' .. maximum)
   end
  end
  return head
 end, 'ulsbs-test-align-after')
 luatexbase.declare_callback_rule('post_linebreak_filter',
   'ulsbs-test-align-before', 'after', 'ulsbs-measure-reach')
 luatexbase.declare_callback_rule('post_linebreak_filter',
   'ulsbs-test-align-after', 'before', 'ulsbs-measure-reach')
 local finish = ulsbs_music.finish_verse
 ulsbs_music.finish_verse = function(id)
  finish(id)
  local retained = {}
  for line in node.traverse_id(hlist, tex.box[id].list) do retained[line] = snapshot(line) end
  finish(id)
  for line, prior in pairs(retained) do
   local current = snapshot(line)
   for key, old in pairs(prior.stacks) do
    local new = assert(current.stacks[key])
    assert(new.height == old.height and new.baseline == old.baseline and new.depth == old.depth,
      'alignment is idempotent on repeated stanza finalization')
   end
  end
 end
}
"""
        body = r"""
\begin{ulSongs}{}\beginsong{Lunita line regression}[id={line-align},key={C}]
\meter{}{}
\AlignCase{verseone}\beginverse*|\[<C>Am]Lunita |\[<D>G]clara |\[<E>C]canta\endverse
\AlignCase{versetwo}\beginverse*|\[<C>Fmaj7]Lunita |\[<D>G]clara |\[<E>C]canta\endverse
\AlignCase{versethree}\beginverse*|\[<C>Am]Lunita |\[<D>G]clara |\[<E>C]canta\endverse
\AlignCase{versefour}\beginverse*|\[<C>Am]Lunita |\[<D>G]clara |\[<E @3ex>Fmaj7]{luz to}\endverse
\AlignCase{wrap}\beginverse*|\[<C>C]Alpha \[<D>Fmaj7]Beta\hfil\break|\[<E>C]Gamma \[<F>G]Delta\endverse
\AlignCase{wrappers}\beginverse*|\[<C>C]Alpha \[<D>Fmaj7]Beta \raisebox{3pt}{\hbox{\[<C>C]Up \[<D>Fmaj7]High}} \raisebox{-3pt}{\hbox{\[<C>C]Down \[<D>Fmaj7]Low}}\endverse
\AlignCase{meter}\meter{3}{4}\beginverse*|\[<C>C]Alpha \[<D>Fmaj7]Beta\endverse
\AlignCase{alt}\beginverse*|\[<C>C]Alpha \[<D>Fmaj7]Beta \altchords{|Gmaj7 |F#m7}\endverse
\AlignCase{local}\beginverse*|{\notesoff\[<C>Fmaj7]Quiet} \[<D>C]Loud\endverse
\AlignCase{hidden}\beginverse*|{\chordsoff\notesoff\beatsoff\[<C>Fmaj7]Quiet}\endverse
\AlignCase{empty}\beginverse*|\[]Empty\endverse
\AlignCase{beat}\beginverse*|\[<*>] \[<*>]x \[<*>]ffl\endverse
\AlignCase{raw}\beginverse*|{\nolyrics\[<C>C]\[<D>Fmaj7]}\[<E>C]Word\endverse
\newchords{align}
\AlignCase{replay}\beginverse*\memorize[align]|\[<C>C]Alpha \[<D>\AlignEffect]Beta\endverse
\typeout{ALIGN-FIRST-EFFECTS:\the\AlignEffects}
\AlignCase{replayed}\beginverse*\replay[align]|^Alpha ^Beta\endverse
\directlua{align_case = nil}\typeout{ALIGN-EFFECTS:\the\AlignEffects}
\endsong\end{ulSongs}
"""
        results = []
        for layers in (False, True):
            with self.subTest(layers=layers):
                source = (r"\def\ulPdfTranspositionLayers{" + str(layers).lower() + "}"
                          + helpers.document(body, preamble).replace(
                              r"\documentclass[oneside,openany,maintitle={Lifecycle}]{ulsbs-songbook}",
                              r"\documentclass{book}\usepackage{ulsbs}", 1))
                output = self.compile_source(source, label=f"align-{layers}", passes=2)
                rows = dict((name + number, tuple(map(int, values))) for name, number, *values in re.findall(
                    r"ALIGN:(\w+):(\d+):(\d+)/(\d+)/(\d+)/(\d+)", output))
                self.assertEqual(len(rows), 16)
                self.assertGreater(rows["versetwo1"][1], 0)
                self.assertGreater(rows["versefour1"][1], 0)
                self.assertGreater(rows["wrap1"][3], rows["wrap2"][3])
                self.assertEqual(rows["wrap2"][1], 0)
                self.assertEqual(rows["wrappers1"][2], 3)
                self.assertEqual(rows["replay1"], rows["replayed1"])
                self.assertEqual(re.findall(r"ALIGN-FIRST-EFFECTS:(\d+)", output), ["1", "1"])
                self.assertEqual(re.findall(r"ALIGN-EFFECTS:(\d+)", output), ["2", "2"])
                self.assertNotIn("Missing character:", output)
                results.append(rows)
        self.assertEqual(*results)

    def test_measure_actual_rows_reach_uppermost_note_circle_midpoint(self):
        # Keep the original difficult circle fixtures, but exercise configurable
        # reference selection rather than the retired row-count/midpoint policy.
        preamble = r"""
\ulShowChords{true}\ulShowNotes{true}\ulShowBeats{true}
\ulSongColumns{1}\ulSongPosition{0}
\renewcommand\ulCircledCircleVerticalShift{2pt}
\newcommand\MidpointCase[4]{\directlua{
 midpoint_case = '#1'; midpoint_rows = #2; midpoint_notes = #3; midpoint_level = #4}}
\directlua{
 local finish = ulsbs_music.finish_verse
 local hlist, vlist, rule = node.id('hlist'), node.id('vlist'), node.id('rule')
 local annotation = \number\csname c__ulsbs_chord_annotation_attribute_int\endcsname
 local row_attribute = \number\csname c__ulsbs_chord_row_attribute_int\endcsname
 local measure = \number\csname c__ulsbs_music_measure_attribute_int\endcsname
 local center_attribute = \ifcsname c__ulsbs_music_note_center_attribute_int\endcsname
   \number\csname c__ulsbs_music_note_center_attribute_int\endcsname\else -1\fi
  local repetition = \csname ulsbs@rep@attribute\endcsname
  local level_attribute = \number\csname c__ulsbs_music_note_level_attribute_int\endcsname
  local radius_attribute = \number\csname c__ulsbs_music_note_radius_attribute_int\endcsname
  local raise_attribute = \number\csname c__ulsbs_music_note_raise_attribute_int\endcsname
  local normal_attribute = \number\csname c__ulsbs_music_normal_raise_attribute_int\endcsname
  local high_attribute = \number\csname c__ulsbs_music_high_raise_attribute_int\endcsname
  local chord_a_attribute = \number\csname c__ulsbs_music_chord_a_attribute_int\endcsname
   local lyric_a_attribute = \number\csname c__ulsbs_music_lyric_a_attribute_int\endcsname
   local prep_attribute = \number\csname c__ulsbs_music_prep_attribute_int\endcsname
   local normal_height_attribute = \csname ulsbs@rep@heightattribute\endcsname
 local function check(ok, message)
   if not ok then texio.write_nl('MIDPOINT-FAIL:' .. midpoint_case .. ':' .. message) end
 end
 ulsbs_music.finish_verse = function(id)
   finish(id)
   if not midpoint_case then return end
   check(center_attribute >= 0, 'missing retained circle-center attribute')
    local lines, minimum, actual_chord = {}, nil, false
   for line in node.traverse_id(hlist, tex.box[id].list) do
     local data = (node.getproperty(line) or {}).ulsbs_music
     if data then
         local info = {top = 0, bars = {}, repetitions = {}, preps = {}, notes = {}, lanes = {}, chord = false,
          level = 0, refs = {}, data = data}
        local function reference(level, bottom, base)
          local old = info.refs[level]
          if not old or bottom + base > old.bottom + old.base then
            info.refs[level] = {bottom = bottom, base = base}
          end
        end
        local function chord_metric(n)
          local value = node.has_attribute(n, chord_a_attribute)
          if value then return value end
          if n.id == hlist or n.id == vlist then
            for child in node.traverse(n.list) do
              value = chord_metric(child)
              if value then return value end
            end
          end
        end
        local function raw_notes(list, baseline, stack)
         for n in node.traverse(list) do
           if n.id == hlist and (n.height > 0 or n.depth > 0) then
             local raised = baseline - n.shift
             local retained = node.has_attribute(n, row_attribute)
             if retained and retained > 0 then
               info.chord = true
                info.level = math.max(info.level, 1)
                 reference(1, raised, assert(chord_metric(n), 'chord capital A metric'))
             end
             local center = center_attribute >= 0 and node.has_attribute(n, center_attribute)
             if center then
               local local_center = math.floor((n.height - n.depth) / 2 + tex.sp('2pt') + .5)
               check(center == local_center, 'circle attribute includes tag or misses 2pt shift')
                local radius = assert(node.has_attribute(n, radius_attribute))
                local level = assert(node.has_attribute(n, level_attribute))
                info.level = math.max(info.level, level)
                local top, bottom = raised + local_center + radius, raised + local_center - radius
                local midpoint = (top + bottom) / 2
                local anchor = raised - assert(node.has_attribute(n, raise_attribute))
                table.insert(info.notes, {top = top, bottom = bottom, center = midpoint,
                  level = level, anchor = anchor, local_center = local_center, radius = radius,
                  normal = node.has_attribute(n, normal_attribute),
                  high = node.has_attribute(n, high_attribute),
                  chord_a = node.has_attribute(n, chord_a_attribute)})
                if level >= 2 then reference(level, bottom, 2 * radius) end
               info.lanes[raised] = true
               stack.lowest = math.min(stack.lowest, raised + n.height)
             else
               raw_notes(n.list, raised, stack)
             end
           end
         end
       end
       local function inspect(list, baseline)
         for n in node.traverse(list) do
           if n.id == rule then
              if node.has_attribute(n, repetition) then
                table.insert(info.repetitions, {box = n, baseline = baseline})
              end
           elseif n.id == hlist or n.id == vlist then
             local raised = baseline - n.shift
              if node.has_attribute(n, prep_attribute) then
                table.insert(info.preps, {box = n, baseline = baseline})
              elseif node.has_attribute(n, measure) == 1 then
               table.insert(info.bars, {box = n, baseline = raised})
             elseif node.has_attribute(n, annotation) then
               info.top = math.max(info.top, raised + n.height)
               local stack = {lowest = math.huge}
               if n.id == vlist then
                 for first in node.traverse_id(hlist, n.list) do
                   raw_notes(first.list, raised + n.height - first.height, stack)
                   break
                 end
               else
                 raw_notes(n.list, raised, stack)
               end
             elseif n.id == hlist then inspect(n.list, raised) end
           end
         end
       end
        inspect(line.list, 0)
        local function lyric_metric(list)
          for n in node.traverse(list) do
            local metric = node.has_attribute(n, lyric_a_attribute)
            if metric then return metric end
            if n.id == hlist or n.id == vlist then
              metric = lyric_metric(n.list)
              if metric then return metric end
            end
          end
        end
        reference(0, 0, assert(lyric_metric(line.list)))
        if not info.chord then
          for _, circle in ipairs(info.notes) do reference(1, circle.anchor, circle.chord_a) end
        end
        for level = 2, info.level do
          if not info.refs[level] then
            local nearest
            for _, circle in ipairs(info.notes) do
              if not nearest or math.abs(circle.level - level) < math.abs(nearest.level - level) then
                nearest = circle
              end
            end
            local raise = level == 2 and nearest.normal or nearest.high
            reference(level, nearest.anchor + raise + nearest.local_center - nearest.radius,
              2 * nearest.radius)
          end
        end
        check(data.level == info.level, 'logical N must be highest actual note level, not row count')
        for level, ref in pairs(info.refs) do
          local retained = data.references[level]
          check(retained and retained.bottom == ref.bottom and retained.base == ref.base,
            'independent retained-node reference L' .. level)
        end
        if info.level > 0 then
          if info.chord and not actual_chord then minimum = nil; actual_chord = true end
          if info.chord or not actual_chord then
            local ref = info.refs[1]
            if not minimum then minimum = {bottom = ref.bottom, base = ref.base}
            else minimum.bottom = math.min(minimum.bottom, ref.bottom)
              minimum.base = math.max(minimum.base, ref.base) end
          end
        end
        table.insert(lines, info)
     end
   end
   check(\string#lines == 2, 'expected annotation and plain continuation physical lines')
   for index, info in ipairs(lines) do
     local rows = info.chord and 1 or 0
     for _ in pairs(info.lanes) do rows = rows + 1 end
      if index == 1 then
        check(info.level == midpoint_level, 'fixture logical N ' .. info.level .. '/' .. midpoint_level)
       check(rows == midpoint_rows, 'actual visible row count ' .. rows .. '/' .. midpoint_rows)
       check(\string#info.notes == midpoint_notes,
         'retained original note count ' .. \string#info.notes .. '/' .. midpoint_notes)
     else
       check(rows == 0, 'plain continuation has no annotation rows')
     end
      local n = info.level
      if minimum and token.get_macro('ulsbs@bar@verseminimum') == '1' and n == 0 then n = 1 end
      local selected = tonumber(token.get_macro('ulsbs@measure@level@' .. n))
      local scale = tonumber(token.get_macro('ulsbs@measure@scale@' .. n))
      local ref = info.refs[selected] or (selected == 1 and minimum)
      local expected = math.max(0, math.floor(ref.bottom + ref.base * scale + .5))
     check(\string#info.bars == 2, 'expected two ordinary measure bars')
     for _, entry in ipairs(info.bars) do
       local actual = entry.baseline + entry.box.height
        check(math.abs(actual - expected) < 2,
          'line ' .. index .. ' bar ' .. actual .. '/' .. expected)
      end
      local repeat_level = tonumber(token.get_macro('ulsbs@repeat@level@' .. n))
      local repeat_scale = tonumber(token.get_macro('ulsbs@repeat@scale@' .. n))
      local repeat_ref = info.refs[repeat_level] or (repeat_level == 1 and minimum)
      local repeat_expected = math.max(0, math.floor(repeat_ref.bottom + repeat_ref.base * repeat_scale + .5))
      if index == 1 then check(\string#info.repetitions > 0, 'verse-left repeat geometry present') end
      for _, entry in ipairs(info.repetitions) do
        local normal = node.has_attribute(entry.box, normal_height_attribute)
        check(math.abs(normal + entry.baseline - repeat_expected) < 2,
          'repeat must use its independently configured reference/scale')
        check(entry.box.height >= normal, 'repeat authored overlap retained')
         check(entry.box.depth == math.floor(info.refs[0].base * tonumber(token.get_macro('ulsbs@repeat@bottomscale')) + .5),
          'repeat depth uses lyric capital A')
      end
      for _, entry in ipairs(info.preps) do
        local fallback = entry.baseline + node.has_attribute(entry.box, prep_attribute)
        local reference_bottom = info.level > 0 and info.refs[info.level].bottom or fallback
        check(entry.baseline - entry.box.shift == math.max(fallback, reference_bottom),
          'prep must follow highest actual reference bottom with authored 1ex minimum')
      end
     texio.write_nl('MIDPOINT-LINE:' .. midpoint_case .. ':' .. index .. ':' ..
       rows .. '/' .. \string#info.notes .. '/' .. expected)
   end
 end
}
"""
        cases = (
            ("empty", "", "", 0, 0),
            ("chord", "", r"\[C]", 1, 0),
            ("chordnote", "", r"\[<C>C]", 2, 1),
            ("chordtwonotes", "", r"\[<C;G>C]", 3, 2),
            ("pitchtwo", r"\chordsoff", r"\[<C;G>C]", 2, 2),
            ("pitchone", r"\chordsoff", r"\[<C>C]", 1, 1),
            ("same", r"\ulMelodySecondaryPosition{same}", r"\[<C;G>C]", 2, 2),
            ("restprimary", "", r"\[<_;G>C]", 2, 1),
            ("restsecondary", "", r"\[<C;_>C]", 2, 1),
            ("rests", "", r"\[<_;_>C]", 1, 0),
            ("hiddennotes", r"\notesoff", r"\[<C;G>C]", 1, 0),
            ("hiddenall", r"\notesoff\chordsoff", r"\[<C;G>C]", 0, 0),
            ("adjacent", "", r"\[<!C;G>]\[C]", 3, 2),
            ("distributed", "", r"\[<!C>]\ulMelodyPrimaryPosition{low}\[<G>C]", 3, 2),
            ("below", r"\ulMelodySecondaryPosition{below}", r"\[<C;G>C]", 3, 2),
            ("raised", "", r"\raisebox{3pt}{\hbox{|\[<C;G>C]Raised}}", 3, 2),
            ("tag", r"\makeatletter\renewcommand\ulsbs@mntag{\rule{1pt}{18pt}}\makeatother",
             r"\[<C;G>C]", 3, 2),
             ("custom", r"\makeatletter\renewcommand\ulsbs@mnsymbolstyle{\fontsize{11}{13}\selectfont}"
              r"\makeatother", r"\[<C;G>C]", 3, 2),
             ("highonly", r"\chordsoff", r"\[<_;G>]", 1, 1),
             ("lowonly", r"\ulMelodyPrimaryPosition{low}\chordsoff", r"\[<C>]", 1, 1),
             ("beatonly", r"\chordsoff\notesoff", r"\[<*>]", 0, 0),
             ("minimumoff", r"\ulUseVerseAnnotationMinimum{false}", r"\[<C;G>C]", 3, 2),
             ("baseline", r"\renewcommand\ulEveryVerse{\baselineskip=40pt}", r"\[<C;G>C]", 3, 2),
             ("nominal", r"\chordsoff"
              r"\renewcommand\ulMelodyNormalHeightFactor{2.7}", r"\[<_;G>]", 1, 1),
        )
        levels = dict(empty=0, chord=1, chordnote=2, chordtwonotes=3, pitchtwo=3,
                      pitchone=2, same=2, restprimary=3, restsecondary=2, rests=1,
                      hiddennotes=1, hiddenall=0, adjacent=3, distributed=2, below=2,
                      raised=3, tag=3, custom=3, highonly=3, lowonly=1, beatonly=0,
                      minimumoff=3, baseline=3, nominal=3)
        body = [r"\begin{ulSongs}{}\beginsong{Circle midpoint}[key={C}]"]
        for policy, selected, scale, repeat_scale in (
                ("default", None, None, None), ("lyric", 0, "0.5", "0.3"),
                ("chord", 1, "1.4", "0.9"), ("normal", 2, "0", "1.1"),
                ("high", 3, "1", "0.65")):
            for label, controls, annotation, rows, notes in cases:
                # Configure only levels that can select the requested reference.
                settings = "" if selected is None else "".join(
                    rf"\ulMeasureBarTop{{{n}}}{{{selected}}}{{{scale}}}"
                    rf"\ulRepeatBarTop{{{n}}}{{{selected}}}{{{repeat_scale}}}"
                    for n in range(selected, 4))
                bars = r"|" if label != "raised" else ""
                body.extend((rf"{{\MidpointCase{{{policy}{label}}}{{{rows}}}{{{notes}}}{{{levels[label]}}}"
                             + settings + controls, r"\beginverse*",
                             r"\beginrep\prep{3}\meter{}{}" + bars + annotation + r"Anchor |tail\hfil\break"
                             r"|Plain continuation |tail.\endrep", r"\endverse}"))
        body.extend((r"\directlua{midpoint_case = nil}", r"\endsong\end{ulSongs}"))
        results = []
        for layers in (False, True):
            with self.subTest(multikey=layers):
                source = (r"\def\ulPdfTranspositionLayers{" + str(layers).lower() + "}"
                          + helpers.document("\n".join(body), preamble))
                output = self.compile_source(source, label=f"midpoint-{layers}", passes=3)
                metrics = re.findall(r"MIDPOINT-LINE:(\w+):(\d+):(\d+)/(\d+)/(\d+(?:\.0)?)", output)
                self.assertEqual(len(metrics), len(cases) * 5 * 2 * 3)
                per_pass = len(cases) * 5 * 2
                self.assertEqual(metrics[:per_pass], metrics[per_pass:2 * per_pass])
                self.assertEqual(metrics[:per_pass], metrics[2 * per_pass:])
                targets = {(case, line): int(float(target))
                           for case, line, _, _, target in metrics[:per_pass]}
                for policy in ("default", "lyric", "chord", "normal", "high"):
                    for line in ("1", "2"):
                        self.assertEqual(targets[policy + "baseline", line],
                                         targets[policy + "chordtwonotes", line])
                self.assertNotEqual(targets["defaulthighonly", "1"],
                                    targets["defaultnominal", "1"])
                self.assertNotEqual(targets["defaultminimumoff", "2"],
                                    targets["defaultchordtwonotes", "2"])
                self.assertNotIn("Missing character:", output)
                self.assertEqual(re.findall(r"MIDPOINT-FAIL:([^\r\n]+)", output), [])
                results.append(metrics[:per_pass])
        if len(results) == 2:
            self.assertEqual(*results)

    def test_esta_em_voce_mixed_stanza_uses_chord_row_and_physical_ink_clearance(self):
        preamble = r"""
\ulShowChords{true}\ulShowNotes{true}\ulShowBeats{true}
\ulSongColumns{1}\ulSongPosition{0}
\typeout{CORPUS-REPEAT-DEPTH:\number\ulRepeatBarDepth}
\newcount\CorpusEffects
\def\CorpusEffect{\global\advance\CorpusEffects1 }
\ulDeclareLyricChar{\CorpusEffect}
\newcommand\CorpusCase[1]{\directlua{corpus_case = '#1'}}
\directlua{
 local finish = ulsbs_music.finish_verse
 local hlist, vlist, rule, glyph, glue, kern = node.id('hlist'), node.id('vlist'),
   node.id('rule'), node.id('glyph'), node.id('glue'), node.id('kern')
 local annotation = \number\csname c__ulsbs_chord_annotation_attribute_int\endcsname
 local measure = \number\csname c__ulsbs_music_measure_attribute_int\endcsname
 local repetition = \csname ulsbs@rep@attribute\endcsname
 ulsbs_music.finish_verse = function(id)
    finish(id)
    if not corpus_case then return end
    local y, previous_bottom, index = 0, nil, 0
    local minimum
    for line in node.traverse_id(hlist, tex.box[id].list) do
      local data = (node.getproperty(line) or {}).ulsbs_music
      if data and data.level > 0 and data.references[1] then
        local ref = data.references[1]
        if not minimum or ref.bottom < minimum.bottom then minimum = ref end
      end
    end
   for line in node.traverse(tex.box[id].list) do
     if line.id == glue then y = y + line.width
     elseif line.id == kern then y = y + line.kern
     elseif line.id == hlist or line.id == vlist or line.id == rule then
       y = y + line.height
       if (node.getproperty(line) or {}).ulsbs_music then
         index = index + 1
          local top, bottom, annotation_top, bar_top, repeat_top = 0, 0, 0, 0, 0
          local upper_top, upper_mid = 0, 0
          local function notes(list, raised)
            for n in node.traverse_id(hlist, list) do
              local baseline = raised - n.shift
              local center = node.has_attribute(n,
                \number\csname c__ulsbs_music_note_center_attribute_int\endcsname)
              if center then
                if baseline + n.height > upper_top then
                  upper_top, upper_mid = baseline + n.height, baseline + center
                end
              elseif not (n.width == 0 and n.height == 0 and n.depth == 0) then notes(n.list, baseline) end
            end
          end
         local function inspect(list, raised)
           for n in node.traverse(list) do
             if n.id == glyph or n.id == rule then
               if n.id == rule and node.has_attribute(n, repetition) then
                 repeat_top = math.max(repeat_top, raised + n.height)
               else
                 top = math.max(top, raised + n.height)
                 bottom = math.max(bottom, n.depth - raised)
               end
             elseif n.id == hlist or n.id == vlist then
               local baseline = raised - n.shift
               if node.has_attribute(n, measure) == 1 then
                 bar_top = math.max(bar_top, baseline + n.height)
                 top = math.max(top, baseline + n.height)
                 bottom = math.max(bottom, n.depth - baseline)
                elseif node.has_attribute(n, annotation) then
                 annotation_top = math.max(annotation_top, baseline + n.height)
                 top = math.max(top, baseline + n.height)
                  bottom = math.max(bottom, n.depth - baseline)
                  if n.id == vlist then
                    for row in node.traverse_id(hlist, n.list) do
                      notes(row.list, baseline + n.height - row.height)
                      break
                    end
                  else notes(n.list, baseline) end
               elseif n.id == hlist then inspect(n.list, baseline) end
             end
           end
         end
          inspect(line.list, 0)
          local data = node.getproperty(line).ulsbs_music
           local enabled=token.get_macro('ulsbs@bar@verseminimum')=='1'
           local level = data.level == 0 and enabled and minimum and 1 or data.level
           local function selected(kind)
             local prefix='ulsbs@'..kind..'@'
             local reference=tonumber(token.get_macro(prefix..'level@'..level))
             local scale=tonumber(token.get_macro(prefix..'scale@'..level))
             local ref=data.references[reference] or (reference==1 and minimum)
             assert(ref,'configured reference for corpus probe')
             return math.floor(ref.bottom+ref.base*scale+.5)
           end
           local expected_measure, expected_repeat = selected('measure'), selected('repeat')
          local gap = previous_bottom and y - top - previous_bottom or -1
         texio.write_nl('CORPUS-INK:' .. corpus_case .. ':' .. index .. ':' ..
           annotation_top .. '/' .. bar_top .. '/' .. repeat_top .. '/' ..
             top .. '/' .. bottom .. '/' .. gap .. '/' .. upper_mid .. '/' ..
             expected_measure .. '/' .. expected_repeat .. '/' ..
              math.floor(data.references[0].base * tonumber(token.get_macro('ulsbs@repeat@bottomscale')) + .5))
         previous_bottom = y + bottom
       end
       y = y + line.depth
     end
   end
 end
}
"""
        # Keep the actual empty chord groups, excluded pitch anchors, named
        # memorize blocks and glued repeat boundary from the reported song.
        first = r"""|\[Dm]{} |\[^<A>]A for\[^<C>]ça \[^<G>]do |\[<A>Am]mar | |\[G]{} |\[^<G>]po\[^<F>]de \[^<E>]most|\[<C>F]rar | \e"""
        second = r"""|\[Dm]{} Abre os |olhos para |\[Am]ver | |\[G]{} o mis|tério reve|\[F]lar | \e"""
        body = r"""
\begin{ulSongs}{}
\beginsong{Está em Você}[key={Em}]
\transpose{-5}\capo{3}
\newchords{chords_estaemvoce_a}\newchords{chords_estaemvoce_b}
\CorpusCase{mixed}
\beginverse\memorize[chords_estaemvoce_a]
FIRST
SECOND
\endverse\glueverses
\CorpusCase{glued}
\beginverse\memorize[chords_estaemvoce_b]
\beginrep
|\[C]{} Es|tá em vo|\[F]cê | |\[C]{} |todo po|\[F]der | \e
De a|\[G]mar | a|\[Am]mar | \e
\endrep
\endverse
\CorpusCase{control}
\beginverse
SECOND
\endverse
\CorpusCase{descenders}
\beginverse*
|\[C]{} gypqj\CorpusEffect | \e
\beginrep
|\[<C;G>C]{} gypqj | \e
|\[F]{} gypqj | \e
\endrep
\endverse
\directlua{corpus_case = nil}
\endsong\end{ulSongs}
\typeout{CORPUS-EFFECTS:\the\CorpusEffects}
""".replace("FIRST", first).replace("SECOND", second)
        results = []
        for layers in (False, True):
            with self.subTest(multikey=layers):
                source = (r"\def\ulPdfTranspositionLayers{" + str(layers).lower() + "}"
                          + helpers.document(body, preamble))
                output = self.compile_source(source, label=f"corpus-{layers}", passes=3)
                rows = [(case, int(number), tuple(map(int, values)))
                        for case, number, *values in re.findall(
                              r"CORPUS-INK:(\w+):(\d+):" + r"/".join([r"(-?\d+)"] * 10), output)]
                self.assertEqual(len(rows), 8 * 3)
                self.assertEqual(re.findall(r"CORPUS-EFFECTS:(\d+)", output), ["1"] * 3)
                self.assertEqual(len(re.findall(r"CORPUS-REPEAT-DEPTH:(\d+)", output)), 3)
                metrics = {(case, number): values for case, number, values in rows}
                results.append(metrics)
                self.assertEqual(rows[:8], rows[8:16])
                self.assertEqual(rows[:8], rows[16:])
                mixed_first, mixed_second = metrics["mixed", 1], metrics["mixed", 2]
                control = metrics["control", 1]
                self.assertGreater(mixed_first[0], control[0], "fixture must contain a real melody row")
                self.assertEqual(mixed_second[1], control[1],
                                 "pitch-only anchors must not inflate the stanza's chord-row minimum")
                self.assertNotEqual(mixed_second[1], mixed_first[0],
                                    "chord-only second line must not inherit the first melody top")
                for case in ("mixed", "glued", "control"):
                    for (name, number), values in metrics.items():
                        if name == case:
                            self.assertAlmostEqual(values[1], values[7], delta=2,
                                                   msg=f"ordinary bar policy: {case}:{number}")
                self.assertAlmostEqual(metrics["glued", 1][2], metrics["glued", 1][8], delta=2,
                                       msg="verse-left repeat must use its independent policy")
                tall = metrics["descenders", 2]
                self.assertAlmostEqual(tall[1], tall[7], delta=2)
                self.assertAlmostEqual(tall[2], tall[8], delta=2)
                self.assertGreater(metrics["descenders", 1][4], 0,
                                   "preceding lyric must have real descender ink")
                for case, number, values in rows:
                    if number > 1:
                        self.assertGreaterEqual(values[5], 65536 - 2,
                                                f"physical ink gap below 1pt: {case}:{number}")
                self.assertNotIn("Missing character:", output)
        if len(results) == 2:
            self.assertEqual(*results)

    def test_configured_ink_gap_and_unterminated_scalar_baseline(self):
        preamble = r"""
\ulSongColumns{1}\ulSongPosition{0}
\newbox\SpacingProbe
\newcommand\CheckSpacingProbe{\directlua{
 local hlist, vlist, rule, glue, kern = node.id('hlist'), node.id('vlist'), node.id('rule'), node.id('glue'), node.id('kern')
 local y, previous, count = 0, nil, 0
 for n in node.traverse(tex.box[\number\SpacingProbe].list) do
   if n.id==hlist or n.id==vlist or n.id==rule then
     local data=(node.getproperty(n) or {}).ulsbs_music
     if data then
       count=count+1
       if spacing_nominal then
         local expected=math.floor(data.references[0].base*spacing_nominal+.5)
         assert(math.abs(data.baseline.width-expected)<2,'last paragraph must retain A-scaled nominal baseline')
       elseif previous then
         assert(math.abs(y-previous-tex.sp(spacing_gap..'pt'))<2,
           'configured ink gap must survive physical lines and glued verses')
       end
       previous=y+n.height+n.depth
     end
     y=y+n.height+n.depth
   elseif n.id==glue then y=y+n.width
   elseif n.id==kern then y=y+n.kern end
 end
 assert(count==4,'all physical source paragraphs audited')
 texio.write_nl('SCALAR-SPACING-PASS')
}}
"""
        body = r"""\begin{ulSongs}{}\beginsong{Spacing policy}[key={C}]
{\ulVerseMinimumGap{1pt}\ulVerseBaseline{0}{0}{0}
\directlua{spacing_gap=1;spacing_nominal=nil}
\setbox\SpacingProbe=\vbox{
\beginverse*\meter{}{}
|\[<C>C]gyp.
|\[C]gyp.
\endverse\glueverses\beginverse*
|\[C]gyp.
|gyp.
\endverse}
\CheckSpacingProbe\box\SpacingProbe}
{\ulVerseMinimumGap{4pt}\ulVerseBaseline{0}{0}{0}
\directlua{spacing_gap=4;spacing_nominal=nil}
\setbox\SpacingProbe=\vbox{
\beginverse*\meter{}{}
|\[<C>C]gyp.
|\[C]gyp.
\endverse\glueverses\beginverse*
|\[C]gyp.
|gyp.
\endverse}
\CheckSpacingProbe\box\SpacingProbe}
{\ulVerseMinimumGap{1pt}\ulVerseBaseline{6}{0}{0}
\directlua{spacing_nominal=6}
\setbox\SpacingProbe=\vbox{
\beginverse*\meter{}{}
|\[C]gyp.
|gyp.\endverse\glueverses\beginverse*
|\[C]gyp.
|gyp.\endverse}
\CheckSpacingProbe\box\SpacingProbe}
\endsong\end{ulSongs}"""
        for layers in (False, True):
            output = self.compile_source(r"\def\ulPdfTranspositionLayers{" + str(layers).lower() + "}"
                                         + helpers.document(body, preamble),
                                         label=f"spacing-gap-{layers}", passes=3)
            self.assertEqual(output.count("SCALAR-SPACING-PASS"), 9)

    def test_empty_chord_and_adjacent_melody_compile(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Cora\c{c}\~ao, luz e ora\c{c}\~ao}[key={D&},by={Jos\'e da Silva}]
\beginverse+
\[<* C D;E F @ .3em>Am]MelodyAnchor \[<A _ C;E _ G>]rest slots.
\[<!C>]ZeroAdvanceAnchor \[</>Am]unpitched \[<* @ 1em>]beat only.
\[<C>]\[<D>]AdjacentMelodyAnchor
\endverse
\endsong
\end{ulSongs}
""")

    def test_accidental_macros_groups_and_slash_bass_under_source_transposition(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Tokens}[key={E}]
\transpose{1}
\beginverse*
\[F\shrp{}m/C\shrp{}]MacroAnchor \[B\flt{}]FlatAnchor
\[F#m/C#]LiteralAnchor \[{C}m]GroupedAnchor
\endverse
\endsong
\end{ulSongs}
""")

    def test_existing_accidental_context_fixture(self):
        output, pdf = compile_fixture("accidental-contexts", multikey=False)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertNotIn("Missing character:", output)

    def test_plus_modifier_scopes_repeat_prefix_raise(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Raised repeat}
\beginverse*+
\beginrep\prep{4}
\[<C>C]RaisedAnchor
\endrep
\endverse
\beginverse*
\beginrep\prep{4}
\[G]OrdinaryAnchor
\endrep
\endverse
\endsong\end{ulSongs}
""")

    def test_missing_key_fallback_keeps_ambient_accidental_preference(self):
        for label, preference in (("default", ""), ("sharps", r"\prefersharps")):
            with self.subTest(preference=label):
                source = helpers.document(r"""
\begin{ulSongs}{}
\beginsong{Fallback}
\transpose{1}
\beginverse*
\[C]FirstFallbackAnchor \[F]SecondFallbackAnchor \[G]ThirdFallbackAnchor
\endverse
\endsong\end{ulSongs}
""", preference)
                self.compile_source(source, label=label)
                text = self.pdf_text()
                for anchor in ("FirstFallbackAnchor", "SecondFallbackAnchor", "ThirdFallbackAnchor"):
                    self.assertIn(anchor, text)


if __name__ == "__main__":
    unittest.main()
