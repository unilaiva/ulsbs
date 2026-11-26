# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Stanza parsing, independent of song-lifecycle test discovery."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import unittest
import xml.etree.ElementTree as ET

import test_song_lifecycle as song_helpers
from test_tex_integration import ROOT


def document(body: str, preamble: str = "", *, variant: str = "default") -> str:
    return song_helpers.document(body, preamble, variant=variant)


class VerseTests(unittest.TestCase):
    # Compose the established compiler harness without inheriting its 22 tests.
    compile_source = song_helpers.SongLifecycleTests.compile_source
    pdf_text = song_helpers.SongLifecycleTests.pdf_text
    setUp = song_helpers.SongLifecycleTests.setUp

    @classmethod
    def setUpClass(cls):
        song_helpers.SongLifecycleTests.setUpClass.__func__(cls)
        cls.diagnostics = Path(os.environ.get(
            "ULSBS_VERSE_DIAGNOSTICS", ROOT / "build/verse"))
        cls.diagnostics.mkdir(parents=True, exist_ok=True)

    def words(self):
        result = subprocess.run(
            ["pdftotext", "-bbox", str(self.book / "book.pdf"), "-"],
            check=True, stdout=subprocess.PIPE, text=True)
        root = ET.fromstring(result.stdout)
        return [{"text": item.text, **{key: float(value) for key, value in item.attrib.items()}}
                for item in root.iter() if item.tag.endswith("}word")]

    def word(self, text):
        matches = [word for word in self.words() if word["text"] == text]
        self.assertEqual(len(matches), 1, (text, matches))
        return matches[0]

    def test_prep_uses_actual_highest_reference_and_plus_has_no_spacing_effect(self):
        preamble = r"""
\ulSongColumns{1}\ulSongPosition{0}
\ulRepeatBarBottomScale{0.1}
\ulMeasureBarTop{1}{0}{0.5}
\directlua{
 local finish = ulsbs_music.finish_verse
 local hlist = node.id('hlist')
 local prep = \number\csname c__ulsbs_music_prep_attribute_int\endcsname
 ulsbs_music.finish_verse = function(id)
   finish(id)
   local box = tex.box[id]
   local count = 0
   for line in node.traverse_id(hlist, box.list) do
     local data = (node.getproperty(line) or {}).ulsbs_music
     if data then
       local info = data.geometry
       assert(info.level == prep_level, 'fixture actual logical level')
       for _, marker in ipairs(info.preps) do
         count = count + 1
         local fallback = marker.baseline + node.has_attribute(marker.box, prep)
         local expected = info.level > 0 and math.max(fallback, info.refs[info.level].bottom) or fallback
         assert(marker.baseline - marker.box.shift == expected, 'prep follows actual highest reference')
         if info.level == 3 then
           assert(expected > info.refs[2].bottom, 'prep does not follow the lower selected bar reference')
         end
       end
       for _, repeatbar in ipairs(info.repetitions) do
         assert(repeatbar.box.depth == math.floor(info.refs[0].base * .1 + .5),
           'repeat low hang follows lyric A, not a fixed dimension')
       end
     end
   end
   assert(count == 1, 'one retained prep marker')
   texio.write_nl('PREP-GEOMETRY:' .. prep_level .. ':' .. box.height .. '/' .. box.depth)
 end
}
"""
        body = [r"\begin{ulSongs}{}\beginsong{Actual prep level}[key={C}]"]
        for level, annotation in ((0, ""), (1, r"\[C]"), (2, r"\[<C>C]"), (3, r"\[<C;G>C]")):
            for modifier in ("", "+"):
                body.extend((rf"\directlua{{prep_level={level}}}", r"\beginverse*" + modifier,
                             r"\meter{}{}\beginrep\prep{3}|" + annotation + "Anchor.",
                             r"\endrep\endverse"))
        body.append(r"\endsong\end{ulSongs}")
        editions = []
        for layers in (False, True):
            output = self.compile_source(r"\def\ulPdfTranspositionLayers{" + str(layers).lower() + "}"
                                         + document("\n".join(body), preamble),
                                         label=f"prep-policy-{layers}", passes=3)
            rows = re.findall(r"PREP-GEOMETRY:(\d+):(\d+)/(\d+)", output)
            self.assertEqual(len(rows), 24)
            for index in range(0, len(rows), 2):
                self.assertEqual(rows[index], rows[index + 1], 'plus must not alter stanza geometry')
            editions.append(rows)
        self.assertEqual(*editions)

    def test_bar_geometry_overflow_fails_at_use_with_clear_diagnostic(self):
        body = r"""\begin{ulSongs}{}\beginsong{Overflow}[key={C}]
\beginverse*\meter{}{}|Word.
\endverse\endsong\end{ulSongs}"""
        with self.assertRaisesRegex(AssertionError, "configured bar geometry exceeds the TeX dimension range"):
            self.compile_source(document(body, r"\ulMeasureBarTop{0}{0}{1e308}"),
                                label="overflow-at-use", passes=1)

    def test_bar_configuration_defaults_and_local_scope(self):
        settings = [
            *[f"ulsbs@{kind}@{field}@{n}"
               for kind in ("measure", "repeat")
               for n in range(4)
               for field in ("level", "scale")],
            "ulsbs@bar@verseminimum", "ulsbs@repeat@bottomscale", "ulsbs@repeat@minimumgap",
        ]
        probe = r"""
\directlua{
 for _,kind in ipairs({'measure','repeat'}) do
  for n=0,3 do
   local level = tonumber(token.get_macro('ulsbs@'..kind..'@level@'..n))
   local scale = tonumber(token.get_macro('ulsbs@'..kind..'@scale@'..n))
   assert(level and level == math.floor(level) and level >= 0 and level <= n)
   assert(scale and scale >= 0 and scale < math.huge, 'finite nonnegative bar scale')
  end
 end
 local minimum = token.get_macro('ulsbs@bar@verseminimum')
 assert(minimum == '0' or minimum == '1')
 for _,field in ipairs({'bottomscale','minimumgap'}) do
  local value = tonumber(token.get_macro('ulsbs@repeat@'..field))
  assert(value and value >= 0 and value < math.huge)
  if field == 'minimumgap' then assert(value == math.floor(value) and value <= 1073741823) end
 end
}
\newcommand\BarSetting[2]{\directlua{
 local raw = token.get_macro('#1')
 assert(raw == '#2', '#1 expected #2, got ' .. tostring(raw))
 texio.write_nl('BAR-SETTING:#1=' .. raw)
}}
"""
        probe += "\n".join(r"\expandafter\edef\csname Saved@" + name
                            + r"\endcsname{\csname " + name + r"\endcsname}"
                            for name in settings)
        checks = "\n".join(r"\BarSetting{" + name + r"}{\csname Saved@" + name + r"\endcsname}"
                           for name in settings)
        overrides = []
        for kind in ("measure", "repeat"):
            command = "Measure" if kind == "measure" else "Repeat"
            for n in range(4):
                overrides.extend((rf"\ul{command}BarTop{{{n}}}{{0}}{{+2.50e-1}}",
                                  rf"\BarSetting{{ulsbs@{kind}@level@{n}}}{{0}}",
                                  rf"\BarSetting{{ulsbs@{kind}@scale@{n}}}{{0.25}}"))
        output = self.compile_source(document(
            checks + "\n{\n" + "\n".join(overrides) + r"""
\ulUseVerseAnnotationMinimum{off}\BarSetting{ulsbs@bar@verseminimum}{0}
\ulRepeatBarBottomScale{0}\BarSetting{ulsbs@repeat@bottomscale}{0}
\ulRepeatBarMinimumGap{0sp}\BarSetting{ulsbs@repeat@minimumgap}{0}
}
""" + checks + r"\null", probe), label="bar-api-scope")
        self.assertEqual(output.count("BAR-SETTING:"), 3 * len(settings))

    def test_scalar_verse_spacing_defaults_resolved_glue_and_local_restoration(self):
        preamble = r"""
\newcommand\VerseSpacingProbe[7]{\directlua{
 local baseline = tex.skip['l__ulsbs_verse_nominal_skip']
 local separation = tex.skip['ulsbs@verse@separation']
 local height = #1
 for _, row in ipairs({{'baseline',baseline,#2,#3,#4}, {'separation',separation,#5,#6,#7}}) do
   for i,field in ipairs({'natural','stretch','shrink'}) do
     assert(tonumber(token.get_macro('ulsbs@verse@'..row[1]..'@'..field)) == row[i+2])
   end
   for i,field in ipairs({'width','stretch','shrink'}) do
     assert(math.abs(row[2][field] - math.floor(height * row[i+2] + .5)) <= 1,
       row[1]..' '..field..' resolves against lyric A')
   end
    assert(row[2].stretch_order == 0 and row[2].shrink_order == 0)
 end
}}
\begingroup\ulLyricFontStyle\ulVerseFont
\xdef\DefaultVerseA{\number\fontcharht\font`A}\endgroup
\ExplSyntaxOn
\token_if_skip_register:NT \ulVerseSpacingScale {\errmessage{Getter must not be assignable}}
\ExplSyntaxOff
\edef\BaselineGetter{\ulVerseSpacingScale{baseline}{natural}}
\edef\SeparationGetter{\ulVerseSpacingScale{separation}{shrink}}
\edef\SavedBaselineNatural{\ulVerseSpacingScale{baseline}{natural}}
\edef\SavedBaselineStretch{\ulVerseSpacingScale{baseline}{stretch}}
\edef\SavedBaselineShrink{\ulVerseSpacingScale{baseline}{shrink}}
\edef\SavedSeparationNatural{\ulVerseSpacingScale{separation}{natural}}
\edef\SavedSeparationStretch{\ulVerseSpacingScale{separation}{stretch}}
\edef\SavedSeparationShrink{\ulVerseSpacingScale{separation}{shrink}}
\expandafter\edef\csname SavedMinimumGap\endcsname{\csname ulsbs@verse@minimumgap\endcsname}
\directlua{
 assert(tonumber('\BaselineGetter') == tonumber(token.get_macro('ulsbs@verse@baseline@natural')))
 assert(tonumber('\SeparationGetter') == tonumber(token.get_macro('ulsbs@verse@separation@shrink')))
 for _,kind in ipairs({'baseline','separation'}) do
  for _,field in ipairs({'natural','stretch','shrink'}) do
   local value = tonumber(token.get_macro('ulsbs@verse@'..kind..'@'..field))
   assert(value and value >= 0 and value < math.huge)
  end
 end
 local gap = tonumber('\SavedMinimumGap')
 assert(gap and gap >= 0 and gap <= 1073741823 and gap == math.floor(gap))
}
"""
        output = self.compile_source(document(r"""
\VerseSpacingProbe{\DefaultVerseA}{\SavedBaselineNatural}{\SavedBaselineStretch}{\SavedBaselineShrink}
 {\SavedSeparationNatural}{\SavedSeparationStretch}{\SavedSeparationShrink}
\directlua{assert(token.get_macro('ulsbs@verse@minimumgap') == '\SavedMinimumGap')}
{
\ulVerseBaseline{+1.25e0}{.5}{.125}\ulVerseSeparation{2}{.25}{.75}
\ulVerseMinimumGap{.5pt}
\VerseSpacingProbe{\DefaultVerseA}{1.25}{.5}{.125}{2}{.25}{.75}
\directlua{assert(token.get_macro('ulsbs@verse@minimumgap') == '32768')}
}
\VerseSpacingProbe{\DefaultVerseA}{\SavedBaselineNatural}{\SavedBaselineStretch}{\SavedBaselineShrink}
 {\SavedSeparationNatural}{\SavedSeparationStretch}{\SavedSeparationShrink}
\directlua{assert(token.get_macro('ulsbs@verse@minimumgap') == '\SavedMinimumGap')}
\ulVerseMinimumGap{1pc}
\directlua{assert(token.get_macro('ulsbs@verse@minimumgap') == '786432')}
\ulVerseMinimumGap{1073741823sp}
\directlua{assert(token.get_macro('ulsbs@verse@minimumgap') == '1073741823')}
\ulVerseMinimumGap{0}
\directlua{assert(token.get_macro('ulsbs@verse@minimumgap') == '0')}
\typeout{VERSE-API-SCOPE-PASS}\null
""", preamble), label="verse-api-scope")
        self.assertIn("VERSE-API-SCOPE-PASS", output)

    def test_baseline_to_top_gap_and_ink_gap_control_distinct_floors(self):
        preamble = r"""
\ulSongColumns{1}\ulSongPosition{0}
\ulVerseBaselineToTopGap{3pt}\ulVerseMinimumGap{1pt}
\directlua{
  local finish = ulsbs_music.finish_verse
  local hlist, glue = node.id('hlist'), node.id('glue')
  local glue_types = node.subtypes('glue')
  ulsbs_music.finish_verse = function(id)
    finish(id)
    local upper, gap, checked
    for n in node.traverse(tex.box[id].list) do
      if n.id == glue and (glue_types[n.subtype] == 'baselineskip' or glue_types[n.subtype] == 'lineskip') then
        gap = n
      elseif n.id == hlist then
        local data = (node.getproperty(n) or {}).ulsbs_music
        if data then
          if upper then
            local depth = tex.sp(expected_depth..'pt')
            local floor = math.max(tex.sp('1pt'), tex.sp(expected_topgap..'pt')-depth)
            assert(upper.depth == depth, 'fixture upper depth')
            assert(data.level == expected_level, 'fixture lower annotation level')
            local natural = math.max(floor, data.baseline.width-depth-n.height)
            assert(gap and gap.width == natural and glue_types[gap.subtype] == 'baselineskip', 'natural line glue')
            assert(gap.stretch == data.baseline.stretch, 'preserve baseline stretch')
            assert(gap.shrink == math.min(data.baseline.shrink, natural-floor), 'shrink respects both floors')
            assert(upper.depth+gap.width == tex.sp(expected_clearance..'pt') or expected_case == 'nominal',
              'baseline-to-top clearance')
            if expected_case == 'nominal' then
              assert(gap.width+depth+n.height == data.baseline.width and gap.shrink > 0,
                'nominal baseline has room to shrink')
            end
            checked = true
          end
          upper = n
        end
      end
    end
    assert(checked, 'two retained lyric lines')
    texio.write_nl('VERSE-TOP-GAP-PASS')
  end
}
"""
        body = r"""\begin{ulSongs}{}\beginsong{Baseline clearance}[key={C}]
\directlua{expected_depth=0;expected_topgap=3;expected_level=1;expected_clearance=3}
\beginverse*
AAA
\[C]AAA
\endverse
\directlua{expected_depth=2}
\beginverse*
AAA\rule[-2pt]{1pt}{2pt}
\[C]AAA
\endverse
\directlua{expected_depth=4;expected_clearance=5}
\beginverse*
AAA\rule[-4pt]{1pt}{4pt}
\[C]AAA
\endverse
{\ulVerseBaselineToTopGap{5pt}\ulVerseBaseline{1.618034}{.25}{.5}
\directlua{expected_depth=0;expected_topgap=5;expected_clearance=5}
\beginverse*
AAA
\[C]AAA\endverse}
{\ulVerseBaselineToTopGap{0pt}\ulVerseBaseline{0}{0}{0}
\directlua{expected_topgap=0;expected_clearance=1}
\beginverse*
AAA
\[C]AAA\endverse}
\directlua{expected_topgap=3;expected_clearance=3}
\beginverse*
AAA
\[C]AAA\endverse
{\ulVerseBaseline{1.618034}{.25}{.5}
\directlua{expected_level=0;expected_case='nominal'}
\beginverse*
AAA
AAA\endverse}
\endsong\end{ulSongs}"""
        output = self.compile_source(document(body, preamble), label="baseline-to-top-gap")
        self.assertEqual(output.count("VERSE-TOP-GAP-PASS"), 7)

    def test_scalar_verse_spacing_calltime_font_and_relative_getter_expressions(self):
        preamble = r"""
\renewcommand\ulLyricFont{\sffamily\fontsize{19}{23}\selectfont}
\renewcommand\ulVerseFont{\rmfamily\bfseries\fontsize{16}{20}\selectfont}
\begingroup\ulLyricFontStyle\ulVerseFont
\xdef\ConfiguredVerseA{\number\fontcharht\font`A}
\xdef\ConfiguredVerseEx{\number\dimexpr.2ex\relax}\endgroup
\directlua{verse_scale_expansions=0}
\newcommand\CountedVerseScale[1]{\directlua{
 verse_scale_expansions=verse_scale_expansions+1
 assert(\number\fontcharht\font`A == \ConfiguredVerseA, 'argument expands in selected lyric font')
 tex.sprint('#1')
}}
\ulVerseBaseline{\CountedVerseScale{2}}{\CountedVerseScale{.5}}{\CountedVerseScale{.25}}
\ulVerseSeparation{3}{.75}{.125}
\newcount\VerseNotifications
\newcount\VerseFontSelections
\newcommand\RelativeVerseBaseline{\fpeval{\ulVerseSpacingScale{baseline}{natural}
  +\number\dimexpr1pt\relax/\number\fontcharht\font`A}}
"""
        output = self.compile_source(document(r"""
\directlua{
 local a = \ConfiguredVerseA;
 assert(verse_scale_expansions==3, 'each argument expands exactly once')
 local b,s = tex.skip['l__ulsbs_verse_nominal_skip'],tex.skip['ulsbs@verse@separation']
 assert(b.width == a*2 and s.width == a*3, 'configured font, not ambient preamble font')
 assert(math.abs(b.stretch-a*.5)<=1 and math.abs(b.shrink-a*.25)<=1)
 assert(math.abs(s.stretch-a*.75)<=1 and math.abs(s.shrink-a*.125)<=1)
 verse_original_width=b.width
 verse_ambient_font=font.current()
}
\ulVerseBaseline{\RelativeVerseBaseline}
 {\ulVerseSpacingScale{baseline}{stretch}}{\ulVerseSpacingScale{baseline}{shrink}}
\ulVerseSeparation{\fpeval{\ulVerseSpacingScale{separation}{natural}
 -\number\dimexpr.2ex\relax/\number\fontcharht\font`A}}
 {\ulVerseSpacingScale{separation}{stretch}}{\ulVerseSpacingScale{separation}{shrink}}
\directlua{
 local a=\ConfiguredVerseA
 local b,s=tex.skip['l__ulsbs_verse_nominal_skip'],tex.skip['ulsbs@verse@separation']
 assert(math.abs(b.width-verse_original_width-65536)<=1, 'relative 1pt uses selected lyric A')
 assert(math.abs(s.width-a*3+\ConfiguredVerseEx)<=1, 'relative ex uses selected lyric font')
 assert(math.abs(b.stretch-a*.5)<=1 and math.abs(b.shrink-a*.25)<=1)
 assert(math.abs(s.stretch-a*.75)<=1 and math.abs(s.shrink-a*.125)<=1)
 assert(font.current()==verse_ambient_font, 'setter must not leak its font')
 verse_relative_width=b.width
}
\renewcommand\ulVerseFont{\ttfamily\fontsize{9}{11}\selectfont}
\directlua{assert(tex.skip['l__ulsbs_verse_nominal_skip'].width == verse_relative_width,
 'font changes alone do not rescale configured skips')}
\ExplSyntaxOn
\__ulsbs_verse_baseline:
\ExplSyntaxOff
\directlua{
 local b=tex.skip.baselineskip
 assert(b.width == verse_relative_width, 'baseline consumes only configured nominal skip')
 assert(math.abs(b.stretch-\ConfiguredVerseA*.5)<=1)
 assert(math.abs(b.shrink-\ConfiguredVerseA*.25)<=1)
}
{
\ExplSyntaxOn
\cs_set_protected:Npn \__ulsbs_music_context: {\global\advance\VerseNotifications1}
\ExplSyntaxOff
\renewcommand\ulVerseFont{\global\advance\VerseFontSelections1\ttfamily\fontsize{9}{11}\selectfont}
\ulVerseBaseline{1.5}{0}{0}\ulVerseSeparation{2}{0}{0}\ulVerseMinimumGap{0sp}
\ulVerseBaseline{\RelativeVerseBaseline}
 {\ulVerseSpacingScale{baseline}{stretch}}{\ulVerseSpacingScale{baseline}{shrink}}
\ifnum\VerseFontSelections=3\else\errmessage{Each scalar setter must select its font once}\fi
\begingroup\ulLyricFontStyle\ulVerseFont
\directlua{assert(math.abs(tex.skip['l__ulsbs_verse_nominal_skip'].width -
 math.floor(\number\fontcharht\font`A*1.5+.5)-65536)<=1,
 'relative expression also selects the new smaller font')}
\endgroup
}
\ifnum\VerseNotifications=4\else\errmessage{Wrong verse context notification count}\fi
\directlua{assert(tex.skip['l__ulsbs_verse_nominal_skip'].width==verse_relative_width,
 'relative configuration restores locally')}
\typeout{VERSE-API-RELATIVE-PASS}\null
""", preamble), label="verse-api-relative")
        self.assertIn("VERSE-API-RELATIVE-PASS", output)

    def test_scalar_verse_spacing_validation_is_atomic_including_resolved_overflow(self):
        invalid = []
        for command in ("ulVerseBaseline", "ulVerseSeparation"):
            for field in range(3):
                for value in ("-1", "nan", "inf", "1e309", "1pt", "", "1e308"):
                    values = ["2", ".5", ".25"]
                    values[field] = value
                    invalid.append("\\" + command + "".join("{" + item + "}" for item in values))
        for command in ("ulVerseMinimumGap", "ulVerseBaselineToTopGap"):
            invalid.extend("\\" + command + "{" + value + "}"
                           for value in ("-1pt", "2", "1mu", "nan", "20000pt", "1073741824sp", "1e2pt", ""))
        preamble = r"""
\ulVerseBaseline{2}{.5}{.25}\ulVerseSeparation{3}{.75}{.125}
\newcount\VerseErrors
\let\OriginalVersePackageError\PackageError
\renewcommand\PackageError[3]{\advance\VerseErrors1\typeout{VERSE-REJECT:#1:#2}}
\directlua{
 verse_config = {}
 for _,kind in ipairs({'baseline','separation'}) do
  for _,field in ipairs({'natural','stretch','shrink'}) do
   local name='ulsbs@verse@'..kind..'@'..field
   verse_config[name]=token.get_macro(name)
  end
 end
  verse_config['ulsbs@verse@minimumgap']=token.get_macro('ulsbs@verse@minimumgap')
  verse_config['ulsbs@verse@baselinetotopgap']=token.get_macro('ulsbs@verse@baselinetotopgap')
 verse_skips={}
 for _,name in ipairs({'l__ulsbs_verse_nominal_skip','ulsbs@verse@separation'}) do
  local s=tex.skip[name]
  verse_skips[name]={s.width,s.stretch,s.shrink}
 end
}
\newcommand\CheckVerseUnchanged{\directlua{
 for name,value in pairs(verse_config) do assert(token.get_macro(name)==value, name) end
 for name,values in pairs(verse_skips) do
  local s=tex.skip[name]
  assert(s.width==values[1] and s.stretch==values[2] and s.shrink==values[3],name)
 end
}}
"""
        body = "\n".join(command + r"\CheckVerseUnchanged" for command in invalid)
        body += r"""
\let\PackageError\OriginalVersePackageError
\typeout{VERSE-ERROR-COUNT:\the\VerseErrors}\null
"""
        output = self.compile_source(document(body, preamble), label="verse-api-validation")
        self.assertIn(f"VERSE-ERROR-COUNT:{len(invalid)}", output)
        self.assertEqual(output.count("VERSE-REJECT:ulsbs:"), len(invalid))
        self.assertNotIn("Dimension too large", output)
        for kind, field in (("unknown", "natural"), ("baseline", "unknown")):
            with self.subTest(kind=kind, field=field):
                self.compile_source(document(r"\null", r"\edef\InvalidSpacingGetter{"
                                             + rf"\ulVerseSpacingScale{{{kind}}}{{{field}}}" + "}"),
                                    label=f"verse-api-getter-error-{kind}-{field}",
                                    failure="Invalid verse spacing key")

    def test_scalar_verse_spacing_canonical_presets_and_late_author_wins(self):
        for variant in ("lyric", "bassclef"):
            with self.subTest(variant=variant):
                source = (rf"\def\ulBuildVariant{{{variant}}}"
                          + document(r"""
\begingroup\ulLyricFontStyle\ulVerseFont
\directlua{
 local a = \number\fontcharht\font`A;
 for _,kind in ipairs({'baseline','separation'}) do
  local skip = tex.skip[kind == 'baseline' and 'l__ulsbs_verse_nominal_skip' or 'ulsbs@verse@separation']
  for i,field in ipairs({'natural','stretch','shrink'}) do
   local scale = tonumber(token.get_macro('ulsbs@verse@'..kind..'@'..field))
   assert(scale and scale >= 0 and scale < math.huge)
   assert(math.abs(skip[({'width','stretch','shrink'})[i]] - a*scale) <= 1,
    'finalized preset resolves against selected lyric A')
  end
  assert(skip.stretch_order == 0 and skip.shrink_order == 0)
 end
}
\endgroup
\ulVerseBaseline{2}{.5}{.25}\ulVerseSeparation{3}{.75}{.125}
\ulVerseBaseline{2.5}{.125}{.0625}\ulVerseSeparation{2.75}{.5}{.25}
\begin{ulSongs}{}\beginsong{Late spacing}\beginverse*\meter{}{}Word.
\endverse\endsong\end{ulSongs}
\directlua{
 assert(\ulVerseSpacingScale{baseline}{natural} == 2.5, 'late baseline setter wins')
 assert(\ulVerseSpacingScale{baseline}{stretch} == .125)
 assert(\ulVerseSpacingScale{baseline}{shrink} == .0625)
 assert(\ulVerseSpacingScale{separation}{natural} == 2.75, 'late separation setter wins')
 assert(\ulVerseSpacingScale{separation}{stretch} == .5)
 assert(\ulVerseSpacingScale{separation}{shrink} == .25)
}
\typeout{VERSE-API-PRESET-PASS}
""").replace(r"\documentclass[", rf"\documentclass[variants={{default,{variant}}},", 1))
                output = self.compile_source(source, label="verse-api-preset-" + variant)
                self.assertIn("VERSE-API-PRESET-PASS", output)

    def test_bar_configuration_booleanish_and_numeric_normalization(self):
        settings = []
        for value, expected in (("true", "1"), ("YES", "1"), (" On ", "1"), ("1", "1"),
                                ("false", "0"), ("NO", "0"), (" Off ", "0"), ("0", "0")):
            settings.append(r"\ulUseVerseAnnotationMinimum{" + value + r"}\directlua{"
                            + "assert(token.get_macro('ulsbs@bar@verseminimum') == '"
                            + expected + "')}")
        settings.append(r"""
\ulMeasureBarTop{+03}{02}{.7500}
\ulRepeatBarTop{3}{0}{0}
\ulRepeatBarBottomScale{2.5e-2}
\ulRepeatBarMinimumGap{.5pt}
\directlua{
 assert(token.get_macro('ulsbs@measure@level@3') == '2')
 assert(token.get_macro('ulsbs@measure@scale@3') == '0.75')
 assert(token.get_macro('ulsbs@repeat@level@3') == '0')
 assert(token.get_macro('ulsbs@repeat@scale@3') == '0')
 assert(token.get_macro('ulsbs@repeat@bottomscale') == '0.025')
 assert(token.get_macro('ulsbs@repeat@minimumgap') == '32768')
}
\ulRepeatBarMinimumGap{1pc}
\directlua{assert(token.get_macro('ulsbs@repeat@minimumgap') == '786432')}
\ulMeasureBarTop{3}{3}{1}
\directlua{assert(token.get_macro('ulsbs@measure@level@3') == '3')}
\ulRepeatBarMinimumGap{1073741823sp}
\directlua{assert(token.get_macro('ulsbs@repeat@minimumgap') == '1073741823')}
\ulRepeatBarMinimumGap{0}
\directlua{assert(token.get_macro('ulsbs@repeat@minimumgap') == '0')}
\ulRepeatBarBottomScale{1e308}
\directlua{assert(tonumber(token.get_macro('ulsbs@repeat@bottomscale')) == 1e308)}
\null
""")
        self.compile_source(document("\n".join(settings)), label="bar-api-normalize")

    def test_bar_configuration_rejects_invalid_values_without_installing_them(self):
        invalid = []
        for command in ("ulMeasureBarTop", "ulRepeatBarTop"):
            for n, level, scale in (("4", "0", "1"), ("-1", "0", "1"),
                                    ("1.0", "0", "1"), ("1", "2", "1"),
                                    ("2", "-1", "1"), ("2", "1.5", "1"),
                                    ("2", "1", "-0.1"), ("2", "1", "nan"),
                                    ("2", "1", "inf"), ("2", "1", "1pt"),
                                    ("2", "1", "1e309"),
                                    ("2", "1", "1+1"), ("2", "1", "")):
                invalid.append(rf"\{command}{{{n}}}{{{level}}}{{{scale}}}")
        invalid.extend(r"\ulUseVerseAnnotationMinimum{" + value + "}"
                       for value in ("maybe", "", "2"))
        invalid.extend(r"\ulRepeatBarBottomScale{" + value + "}"
                       for value in ("-1", "nan", "inf", "1e309", "1pt", ""))
        invalid.extend(r"\ulRepeatBarMinimumGap{" + value + "}"
                       for value in ("-1pt", "2", "1mu", "nan", "20000pt", "1073741824sp", "1e2pt", ""))
        preamble = r"""
\newcount\BarErrors
\let\OriginalPackageError\PackageError
\renewcommand\PackageError[3]{\advance\BarErrors1\typeout{BAR-REJECT:#1:#2}}
\directlua{
 bar_defaults = {}
 for _,kind in ipairs({'measure','repeat'}) do
   for n=0,3 do
     for _,field in ipairs({'level','scale'}) do
       local name = 'ulsbs@'..kind..'@'..field..'@'..n
       bar_defaults[name] = token.get_macro(name)
     end
   end
 end
 for _,name in ipairs({'ulsbs@bar@verseminimum','ulsbs@repeat@bottomscale','ulsbs@repeat@minimumgap'}) do
   bar_defaults[name] = token.get_macro(name)
 end
}
"""
        body = "\n".join(invalid) + r"""
\let\PackageError\OriginalPackageError
\directlua{for name,value in pairs(bar_defaults) do
 assert(token.get_macro(name) == value, 'invalid setter changed '..name)
end}
\typeout{BAR-ERROR-COUNT:\the\BarErrors}\null
"""
        output = self.compile_source(document(body, preamble), label="bar-api-atomic")
        self.assertIn(f"BAR-ERROR-COUNT:{len(invalid)}", output)
        self.assertEqual(output.count("BAR-REJECT:ulsbs:Invalid bar setting:"), len(invalid))

    def test_bar_configuration_notifies_context_once_per_scoped_command(self):
        commands = (r"\ulMeasureBarTop{1}{0}{.5}", r"\ulRepeatBarTop{2}{1}{.25}",
                    r"\ulUseVerseAnnotationMinimum{off}", r"\ulRepeatBarBottomScale{.05}",
                    r"\ulRepeatBarMinimumGap{0}")
        checks = "\n".join(
            command + rf"\ifnum\BarNotifications={number}\else"
            + r"\errmessage{Wrong bar context notification count}\fi"
            for number, command in enumerate(commands, 1))
        output = self.compile_source(document(r"""
\begingroup
\ExplSyntaxOn
\cs_set_protected:Npn \__ulsbs_music_context:
  {\global\advance\BarNotifications1\typeout{BAR-CONTEXT-NOTIFIED}}
\ExplSyntaxOff
""" + checks + r"""
\endgroup
\ifnum\BarNotifications=5\else\errmessage{Scoped notifications were lost}\fi
\typeout{BAR-CONTEXT-COUNT:\the\BarNotifications}\null
""", r"\newcount\BarNotifications"), label="bar-api-context")
        self.assertEqual(output.count("BAR-CONTEXT-NOTIFIED"), len(commands))
        self.assertIn("BAR-CONTEXT-COUNT:5", output)

    def test_bar_configuration_invalid_public_setters_fail_actionably(self):
        for label, setter in (("measure", r"\ulMeasureBarTop{4}{0}{1}"),
                              ("repeat", r"\ulRepeatBarTop{1}{2}{1}"),
                              ("minimum", r"\ulUseVerseAnnotationMinimum{maybe}"),
                              ("bottom", r"\ulRepeatBarBottomScale{-1}"),
                              ("gap", r"\ulRepeatBarMinimumGap{-1pt}")):
            with self.subTest(label=label):
                output = self.compile_source(document(r"\null", setter),
                                             label="bar-api-error-" + label,
                                             failure="Invalid bar setting")
                self.assertNotIn("Undefined control sequence", output)

    def test_mixed_stanzas_reserve_one_real_annotation_row_and_repeat_bottom_tracks_baseline(self):
        preamble = r"""
\ulSongColumns{1}\ulSongPosition{0}
\ulUseVerseAnnotationMinimum{true}
\newcommand\SpacingCase[1]{\directlua{spacing_case = '#1'}}
\directlua{
 local finish = ulsbs_music.finish_verse
 local hlist, vlist, rule, glue, kern = node.id('hlist'), node.id('vlist'), node.id('rule'), node.id('glue'), node.id('kern')
 local measure = \number\csname c__ulsbs_music_measure_attribute_int\endcsname
 local repetition = \csname ulsbs@rep@attribute\endcsname
 ulsbs_music.finish_verse = function(id)
   finish(id)
   if not spacing_case then return end
    local y, index, ends = 0, 0, {}
    local minimum, actual_chord
    for line in node.traverse_id(hlist, tex.box[id].list) do
      local data = (node.getproperty(line) or {}).ulsbs_music
      if data and data.level > 0 then
        if data.geometry.chord and not actual_chord then minimum = nil; actual_chord = true end
        if data.geometry.chord or not actual_chord then
          local ref = data.references[1]
          if not minimum or ref.bottom < minimum.bottom then minimum = ref end
        end
      end
    end
    local repeat_depth, alternate_expected
    local function inspect(list, baseline)
     local bars, alternates = 0, 0
     for n in node.traverse(list) do
       if n.id == rule and node.has_attribute(n, repetition) then
          assert(n.depth == repeat_depth, 'verse repeat depth must scale from lyric capital A')
         local serial = node.has_attribute(n, repetition)
         ends[serial] = math.max(ends[serial] or -math.huge, baseline + n.depth)
       elseif n.id == hlist then
         local nested, alt = inspect(n.list, baseline + n.shift)
         bars, alternates = math.max(bars, nested), math.max(alternates, alt)
       elseif n.id == vlist and node.has_attribute(n, measure) then
         if node.has_attribute(n, measure) == 1 then bars = math.max(bars, n.height)
         else
           assert(n.height == alternate_expected, 'altchords bar must retain annotation-free height')
           alternates = math.max(alternates, n.height)
         end
       end
     end
     return bars, alternates
   end
   for n in node.traverse(tex.box[id].list) do
     if n.id == hlist or n.id == vlist or n.id == rule then
       local baseline = y + n.height
        local bars, alternates = 0, 0
        local data = (node.getproperty(n) or {}).ulsbs_music
        if data then
           repeat_depth = math.floor(data.references[0].base *
             tonumber(token.get_macro('ulsbs@repeat@bottomscale')) + .5)
           alternate_expected = math.floor(data.references[0].base *
             tonumber(token.get_macro('ulsbs@measure@scale@0')) + .5)
        end
        if n.id == hlist then bars, alternates = inspect(n.list, baseline) end
        if data then
          index = index + 1
           local use_minimum = token.get_macro('ulsbs@bar@verseminimum') == '1'
           local level = data.level == 0 and minimum and use_minimum and 1 or data.level
           local selected = tonumber(token.get_macro('ulsbs@measure@level@'..level))
           local scale = tonumber(token.get_macro('ulsbs@measure@scale@'..level))
           local ref = data.references[selected] or (selected == 1 and minimum)
           local expected = math.max(0, math.floor(ref.bottom + ref.base * scale + .5))
          assert(bars == expected, 'mixed stanza bar must follow logical N and capital/circle reference')
          texio.write_nl('VERSE-ROW:' .. spacing_case .. ':' .. index .. ':' ..
            n.height .. '/' .. baseline .. '/' .. bars .. '/' .. alternates .. '/' .. repeat_depth)
       end
       y = baseline + n.depth
     elseif n.id == glue then y = y + n.width
     elseif n.id == kern then y = y + n.kern end
   end
   for serial, bottom in pairs(ends) do
     texio.write_nl('REPEAT-BOTTOM:' .. spacing_case .. ':' .. serial .. ':' .. bottom)
   end
 end
}
"""
        body = [r"\begin{ulSongs}{}\beginsong{One real row}[key={C}]"]
        for label, controls, middle in (
            ("empty", "", ""),
            ("hidden", r"\chordsoff\notesoff\beatsoff", r"\[<C;G>C]"),
            ("beat", r"\chordsoff\notesoff", r"\[<*>]"),
            ("chord", "", r"\[C]"),
            ("chordnote", "", r"\[<C>C]"),
            ("chordnotes", "", r"\[<C;G>C]"),
            ("mixed", "", r"\[<C>]Note \[G]"),
            ("pitch", "", r"\[<C>]"),
            ("pitches", "", r"\[<C;G>]"),
            ("late", "", ""),
            ("wrap", "", r"\[C]"),
            ("gap", "", r"\[C]"),
            ("authored", r"\renewcommand\ulEveryVerse{\baselineskip=40pt plus2pt minus1pt}", r"\[C]"),
            ("alternate", "", r"\[<C;G>C]"),
        ):
            first = r"|First.\hfil\break |Wrapped." if label == "wrap" else "|First."
            last = r"|\[C]Last." if label == "late" else "|Last."
            alt = (r" \altchords{|\id{G}|\id{C}|}"
                   if label == "alternate" else "")
            body.extend((r"{\SpacingCase{" + label + "}" + controls, r"\beginverse*\meter{}{}",
                         first, "|" + middle + "Middle." + alt,
                         r"\vskip7pt" if label == "gap" else "", last, r"\endverse}"))
        body.extend((r"\SpacingCase{repeats}\beginverse*\meter{}{}",
                     r"\beginrep |\[C]First.", "|Descenderp.", r"\endrep",
                     r"\beginrep |\[C]Next.\hfil\break |Wrappedp.", r"\endrep\endverse",
                     r"\directlua{spacing_case = nil}\endsong\end{ulSongs}"))
        editions = []
        for layers in (False, True):
            output = self.compile_source(
                r"\def\ulPdfTranspositionLayers{" + str(layers).lower() + "}"
                + document("\n".join(body), preamble), label=f"one-row-{layers}", passes=3)
            rows = {}
            for label, index, *values in re.findall(
                     r"VERSE-ROW:(\w+):(\d+):(\d+)/(\d+)/(\d+)/(\d+)/(\d+)", output):
                rows[label + index] = tuple(map(int, values))
            chord = rows["chord1"][0]
            self.assertGreater(chord, rows["empty1"][0])
            for label in ("chord", "chordnote", "chordnotes", "mixed", "late", "wrap", "gap", "alternate"):
                self.assertEqual(rows[label + "1"][0], chord, label)
                self.assertEqual(rows[label + "3"][0], chord, label)
                self.assertEqual(rows[label + "1"][2], chord, label)
            self.assertEqual(rows["hidden1"], rows["empty1"])
            self.assertEqual(rows["beat1"], rows["empty1"])
            self.assertGreater(rows["chordnotes2"][0], chord)
            self.assertLess(rows["chordnotes2"][2], rows["chordnotes2"][0])
            self.assertGreater(rows["chordnotes2"][2], chord)
            self.assertLess(rows["chordnote2"][2], rows["chordnote2"][0])
            self.assertEqual(rows["pitches1"][0], rows["pitch1"][0])
            self.assertGreater(rows["pitches2"][0], rows["pitches1"][0])
            normal_gap = rows["chord3"][1] - rows["chord2"][1]
            self.assertEqual(rows["chord2"][1] - rows["chord1"][1], normal_gap)
            self.assertEqual(rows["gap3"][1] - rows["gap2"][1], normal_gap + 7 * 65536)
            self.assertEqual(rows["authored3"][1] - rows["authored2"][1], 40 * 65536)
            self.assertGreater(rows["alternate2"][3], 0)
            self.assertLess(rows["alternate2"][3], rows["alternate2"][2])
            bottoms = {int(serial): int(bottom) for serial, bottom in re.findall(
                r"REPEAT-BOTTOM:repeats:(\d+):(\d+)", output)}
            self.assertEqual(sorted(bottoms.values()),
                              [rows["repeats2"][1] + rows["repeats2"][4],
                               rows["repeats4"][1] + rows["repeats4"][4]])
            editions.append((rows, bottoms))
        self.assertEqual(*editions)

    def test_ink_clearance_across_glued_verses_and_authored_shrink(self):
        preamble = r"""
\ulSongColumns{1}\ulSongPosition{0}
\newbox\ClearanceProbe
\newcommand\CheckClearance{\directlua{
 local hlist, vlist, rule, glue, kern = node.id('hlist'), node.id('vlist'), node.id('rule'), node.id('glue'), node.id('kern')
 local y, previous, lines = 0, nil, 0
 for n in node.traverse(tex.box[\number\ClearanceProbe].list) do
   if n.id == hlist or n.id == vlist or n.id == rule then
     if (node.getproperty(n) or {}).ulsbs_music then
       lines = lines + 1
       if previous then
         assert(y - previous >= tex.sp('1pt'), 'ink clearance across a glued stanza boundary')
       end
       previous = y + n.height + n.depth
     end
     y = y + n.height + n.depth
   elseif n.id == glue then
     y = y + n.width
     if previous and n.shrink_order == 0 then y = y - n.shrink end
   elseif n.id == kern then y = y + n.kern end
 end
 assert(lines == 4, 'audit all source lines across both stanzas')
 texio.write_nl('INK-CLEARANCE-PASS')
}}
"""
        body = r"""
\begin{ulSongs}{}\beginsong{Boundary ink}[key={C}]
\setbox\ClearanceProbe=\vbox{
\beginverse*\meter{}{}
|\[C]Firstgypqj.
|\[<C;G>C]Lastgypqj.
\endverse\glueverses
\beginverse*
\beginrep
|\[<C>C]Nextgypqj.
|\[C]Finalgypqj.
\endrep\endverse
}
\CheckClearance\box\ClearanceProbe
\endsong\end{ulSongs}
"""
        for layers in (False, True):
            output = self.compile_source(
                r"\def\ulPdfTranspositionLayers{" + str(layers).lower() + "}"
                + document(body, preamble + r"\renewcommand\ulEveryVerse{\baselineskip=12pt minus6pt}"),
                label=f"ink-boundary-{layers}", passes=3)
            self.assertEqual(output.count("INK-CLEARANCE-PASS"), 3)

    def test_inline_first_paragraphs_with_and_without_chords(self):
        for mode in ("chorded", "chords-off", "lyric"):
            with self.subTest(mode=mode):
                source = document(r"""
\begin{ulSongs}{}
\beginsong{Inline source}
\beginverse* Hidden chords: \[C]still lyrics.\endverse
\beginverse Inline number: \[G]still lyrics.\endverse
\beginverse*[1] Indented inline source.\endverse
\beginverse*
Physical first line.
\endverse
\endsong
\end{ulSongs}
""", r"\chordsoff" if mode == "chords-off" else "",
                                  variant="lyric" if mode == "lyric" else "default")
                self.compile_source(source, label=mode)
                text = self.pdf_text()
                for anchor in ("Hidden chords:", "Inline number:", "Indented inline source.",
                               "Physical first line."):
                    self.assertIn(anchor, text)

    def test_physical_lines_comments_groups_and_explicit_spaces(self):
        output = self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Token semantics}
