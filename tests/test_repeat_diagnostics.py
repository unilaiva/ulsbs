# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Repeat-box diagnostics are observable even for unselected source songs."""

import json
import os
from pathlib import Path
import re
import unittest

import test_song_lifecycle as lifecycle
import test_song_order as order
from test_tex_integration import ROOT


class RepeatDiagnosticsTests(unittest.TestCase):
    setUp = lifecycle.SongLifecycleTests.setUp
    compile_source = lifecycle.SongLifecycleTests.compile_source
    compile_checked = order.SongOrderTests.compile_checked

    @classmethod
    def setUpClass(cls):
        lifecycle.SongLifecycleTests.setUpClass.__func__(cls)
        cls.diagnostics = Path(os.environ.get(
            "ULSBS_REPEAT_DIAGNOSTICS", ROOT / "build/repeat-diagnostics"))
        cls.diagnostics.mkdir(parents=True, exist_ok=True)

    def check(self, *, selected, mode):
        # Each final source paragraph wraps, so endrep must emit the remaining
        # repeat-bar fragment. Its zero-width box deliberately has positive
        # natural width: content inset plus the optional verse inset.
        body = "\\begin{ulSongs}{titleidx,authidx,tagidx}\n"
        body += "\\beginsong{Wrapped}[id={wrapped},by={Author},tags={fire}]\n"
        for option in ("", "[1]"):
            body += "\\beginverse" + option + "\n\\beginrep\n\\Effect "
            body += "wrapped words " * 18
            body += "\n\\endrep\n\\endverse\n"
        body += r"""\endsong
\beginsong{Visible}[id={visible},by={Author},tags={fire}]
\beginverse*
\Effect Visible line
\endverse
\endsong
\end{ulSongs}\typeout{REPEAT-EFFECTS:\the\Effects}
"""
        preamble = r"""
\newcount\Effects\def\Effect{\global\advance\Effects1\relax}
"""
        preamble += r"\ulIncludeOnlySongs{1}" if selected else r"\ulIncludeOnlySongs{2}"
        if mode == "hidden":
            preamble += r"\chordsoff"
        source = lifecycle.document(body, preamble,
                                    variant="lyric" if mode == "lyrics" else "default")
        label = f"{mode}-{'selected' if selected else 'excluded'}"
        outputs = self.compile_checked(source, label)
        expected_lines = [n for n, line in enumerate(source.splitlines(), 1)
                          if line.strip() == r"\endrep"] * 2
        report = {}
        for result, output in outputs.items():
            compiled = source
            warnings = re.findall(r"Overfull \\hbox \([^\n]*detected at line \d+", output)
            report[result] = {
                "warnings": warnings,
                "source_lines": [
                    {"line": int(re.search(r"line (\d+)$", message).group(1)),
                     "text": compiled.splitlines()[
                         int(re.search(r"line (\d+)$", message).group(1)) - 1]}
                    for message in warnings
                ],
                "effects": re.findall(r"REPEAT-EFFECTS:(\d+)", output),
            }
        path = self.diagnostics / self._testMethodName / label / "warnings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.assertEqual([row["line"] for row in report["output"]["source_lines"]],
                         expected_lines, str(path))
        widths = [float(re.search(r"\(([\d.]+)pt", warning).group(1))
                  for warning in report["output"]["warnings"]]
        self.assertTrue(all(width > 0 for width in widths), str(path))
        self.assertGreater(widths[1], widths[0], str(path))
        self.assertEqual(report["output"]["effects"], ["3", "3"], str(path))

    def test_excluded_wrapped_repeat_diagnostics(self):
        for mode in ("chorded", "hidden", "lyrics"):
            with self.subTest(mode=mode):
                self.check(selected=False, mode=mode)

    def test_selected_wrapped_repeat_diagnostics(self):
        for mode in ("chorded", "hidden", "lyrics"):
            with self.subTest(mode=mode):
                self.check(selected=True, mode=mode)

    def test_configured_gap_reaches_real_adjacent_source_sections(self):
        capture = r"""\directlua{
local original = luatexbase.add_to_callback
luatexbase.add_to_callback = function(name, callback, description, ...)
  if description == 'ulsbs.repeatbars' then
    luatexbase.add_to_callback = original
    local function audited(head)
      local result = callback(head)
      local attribute = tonumber(token.get_macro('ulsbs@rep@attribute'))
      local hlist, vlist, rule, glue, kern = node.id('hlist'), node.id('vlist'), node.id('rule'), node.id('glue'), node.id('kern')
      local rectangles = {}
      local walk
      local function horizontal(list, x, baseline, parent)
        for n in node.traverse(list) do
          if n.id == rule and node.has_attribute(n, attribute) and n.width > 0 and n.height + n.depth > 0 then
            table.insert(rectangles, {x=x, top=baseline-n.height, bottom=baseline+n.depth})
          elseif n.id == hlist or n.id == vlist then walk(n, x, baseline+n.shift) end
          if n.id == glue then x=x+node.effective_glue(n,parent)
          elseif n.id == kern then x=x+n.kern
          elseif n.width then x=x+n.width end
        end
      end
      walk = function(box, x, baseline)
        if box.id == hlist then horizontal(box.list,x,baseline,box)
        else
          local y=baseline-box.height
          for n in node.traverse(box.list) do
            if n.id == hlist or n.id == vlist then walk(n,x+n.shift,y+n.height);y=y+n.height+n.depth
            elseif n.id == glue then y=y+node.effective_glue(n,box)
            elseif n.id == kern then y=y+n.kern
            elseif n.id == rule then y=y+n.height+n.depth end
          end
        end
      end
      walk(head,0,head.height)
      assert(\string#rectangles==2,'two actual source repeat sections')
      table.sort(rectangles,function(a,b)return a.top<b.top end)
      assert(rectangles[1].x==rectangles[2].x,'same physical repeat column')
      local gap=rectangles[2].top-rectangles[1].bottom
      if requested_gap==0 then assert(gap<tex.sp('2pt'),'disabled gap retains natural close sections')
      else assert(math.abs(gap-requested_gap)<2,'configured gap reaches generated source rules') end
      texio.write_nl('SOURCE-REPEAT-GAP:'..gap)
      return result
    end
    return original(name,audited,description,...)
  end
  return original(name,callback,description,...)
end
}
"""
        body = r"""\begin{ulSongs}{}\beginsong{Source gaps}[key={C}]
\beginverse*\meter{}{}
\beginrep |\[C]ACE.
\endrep
\beginrep |\[C]ACE.
\endrep\endverse
\endsong\end{ulSongs}"""
        for gap in (0, 2, 5):
            for layers in (False, True):
                # Fix the probe's ink spacing/relative reach explicitly; shipped
                # presentation defaults are intentionally free to be retuned.
                preamble = (r"\ulSongColumns{1}\ulSongPosition{0}"
                            r"\ulVerseMinimumGap{1pt}\ulVerseBaseline{0}{0}{0}"
                            r"\ulMeasureBarTop{1}{1}{2}\ulRepeatBarTop{1}{1}{2}"
                            + rf"\ulRepeatBarMinimumGap{{{gap}pt}}\directlua{{requested_gap=tex.sp('{gap}pt')}}")
                source = capture + r"\def\ulPdfTranspositionLayers{" + str(layers).lower() + "}"
                output = self.compile_source(source + lifecycle.document(body, preamble),
                                             label=f"source-gap-{gap}-{layers}", passes=2)
                self.assertEqual(output.count("SOURCE-REPEAT-GAP:"), 2)

    def test_minimum_gap_clips_only_separate_completed_repeat_ink(self):
        # Capture the actual registered callback, then exercise real LuaTeX
        # nodes at exact coordinates without relying on font/layout rounding.
        capture = r"""\directlua{
local original = luatexbase.add_to_callback
luatexbase.add_to_callback = function(name, fn, description, ...)
  if description == 'ulsbs.repeatbars' then
    repeat_gap_callback = fn
    luatexbase.add_to_callback = original
  end
  return original(name, fn, description, ...)
end
}
"""
        probe = r"""
\directlua{
local attr = tonumber(token.get_macro('ulsbs@rep@attribute'))
local startattr = tonumber(token.get_macro('ulsbs@rep@startattribute'))
local endattr = tonumber(token.get_macro('ulsbs@rep@endattribute'))
local gapattr = tonumber(token.get_macro('ulsbs@rep@gapattribute'))
local sp = 65536
local function check(label, specs, expected)
  local page = node.new('hlist')
  page.dir = 'TLT'
  page.height = 0
  page.width = 100 * sp
  local tail, rules, boxes = nil, {}, {}
  local function append(n)
    if tail then tail.next = n; n.prev = tail else page.list = n end
    tail = n
  end
  for i, s in ipairs(specs) do
    local rule = node.new('rule')
    rule.width = sp
    rule.height = (s.baseline - s.top) * sp
    rule.depth = (s.bottom - s.baseline) * sp
    node.set_attribute(rule, attr, s.id or i)
    if not (s.start == false) then node.set_attribute(rule, startattr, 1) end
    if s.gap then node.set_attribute(rule, gapattr, s.gap * sp) end
    local box = node.new('hlist')
    box.dir = 'TLT'
    box.list = rule
    box.width = 0; box.height = 0; box.depth = 0
    box.shift = s.baseline * sp
    append(box)
    rules[i] = rule; boxes[i] = box
    if not (s.finish == false) then
      local marker = node.new('whatsit', 'user_defined')
      marker.type = 100; marker.value = 0
      node.set_attribute(marker, attr, s.id or i)
      node.set_attribute(marker, endattr, 1)
      append(marker)
    end
    if s.close then
      local marker = node.new('whatsit', 'user_defined')
      marker.type = 100; marker.value = 0
      node.set_attribute(marker, attr, s.close)
      node.set_attribute(marker, endattr, 1)
      append(marker)
    end
  end
  assert(repeat_gap_callback(page))
  for i, e in ipairs(expected) do
    local rule, box = rules[i], boxes[i]
    assert(box.width == 0 and box.height == 0 and box.depth == 0,
           label .. ': layout changed')
    if e.zero then
      assert(rule.width == 0 and rule.height == 0 and rule.depth == 0, label)
      if e.top then
        local overlay = box.list
        assert(overlay.id == node.id('hlist'), label .. ': missing overlay')
        assert(overlay.width == 0 and overlay.height == 0 and overlay.depth == 0)
        local dash = overlay.list
        local bottom = specs[i].baseline * sp + overlay.shift
        assert(bottom == e.bottom * sp and bottom - dash.height == e.top * sp,
               label .. ': overlay interval')
        assert(dash.height > 0 and dash.depth == 0)
      end
    else
      assert(specs[i].baseline * sp - rule.height == e.top * sp,
             label .. ': incorrect top')
      assert(specs[i].baseline * sp + rule.depth == e.bottom * sp,
             label .. ': incorrect bottom')
    end
  end
  assert(page.width == 100 * sp and page.height == 0)
  node.flush_node(page)
  texio.write_nl('REPEAT-GAP-PASS:' .. label)
end
local first = {top=0, bottom=12, baseline=10}
check('configured-fallback', {first, {top=-100, bottom=30, baseline=25}},
      {{top=0,bottom=12}, {top=14,bottom=30}})
check('disabled', {first, {top=-100, bottom=30, baseline=25,gap=0}},
      {{top=0,bottom=12}, {top=-100,bottom=30}})
check('custom', {first, {top=-100, bottom=30, baseline=25,gap=5}},
      {{top=0,bottom=12}, {top=17,bottom=30}})
check('already-clear', {first, {top=20, bottom=30, baseline=25}},
      {{top=0,bottom=12}, {top=20,bottom=30}})
check('below-baseline', {first, {top=-100,bottom=20,baseline=13}},
      {{top=0,bottom=12}, {zero=true,top=14,bottom=20}})
check('exhausted', {first, {top=-100,bottom=13,baseline=13}},
      {{top=0,bottom=12}, {zero=true}})
check('exhausted-again', {first, {top=-100,bottom=13,baseline=13}},
      {{top=0,bottom=12}, {zero=true}})
check('outgoing', {{top=0,bottom=12,baseline=10,finish=false},
                   {top=-100,bottom=30,baseline=25}},
      {{top=0,bottom=12}, {top=-100,bottom=30}})
check('incoming', {first, {top=10,bottom=30,baseline=25,start=false}},
      {{top=0,bottom=12}, {top=10,bottom=30}})
check('same-occurrence', {{top=0,bottom=12,baseline=10,id=1},
                         {top=5,bottom=30,baseline=25,id=1}},
      {{top=0,bottom=30}, {zero=true}})
check('nested-ongoing', {{top=0,bottom=40,baseline=10,finish=false},
                        {top=-100,bottom=30,baseline=25}},
      {{top=0,bottom=40}, {top=-100,bottom=30}})
check('nested-completed', {{top=0,bottom=40,baseline=10,finish=false},
                          {top=-100,bottom=30,baseline=25,close=1}},
      {{top=0,bottom=40}, {top=-100,bottom=30}})
}
Gap probe.
"""
        # This is a controlled fallback-policy probe, not a frozen assertion
        # about the author's current presentation defaults.
        output = self.compile_source(capture + lifecycle.document(probe, r"\ulRepeatBarMinimumGap{2pt}"))
        self.assertEqual(len(re.findall(r"REPEAT-GAP-PASS:", output)), 12)
        self.assertEqual(output.count("Repeat minimum gap suppressed a bar"), 1)


if __name__ == "__main__":
    unittest.main()