\beginverse*
\typeout{EMPTYLINE-BASE:\the\baselineskip}
First physical
Second physical
Comment% removes the newline, no inserted space
joined \textbf{grouped words} explicit\ space \% \& \#
{Groupfirst
Groupsecond} final

Afterblank
\emptyline
Afterempty
Controlblank
Controlempty
\endverse
\endsong
\end{ulSongs}
"""))
        self.assertLess(self.word("First")["yMin"], self.word("Second")["yMin"])
        self.assertIn("Commentjoined", self.pdf_text())
        self.assertIn("grouped words", self.pdf_text())
        self.assertIn("explicit space", self.pdf_text())
        self.assertLess(self.word("Groupfirst")["yMin"], self.word("Groupsecond")["yMin"])
        gap = self.word("Afterempty")["yMin"] - self.word("Afterblank")["yMin"]
        controlgap = self.word("Controlempty")["yMin"] - self.word("Controlblank")["yMin"]
        baseline = float(re.search(r"EMPTYLINE-BASE:([\d.]+)pt", output).group(1)) * 72 / 72.27
        # Physical ink gaps depend on descenders; emptyline adds one authored
        # baseline, not twice an unrelated pair's collision-adjusted spacing.
        self.assertAlmostEqual(gap - controlgap, baseline, delta=.03)

    def test_modifiers_indentation_plus_spacing_and_restore(self):
        self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Modifiers}
\beginverse*
Plainfirst
Plainsecond
\endverse
\beginverse*+[2]
Plusfirst
Plussecond
\endverse
\beginverse*[1]
Indentfirst
Indentsecond
\endverse
\endsong
\end{ulSongs}
"""))
        plain = self.word("Plainfirst")
        plus = self.word("Plusfirst")
        indent = self.word("Indentfirst")
        self.assertAlmostEqual(plus["xMin"] - plain["xMin"],
                               2 * (indent["xMin"] - plain["xMin"]), delta=.03)
        self.assertAlmostEqual(plus["xMin"], self.word("Plussecond")["xMin"], delta=.03)
        normalgap = self.word("Plainsecond")["yMin"] - plain["yMin"]
        plusgap = self.word("Plussecond")["yMin"] - plus["yMin"]
        restoredgap = self.word("Indentsecond")["yMin"] - indent["yMin"]
        self.assertAlmostEqual(plusgap, normalgap, delta=.03)
        self.assertAlmostEqual(normalgap, restoredgap, delta=.03)

    def test_modifier_scanner_preserves_whitespace_and_comments(self):
        self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Modifier whitespace}
\beginverse * % comment between star and plus
+
[2]
Acrossfirst
Acrosssecond
\endverse
\beginverse*+[2]
Inlinefirst
Inlinesecond
\endverse
\endsong
\end{ulSongs}
"""))
        self.assertAlmostEqual(self.word("Acrossfirst")["xMin"],
                               self.word("Inlinefirst")["xMin"], delta=.03)
        across = self.word("Acrosssecond")["yMin"] - self.word("Acrossfirst")["yMin"]
        inline = self.word("Inlinesecond")["yMin"] - self.word("Inlinefirst")["yMin"]
        self.assertAlmostEqual(across, inline, delta=.03)

    def test_pitch_request_restores_at_stanza_and_song_boundaries(self):
        output = self.compile_source(document(r"""
\begin{ulSongs}{}\beginsong{Scoped pitches}[key={C}]
{\notesoff
 \beginverse*+
Hiddenfirst
Hiddensecond
\endverse
 \ifulShowNotes\errmessage{Lost surrounding request}\fi}
\ifulShowNotes\else\errmessage{Lost grouped restoration}\fi
\beginverse*+\notesoff
\typeout{STANZA-NOTES:\ifulShowNotes on\else off\fi}
Restoredfirst
Restoredsecond
\endverse
\ifulShowNotes\else\errmessage{Request escaped stanza}\fi
\notesoff\endsong
\ifulShowNotes\else\errmessage{Request escaped song}\fi
\beginsong{Next song}
\beginverse*+
Nextfirst
Nextsecond
\endverse
\endsong\end{ulSongs}
""", r"\chordsoff\beatsoff"))
        self.assertIn("STANZA-NOTES:off", output)
        gaps = {name: self.word(name + "second")["yMin"] - self.word(name + "first")["yMin"]
                for name in ("Hidden", "Restored", "Next")}
        self.assertAlmostEqual(gaps["Restored"], gaps["Hidden"], delta=.03)
        self.assertAlmostEqual(gaps["Restored"], gaps["Next"], delta=.03)

    def test_beat_request_restores_at_stanza_and_song_boundaries(self):
        output = self.compile_source(document(r"""
\begin{ulSongs}{}\beginsong{Scoped beats}[key={C}]
{\beatsoff
 \beginverse*
\[<C*>]Hidden
\endverse
 \ifulShowBeats\errmessage{Lost surrounding request}\fi}
\ifulShowBeats\else\errmessage{Lost grouped restoration}\fi
\beginverse*\beatsoff
\typeout{STANZA-BEATS:\ifulShowBeats on\else off\fi}
\[<C*>]Suppressed
\endverse
\ifulShowBeats\else\errmessage{Request escaped stanza}\fi
\beatsoff\endsong
\ifulShowBeats\else\errmessage{Request escaped song}\fi
\beginsong{Next song}
\beginverse*
\[<C*>]Restored
\endverse
\endsong\end{ulSongs}
""", r"\chordsoff\notesoff"))
        self.assertIn("STANZA-BEATS:off", output)

    def test_once_only_effects_hooks_and_number_counter(self):
        preamble = r"""
\newcount\ProbeEffects
\newcommand\Effect{\global\advance\ProbeEffects1 EFFECT}
\renewcommand\ulPrintVerseNumber[1]{V#1\space}
\setlength\ulVerseNumberWidth{20pt}
\AddToHook{ulsbs/stanza/start}{\typeout{STANZA-START=\theulVerseNumber}}
\AddToHook{ulsbs/stanza/finish}{\typeout{STANZA-FINISH=\theulVerseNumber}}
\renewcommand\ulEveryVerse{\typeout{EVERY-VERSE}}
"""
        output = self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Numbers}
\beginverse
\Effect \textbf{\Effect}
\endverse
\beginverse*
Unnumbered
\endverse
\beginverse+[1]
Lastnumbered
\endverse
\typeout{NEXT-NUMBER=\theulVerseNumber;EFFECTS=\the\ProbeEffects}
\endsong
\beginsong{Reset}
\beginverse
Resetnumber
\endverse
\endsong
\end{ulSongs}
""", preamble))
        self.assertEqual(re.findall(r"STANZA-START=(\d+)", output), ["1", "2", "2", "1"])
        self.assertEqual(re.findall(r"STANZA-FINISH=(\d+)", output), ["1", "2", "2", "1"])
        self.assertEqual(output.count("EVERY-VERSE"), 4)
        self.assertIn("NEXT-NUMBER=3;EFFECTS=2", output)
        self.assertEqual(self.pdf_text().count("EFFECT"), 2)
        self.assertIn("V2", self.pdf_text())

    def test_stanza_glue_is_one_shot_and_resets_between_songs(self):
        output = self.compile_source(document(r"""
\typeout{STANZA-SEPARATION:\the\csname ulsbs@verse@separation\endcsname}
\begin{ulSongs}{}
\beginsong{Glue}
\beginverse*
Gluefirst
\glueverses
\endverse
\beginverse*
Gluesecond
\endverse
\beginverse*
Separated
\endverse
\glueverses
\endsong
\beginsong{Reset glue}
\beginverse*
Resetfirst
\endverse
\beginverse*
Resetsecond
\endverse
\endsong
\end{ulSongs}
"""))
        glued = self.word("Gluesecond")["yMin"] - self.word("Gluefirst")["yMin"]
        separated = self.word("Separated")["yMin"] - self.word("Gluesecond")["yMin"]
        reset = self.word("Resetsecond")["yMin"] - self.word("Resetfirst")["yMin"]
        separation = float(re.search(r"STANZA-SEPARATION:([\d.]+)pt", output).group(1))
        self.assertAlmostEqual(separated - glued, separation * 72 / 72.27, delta=.05)
        self.assertAlmostEqual(separated, reset, delta=.05)

    def test_long_source_line_wraps_and_newline_starts_new_paragraph(self):
        source = (r"\begin{ulSongs}{}\beginsong{Wrap}" + "\n"
                  + r"\beginverse*[2]" + "\nWrapstart " + "wrappedword " * 60
                  + "Wrapend\nNextsource\n" + r"\endverse\endsong\end{ulSongs}")
        self.compile_source(document(source))
        self.assertGreater(self.word("Wrapend")["yMin"], self.word("Wrapstart")["yMin"])
        self.assertGreater(self.word("Nextsource")["yMin"], self.word("Wrapend")["yMin"])
        self.assertAlmostEqual(self.word("Nextsource")["xMin"], self.word("Wrapstart")["xMin"], delta=.03)

    def test_fonts_multilingual_arguments_and_scoped_catcodes(self):
        self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Languages}
\beginverse*
Ääni coração canción
\textit{français português suomi}
\endverse
Outside \textbf{ordinary argument} with math $x^2$.
\endsong
\end{ulSongs}
"""))
        text = self.pdf_text()
        for value in ("Ääni", "coração", "canción", "français", "português", "suomi",
                      "ordinary argument"):
            self.assertIn(value, text)

    def test_first_active_accidentals_and_literal_escapes(self):
        self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Accidentals}
\beginverse*[1]
#Sharpfirst \# literalhash
&Flatfirst \& literalampersand
\endverse
\endsong
\end{ulSongs}
"""))
        text = self.pdf_text()
        self.assertIn("Sharpfirst", text)
        self.assertIn("Flatfirst", text)
        self.assertIn("# literalhash", text)
        self.assertIn("& literalampersand", text)

    def test_explicit_breaks_disobeylines_and_obeylines(self):
        self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Line controls}
\beginverse*
Explicitfirst\\Explicitsecond
Physicalthird
\disobeylines
Prosefirst
Prosesecond\par
\obeylines
Restoredfirst
Restoredsecond
\endverse
\endsong
\end{ulSongs}
"""))
        self.assertLess(self.word("Explicitfirst")["yMin"], self.word("Explicitsecond")["yMin"])
        self.assertLess(self.word("Explicitsecond")["yMin"], self.word("Physicalthird")["yMin"])
        self.assertAlmostEqual(self.word("Prosefirst")["yMin"], self.word("Prosesecond")["yMin"], delta=.03)
        self.assertLess(self.word("Restoredfirst")["yMin"], self.word("Restoredsecond")["yMin"])

    def test_named_lyric_variant_plus_keeps_independent_line_metrics(self):
        source = document(r"""
\begin{ulSongs}{}
\beginsong{Lyric metrics}
\beginverse*
Lyricfirst
Lyricsecond
\endverse
\beginverse*+
Lyricplusfirst
Lyricplussecond
\endverse
\endsong
\end{ulSongs}
""", r"\AtBeginDocument{\ulIfVariant{lyric}{\typeout{TRUE-LYRIC}}{}}")
        source = source.replace("oneside,openany,", "variants={default,lyric},oneside,openany,", 1)
        output = self.compile_source("\\def\\ulBuildVariant{lyric}\n" + source)
        self.assertIn("TRUE-LYRIC", output)
        normal = self.word("Lyricsecond")["yMin"] - self.word("Lyricfirst")["yMin"]
        plus = self.word("Lyricplussecond")["yMin"] - self.word("Lyricplusfirst")["yMin"]
        self.assertAlmostEqual(normal, plus, delta=.03)

    def test_source_line_penalties_protect_wraps_and_brk_replaces_boundary(self):
        preamble = r"""
\interlinepenalty=1371
\ulBreakPenalty=91
\AddToHook{ulsbs/stanza/finish}{\directlua{
  for n in node.traverse(tex.nest.top.head) do
    if n.id == node.id('penalty') then
      texio.write_nl('term and log','VERSE-PENALTY='..n.penalty)
    end
  end
}}
"""
        source = ("\\begin{ulSongs}{}\\beginsong{Penalties}\n\\beginverse*\n"
                  + "Wrapstart " + "manyword " * 70
                  + "Wrapend\nBoundaryone\nBoundarytwo\n\\brk\nFinal\n"
                  + r"\endverse\endsong\end{ulSongs}")
        output = self.compile_source(document(source, preamble))
        penalties = [int(value) for value in re.findall(r"VERSE-PENALTY=(-?\d+)", output)]
        self.assertIn(1371, penalties)
        self.assertIn(91, penalties)
        self.assertTrue(any(value >= 10000 for value in penalties), penalties)
        self.assertNotEqual(penalties[-1], 1371, penalties)

    def test_plain_stanza_relative_geometry(self):
        source = document(r"""
\begin{ulSongs}{}
\beginsong{Relative metrics}
\beginverse*+[2]
Anchorfirst explicit\ space
Secondline {grouped words} % retain a word space but suppress this newline
joinedwords
Thirdline
\endverse
\endsong
\end{ulSongs}
""", r"""
\renewcommand\ulEveryVerse{\typeout{VERSE-BASELINE=\the\baselineskip}}
""")
        names = ("Anchorfirst", "explicit", "space", "Secondline", "grouped", "words",
                 "joinedwords", "Thirdline")
        self.compile_source(source)
        actual = {name: self.word(name) for name in names}
        for first, second in (("Anchorfirst", "explicit"), ("explicit", "space"),
                              ("Secondline", "grouped"), ("grouped", "words"),
                              ("words", "joinedwords")):
            self.assertAlmostEqual(actual[first]["yMin"], actual[second]["yMin"], delta=.03)
            self.assertLess(actual[first]["xMax"], actual[second]["xMin"])
        self.assertLess(actual["Anchorfirst"]["yMin"], actual["Secondline"]["yMin"])
        self.assertLess(actual["Secondline"]["yMin"], actual["Thirdline"]["yMin"])

    def test_verse_boundary_penalties_and_scoped_separation(self):
        preamble = r"""
\ulVerseVersePenalty=317
\ulGluePenalty=863
\ExplSyntaxOn
\cs_new_eq:NN \test_layout_break:n \__ulsbs_layout_break:n
\cs_set_protected:Npn \__ulsbs_layout_break:n #1
  {\typeout{STANZA-BREAK=\int_eval:n{#1}}\test_layout_break:n{#1}}
\ExplSyntaxOff
"""
        output = self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Boundary controls}
\beginverse First.\endverse
\beginverse*\beginrep Repeated.\endrep\endverse
\glueverses
\beginverse Glued.\endverse
{\ulSeparateVerses
\beginverse Separate.\endverse
}
\beginverse Restored.\endverse
\endsong
\end{ulSongs}
""", preamble))
        penalties = [int(value) for value in re.findall(r"STANZA-BREAK=(-?\d+)", output)]
        self.assertEqual([value for value in penalties if value != 0], [317, 863, -10000, 317])

    def test_command_and_environment_stanza_entrypoints(self):
        self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Owned}
\beginverse*[1]
Owned first
Owned second
\endverse
\begin{verse*}
Environment
\end{verse*}
\endsong
\end{ulSongs}
"""))
        text = self.pdf_text()
        for anchor in ("Owned first", "Owned second", "Environment"):
            self.assertIn(anchor, text)

    def test_misordered_stanza_states_fail_actionably(self):
        cases = (("outside", r"\beginverse Text", "outside"),
                 ("end", r"\begin{ulSongs}{}\beginsong{Bad}\endverse", "without"),
                 ("nested", "\\begin{ulSongs}{}\\beginsong{Bad}\n\\beginverse\n\\beginverse", "missing"),
                 ("unclosed", "\\begin{ulSongs}{}\\beginsong{Bad}\n\\beginverse\nText\n\\endsong", "missing"))
        for label, body, diagnostic in cases:
            with self.subTest(label=label):
                output = self.compile_source(document(body), label=label, failure=diagnostic)
                self.assertNotIn("Undefined control sequence", output)

    def test_music_is_owned_including_first_token_after_modifiers(self):
        for label, notation in (("chord", r"\[C]Word"), ("replay", "^Word"),
                                ("bar", "|Word"), ("transpose", r"\transpose{1}")):
            with self.subTest(label=label):
                output = self.compile_source(document(
                    "\\begin{ulSongs}{}\\beginsong{Music}\n"
                    "\\beginverse*\n\\[C]Memory\n\\endverse\n\\beginverse*+[1]\n"
                    + notation + "\n\\endverse\\endsong\\end{ulSongs}"),
                    label=label)
                self.assertNotIn("Undefined control sequence", output)


if __name__ == "__main__":
    unittest.main()
