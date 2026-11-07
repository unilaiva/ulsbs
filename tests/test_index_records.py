# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Event snapshots, record normalization and shipout semantics."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from index_records import EVENT_SIGNATURE, SIGNATURE, index_events, read_snapshot


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src/ulsbs/assets/tex"
FIXTURES = ROOT / "tests/fixtures/index"
RUNNER = r'''
local assets, output = arg[1], arg[2]
kpse = {find_file = function(name) return assets .. "/" .. name end}
status = {output_directory = output}
texio = {write_nl = function(_, message) print(message) end}
local function read(path)
  local file = assert(io.open(path, "rb"))
  local bytes = file:read("*a")
  file:close()
  return bytes
end
local function write(path, bytes)
  local file = assert(io.open(path, "wb"))
  assert(file:write(bytes))
  assert(file:close())
end
local state = dofile(assets .. "/ulsbs-index-state.lua")
local codec = dofile(assets .. "/ulsbs-index-records.lua")
local sorter = dofile(assets .. "/ulsbs-index.lua")
local function render(title, label, target, kind, definitions)
  return sorter.render({{title=kind == "tag" and title or sorter.normalize_title(title),
    label=label, target=target, ordinal=1, line=1}}, kind or "title", definitions)
end
local function start(files, job, root)
  state.start(job or "book", files ~= false)
  state.declare("titles", "title", "idx_title")
  state.declare("tags", "tag", "idx_tag")
  state.declare("authors", "author", "idx_auth")
  state.begin_document(files ~= false, root or "book.tex")
end
local function collect(title)
  state.collect("titles", title or "The Apple", "7", "song1-7.1", "Chapter 2")
end
'''


class IndexRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("texlua") is None:
            raise unittest.SkipTest("texlua is required")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ulsbs-records-")
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        (self.work / "book.tex").write_text("stable source", encoding="utf-8")
        (self.work / "include").mkdir()
        shutil.copy2(FIXTURES / "tags.txt", self.work / "include/tags.txt")
        self.snapshot = self.work / "book.ulsbs-index-state"

    def run_lua(self, body, diagnostic=None):
        script = self.work / "runner.lua"
        script.write_text(RUNNER + body, encoding="utf-8")
        result = subprocess.run(
            ["texlua", str(script), str(ASSETS), str(self.work)],
            cwd=self.work, env=os.environ.copy(), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30,
            check=False,
        )
        if diagnostic is None:
            self.assertEqual(result.returncode, 0, result.stdout)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn(diagnostic, result.stdout)
        return result.stdout

    def seed(self):
        self.run_lua('start(); collect(); state.finish()')

    def rewrite_payload(self, transform):
        payload = self.snapshot.read_bytes().split(b"\n", 1)[1]
        payload = transform(payload)
        self.snapshot.write_bytes(hashlib.md5(payload).hexdigest().encode() + b"\n" + payload)

    def test_fresh_repeat_render_exact_and_no_sxd_dependency(self):
        output = self.run_lua('''
start()
write("idx_title.sxd", "POISONED")
assert(select(2, state.show("titles")) == nil)
collect()
state.finish()
assert(read("idx_title.sxd") == "POISONED")
start()
local name, path = state.show("titles")
assert(name == "idx_title.sbx" and path:match("/idx_title.sbx$"))
assert(read(path) == render("The Apple", "7", "song1-7.1"))
collect()
state.finish()
''')
        self.assertIn("No complete previous-pass data", output)
        self.assertEqual(output.count("Collected records changed"), 1)
        self.assertTrue(self.snapshot.read_bytes().split(b"\n", 1)[1].startswith(
            b"ULSBS index snapshot 3 fi-compatible-v1\n"))
        self.assertFalse((self.work / "idx_tag.sxd").exists())
        self.assertFalse((self.work / "idx_auth.sxd").exists())

    def test_arbitrary_unicode_and_tex_special_fields_roundtrip_as_data(self):
        self.run_lua(r'''
local text = "Åäö नमस्ते 中文 \\textbf{a} # & % ~ ^ _ $ :\n\0" .. 'os.execute("BAD")'
local event = {type = "record", title = text, label = text, target = text, chapter = text}
local decoded = codec.decode(codec.encode({event}), "title")[1]
for key, value in pairs(event) do assert(decoded[key] == value) end
start()
state.collect("titles", text, text, text, text)
state.finish()
start()
assert(not io.open("BAD", "rb"))
''')

    def test_stage_ship_once_and_unshipped_events_do_not_leak(self):
        self.run_lua('''
start()
state.stage("titles", "Not selected", "1", "omitted")
local event = state.stage("titles", "The Apple", "wrong page", "shipped", "chapter")
state.ship(event, "42")
state.ship(event, "99")
state.finish()
start()
local _, path = state.show("titles")
assert(read(path) == render("The Apple", "42", "shipped"))
''')

    def test_intentional_identical_records_remain_distinct(self):
        self.run_lua('''
start(); collect(); collect(); state.finish(); start()
local _, path = state.show("titles")
assert(read(path):find("\\\\\\\\\\\\ulSongLink{song1-7.1}{7}", 1, true))
''')

    def test_explicit_selection_occurrences_are_distinct_but_dry_copies_are_not(self):
        self.run_lua('''
start()
local event = state.stage("titles", "Selected", "1", "target")
state.replay = 1
state.ship(event); state.ship(event)
state.replay = 2
state.ship(event); state.ship(event)
state.replay = 0
state.finish()
''')
        events = read_snapshot(self.snapshot)["indices"]["titles"]["events"]
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0], events[1])

    def test_tex_spelling_normalizes_delimiters_without_evaluating_literal_pages(self):
        self.run_lua(r'''
start()
local event = state.stage("titles", {"Literal \\thepage"},
  {"\\textbf {", "}"}, "target", "", true)
state.ship(event, nil, "xii")
local raw = state.stage("titles", "\\word", "raw", "target")
state.ship(raw)
state.finish()
''')
        events = read_snapshot(self.snapshot)["indices"]["titles"]["events"]
        self.assertEqual(events[0]["title"], r"Literal \thepage ")
        self.assertEqual(events[0]["label"], r"\textbf {xii}")
        self.assertEqual(events[1]["title"], r"\word")

    def test_tex_spelling_preserves_unicode_control_words_and_control_symbols(self):
        self.run_lua(r'''
tex = {getcatcode = function(code) return code == 233 and 11 or 12 end}
start()
local event = state.stage("titles", "\\Chanté \\© नमस्ते", "1", "target", "", true)
state.ship(event)
state.finish()
''')
        event, = read_snapshot(self.snapshot)["indices"]["titles"]["events"]
        self.assertEqual(event["title"], "\\Chanté \\© नमस्ते")

    def test_page_templates_are_literal_copied_parts_resolved_only_at_shipout(self):
        self.run_lua(r'''
start()
local title = {"The page ", " and ", ""}
local event = state.stage("titles", title, {"\\textbf{", "}"}, {"target-", ""}, {"chapter-", ""})
title[1] = "MUTATED"
state.ship(event, nil, "xii")
state.finish(); start()
local _, path = state.show("titles")
assert(read(path) == sorter.render({{title="Page xii and xii,~The", label="\\textbf{xii}",
  target="target-xii", chapter="chapter-xii", ordinal=1, line=1}}, "title"))
''')

    def test_page_template_diagnostics(self):
        for body, diagnostic in (
            ('state.stage("titles", {}, "1", "x")', "Empty page template"),
            ('state.stage("titles", {[2]="hole"}, "1", "x")', "Sparse page template"),
            ('state.stage("titles", {bad="key"}, "1", "x")', "Invalid page template"),
            ('local h = state.stage("titles", {"page ", ""}, "1", "x"); state.ship(h)',
             "shipout page label for staged template must be a string"),
        ):
            with self.subTest(diagnostic=diagnostic):
                self.snapshot.unlink(missing_ok=True)
                self.run_lua('start(); ' + body, diagnostic)

    def test_label_override_bypasses_template_and_failed_ship_can_retry(self):
        self.run_lua(r'''
start()
local event = state.stage("titles", "Apple", {"unresolved ", ""}, "target")
assert(not pcall(state.ship, event))
state.ship(event, "")
state.ship(event, "duplicate")
state.finish(); start()
local _, path = state.show("titles")
assert(read(path) == render("Apple", "", "target"))
''')

    def test_real_late_lua_shipout_resolves_page_and_deduplicates_box_copies(self):
        if shutil.which("lualatex") is None:
            self.skipTest("LuaLaTeX is required for actual shipout")
        source = r'''
\documentclass{article}
\directlua{
  state = dofile(assert(kpse.find_file("ulsbs-index-state.lua", "tex")))
  state.start("book", true)
  state.declare("titles", "title", "idx_title")
}
\begin{document}
\directlua{
  state.begin_document(true, "book.tex")
  assert(state.stage("titles", "Never shipped", "0", "omitted") == 1)
  assert(state.stage("titles", "The Apple", {"page ", ""}, "shipped") == 2)
}
\setbox0=\vbox{Real box\latelua{state.ship(2, nil, tostring(tex.count[0]))}}
\setbox1=\copy0
\box1\clearpage
\box0\clearpage
\directlua{state.finish()}
\end{document}
'''
        (self.work / "book.tex").write_text(source)
        env = os.environ.copy()
        cache = self.work / "cache"
        cache.mkdir()
        env.update(TEXINPUTS=f"{ASSETS}//{os.pathsep}",
                   LUAINPUTS=f"{ASSETS}//{os.pathsep}",
                   TEXMFVAR=str(cache), TEXMFCACHE=str(cache))
        result = subprocess.run(
            ["lualatex", "-halt-on-error", "-interaction=nonstopmode", "book.tex"],
            cwd=self.work, env=env, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=120, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.run_lua(r'''
state.start("book", true)
state.declare("titles", "title", "idx_title")
state.begin_document(true, "book.tex")
local _, path = state.show("titles")
assert(read(path) == render("The Apple", "page 1", "shipped"))
''')

    def test_directives_preserve_event_order_and_prefix_rotation(self):
        self.run_lua('''
start()
collect("The Apple")
state.directive("titles", "prefix", "Le")
collect("The Zebra")
collect("*Le arbre")
state.directive("authors", "sep", "and")
state.directive("authors", "after", "by")
state.directive("authors", "ignore", "unknown")
state.finish(); start()
local _, path = state.show("titles")
local output = read(path)
assert(output:find("\\\\ulIndexDisplayEntry{Apple,~The}", 1, true))
assert(output:find("\\\\ulIndexDisplayEntry{The Zebra}", 1, true))
assert(output:find("\\\\ulIndexDisplayAltEntry{Arbre,~Le}", 1, true))
''')

    def test_normalization_handles_articles_edge_spaces_and_control_spaces(self):
        self.run_lua(r'''
for _, pair in ipairs({{"  The apple  ", "Apple,~The"}, {"*  The apple ", "*Apple,~The"},
    {"The apple\\ ", "Apple\\ ,~The"},
    {"  Ääni", "Ääni"}, {"*A song", "*Song,~A"}, {"A", "A"}}) do
  assert(sorter.normalize_title(pair[1]) == pair[2], pair[1])
end
assert(sorter.normalize_title("Le soleil", {LE=true}) == "Soleil,~Le")
assert(sorter.normalize_title("Le soleil") == "Le soleil")
''')

    def test_author_default_splitting_grouping_tokens_and_attribution(self):
        self.run_lua(r'''
local cases = {
  {"Alice, Bob; Carol AnD David", {"Alice", "Bob", "Carol", "David"}},
  {"Anderson and Sandy and Candy", {"Anderson", "Sandy", "Candy"}},
  {"Rock-and-Roll and stand-by-band; D'and and by'Name",
    {"Rock-and-Roll", "stand-by-band", "D'and", "by'Name"}},
  {" Words by Alice; Music BY Bob; version by old by Carol", {"Alice", "Bob", "Carol"}},
  {"Traditional 1899; Words Alice", {"Traditional 1899", "Words Alice"}},
  {"{Family, Given} and {Organization and Friends, Inc.}",
    {"{Family, Given}", "{Organization and Friends, Inc.}"}},
  {"\\textbf {Alice, Bob and Carol}; David\\, Jr. and E\\; F",
    {"\\textbf {Alice, Bob and Carol}", "David\\, Jr.", "E\\; F"}},
  {"\\and Alice; \\by Bob; {by Carol} and Alice\\ and Bob",
    {"\\and Alice", "\\by Bob", "{by Carol}", "Alice\\ and Bob"}},
  {"\n Alice \n and\t Bob ; ;, Alice, *Alice", {"Alice", "Bob", "*Alice"}},
  {"", {}}, {" \n\t ", {}}, {", ; and ; by ", {}},
  {"Alice\\ ", {"Alice\\ "}},
  {"\\AuthorName; \\&; *", {"\\AuthorName", "\\&", "*"}},
  {"\\textbf and Alice; \\textbf {Bob and Carol}",
    {"\\textbf and Alice", "\\textbf {Bob and Carol}"}},
}
local open, locale = io.open, os.setlocale
io.open = function() error("author parser accessed filesystem") end
os.setlocale = function() error("author parser accessed locale") end
for _, case in ipairs(cases) do
  local names = sorter.normalize_authors(case[1])
  assert(#names == #case[2], case[1] .. ": " .. table.concat(names, "|"))
  for i, expected in ipairs(case[2]) do assert(names[i] == expected, names[i]) end
end
io.open, os.setlocale = open, locale
''')

    def test_author_policy_stream_fans_out_without_mutation_or_retained_state(self):
        self.run_lua(r'''
local events = {}
local function record(text)
  events[#events + 1] = {type="record", title=text, label="7", target="song", chapter="chapter"}
end
local function directive(name, value)
  events[#events + 1] = {type="directive", name=name, value=value}
end
record("Words by Alice and Bob, Alice")
directive("sep", "et")
record("Alice and Bob et Carol")
directive("sep", "und")
directive("after", "par")
record("Words by Alice et Words par Bob und Carol")
directive("after", "von")
directive("ignore", "\\textbf{UNKNOWN}")
directive("ignore", "")
record("unknown et Unknown Person und Words von David et \\emph{unknown}")
record("Alice et Alice")
record("Alice")
local encoded = codec.encode(events)
local records = codec.normalize(events, "author", sorter)
local expected = {"Alice", "Bob", "Alice and Bob", "Carol", "Words by Alice", "Bob", "Carol",
  "Unknown Person", "David", "Alice", "Alice"}
assert(#records == #expected)
for i, name in ipairs(expected) do
  local record = records[i]
  assert(record.title == name, record.title)
  assert(record.ordinal == i and record.label == "7" and record.target == "song" and record.chapter == "chapter")
end
assert(records[1].line == 1 and records[3].line == 3 and records[10].line == 11)
assert(codec.encode(events) == encoded, "normalization mutated source events")
sorter.render(records, "author")
assert(codec.encode(events) == encoded, "render mutated source events")
records = codec.normalize(events, "author", sorter)
records[1].title = "MUTATED"
assert(codec.normalize(events, "author", sorter)[1].title == "Alice")
assert(codec.normalize({{type="record", title="Words by Alice and Bob", label="", target="", chapter=""}},
  "author", sorter)[2].title == "Bob", "custom policy leaked")
''')

    def test_author_ignore_is_whole_cleaned_unicode_name_not_substring(self):
        self.run_lua(r'''
local names = sorter.normalize_authors("ÄÄNI and \\emph{ääni}; Ääni Person; Person Ääni", nil, nil,
  {[sorter.author_word(" {Ääni} ")]=true})
assert(#names == 2 and names[1] == "Ääni Person" and names[2] == "Person Ääni")
assert(#sorter.normalize_authors("Alice; Alice; alice") == 2)
''')

    def test_author_empty_first_directives_clear_defaults_and_later_values_add(self):
        self.run_lua(r'''
local events = {
  {type="directive", name="sep", value=""},
  {type="directive", name="after", value=""},
  {type="directive", name="ignore", value=""},
  {type="record", title="Words by Alice and Bob", label="", target="", chapter=""},
  {type="directive", name="sep", value="ET"},
  {type="directive", name="after", value="PAR"},
  {type="record", title="Words par Carol et David", label="", target="", chapter=""},
}
local records = codec.normalize(events, "author", sorter)
assert(#records == 3 and records[1].title == "Words by Alice and Bob")
assert(records[2].title == "Carol" and records[3].title == "David")
''')

    def test_author_malformed_directive_and_group_diagnostics(self):
        for body, diagnostic in (
            (r'codec.directive("author", "sep", "\\evil")', "one literal word"),
            ('codec.directive("author", "after", "two words")', "one literal word"),
            ('sorter.normalize_authors("{Alice")', "unclosed group"),
            ('sorter.normalize_authors("Alice}")', "unmatched closing brace"),
        ):
            with self.subTest(body=body):
                self.run_lua(body, diagnostic)

    def test_tags_aliases_exact_render_and_author_normalization(self):
        self.run_lua('''
start()
state.collect("tags", "fire", "8", "song1-8.1", "chapter")
state.collect("authors", "Alice and Bob", "8", "song1-8.1", "chapter")
state.finish(); start()
local _, path = state.show("tags")
assert(read(path) == render("fire", "8", "song1-8.1", "tag", read("include/tags.txt")))
local events = {{type="record", title="Alice and Bob", label="8", target="song1-8.1", chapter="chapter"}}
local records = codec.normalize(events, "author", sorter)
assert(#records == 2 and records[1].title == "Alice" and records[2].title == "Bob")
local _, author_path = state.show("authors")
assert(read(author_path) == sorter.render(records, "author"))
''')

    def test_unknown_tag_diagnostic(self):
        self.run_lua('start(); state.collect("tags", "not-a-tag", "8", "x"); state.finish(); start(); state.show("tags")',
                     "unknown tag 'not-a-tag'")

    def test_unknown_index_and_directive_diagnostics(self):
        for body, diagnostic in (
            ('state.collect("missing", "t", "1", "x")', "Unknown index identifier: missing"),
            ('state.directive("titles", "unknown", "x")', "unknown directive 'unknown'"),
            ('state.directive("tags", "prefix", "x")', "unknown directive 'prefix'"),
            ('state.show("missing")', "Unknown index identifier: missing"),
            ('state.ship(100)', "Unknown staged index event: 100"),
            ('state.collect("titles", string.char(255), "1", "x")', "invalid UTF-8"),
        ):
            with self.subTest(body=body):
                self.snapshot.unlink(missing_ok=True)
                self.run_lua('start(); ' + body, diagnostic)

    def test_nofiles_does_not_modify_snapshot_or_collect(self):
        self.seed()
        before = self.snapshot.read_bytes()
        self.run_lua('start(false); collect(); state.finish()')
        self.assertEqual(self.snapshot.read_bytes(), before)
        self.run_lua('start(false); state.show("titles")', "with \\nofiles")

    def test_source_change_discards_previous_before_display(self):
        self.seed()
        (self.work / "book.tex").write_text("changed source")
        output = self.run_lua('start(); assert(select(2, state.show("titles")) == nil); collect(); state.finish()')
        self.assertIn("Source identity changed", output)
        self.assertIn("No complete previous-pass data", output)

    def test_changed_records_require_rerun(self):
        self.seed()
        output = self.run_lua('start(); state.show("titles"); collect("Banana"); state.finish()')
        self.assertIn("Collected records changed for titles", output)

    def test_read_before_collecting_marker_and_aborted_pass_diagnostic(self):
        self.seed()
        self.run_lua('start(); local _, path = state.show("titles"); assert(read(path):find("Apple"))')
        self.assertIn(b"10:collecting", self.snapshot.read_bytes())
        self.run_lua('start()', "Aborted earlier index pass")

    def test_checksum_schema_job_and_malformed_event_diagnostics(self):
        for transform, diagnostic in (
            (lambda b: b.replace(b"snapshot 3", b"snapshot 2"), "Unsupported index snapshot/locale"),
            (lambda b: b.replace(b"4:book", b"4:else", 1), "belongs to another job"),
            (lambda b: b.replace(b"records 1", b"records 9"), "unsupported index record version"),
            (lambda b: b.replace(b"6:record", b"6:broken"), "unknown event type 'broken'"),
            (lambda b: b[:-1], "Truncated"),
        ):
            with self.subTest(diagnostic=diagnostic):
                self.snapshot.unlink(missing_ok=True)
                self.seed()
                self.rewrite_payload(transform)
                self.run_lua('start()', diagnostic)
        self.snapshot.write_bytes(b"bad checksum\nno executable data")
        self.run_lua('start()', "Malformed or incomplete")

    def test_codec_rejects_truncation_unknown_directive_and_invalid_utf8(self):
        for expression, diagnostic in (
            ('"ULSBS index records 1\\n99:x"', "truncated event field"),
            ('"ULSBS index records 1\\nx"', "malformed length-prefixed"),
            ('"ULSBS index records 1\\n9:directive3:bad1:x"', "unknown directive 'bad'"),
            ('"ULSBS index records 1\\n6:record1:" .. string.char(255) .. "0:0:0:"', "invalid UTF-8"),
        ):
            with self.subTest(diagnostic=diagnostic):
                self.run_lua('codec.decode(' + expression + ', "title")', diagnostic)

    def test_declaration_drift_is_actionable(self):
        self.seed()
        self.run_lua('state.start("book", true); state.declare("titles", "tag", "idx_title")',
                     "Stale index declaration for titles")


class SnapshotDecoderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ulsbs-snapshot-decoder-")
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.path = self.work / "book.ulsbs-index-state"

    @staticmethod
    def field(value):
        value = value.encode() if isinstance(value, str) else value
        return str(len(value)).encode() + b":" + value

    def payload(self, *, job="book", state="complete", kind="title", event_type="record",
                values=("Åäö \\emph{Title} # & %", "\\textbf{7}", "song1-7.1", "chapter")):
        events = EVENT_SIGNATURE + self.field(event_type) + b"".join(map(self.field, values))
        return SIGNATURE + b"".join(map(self.field, (
            job, state, "book.tex", hashlib.md5(b"source").hexdigest(),
            "titles", kind, "idx_title", events)))

    def publish(self, payload):
        self.path.write_bytes(hashlib.md5(payload).hexdigest().encode() + b"\n" + payload)

    def test_decoder_retains_exact_fields_and_event_order(self):
        self.publish(self.payload())
        snapshot = read_snapshot(self.path)
        self.assertEqual(snapshot["job"], "book")
        self.assertEqual(snapshot["source"], "book.tex")
        self.assertEqual(snapshot["sourcehash"], hashlib.md5(b"source").hexdigest())
        self.assertEqual(snapshot["indices"]["titles"], {
            "kind": "title", "filename": "idx_title", "events": [{
                "type": "record", "title": "Åäö \\emph{Title} # & %", "label": "\\textbf{7}",
                "target": "song1-7.1", "chapter": "chapter"}]})
        self.assertEqual(index_events(self.work, "idx_title"), snapshot["indices"]["titles"]["events"])

    def test_decoder_rejects_checksum_schema_completion_and_provenance_errors(self):
        for payload, diagnostic in (
            (self.payload().replace(b"snapshot 3", b"snapshot 2"), "snapshot version"),
            (self.payload(state="collecting"), "Incomplete index pass"),
            (self.payload(kind="unknown"), "Unknown index kind"),
            (self.payload(event_type="unknown"), "Unknown index event type"),
            (self.payload(event_type="directive", values=("bad", "x")), "Unknown index directive"),
            (self.payload().replace(b"records 1", b"records 9"), "event version"),
            (self.payload()[:-1], "Truncated index field"),
            (SIGNATURE + self.field("book"), "Incomplete index fields"),
            (self.payload(values=("title", "label", "target")), "Incomplete index fields"),
            (self.payload(values=(b"\xff", "label", "target", "")), "utf-8"),
        ):
            with self.subTest(diagnostic=diagnostic):
                self.publish(payload)
                with self.assertRaisesRegex(ValueError, diagnostic):
                    read_snapshot(self.path)
        self.path.write_bytes(b"missing checksum")
        with self.assertRaisesRegex(ValueError, "Missing index checksum"):
            read_snapshot(self.path)
        self.publish(self.payload())
        self.path.write_bytes(self.path.read_bytes() + b"corrupt")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            read_snapshot(self.path)
        self.publish(self.payload(job="another"))
        with self.assertRaisesRegex(ValueError, "another job"):
            index_events(self.work, "idx_title")

    def test_decoder_rejects_duplicate_identifier_and_filename(self):
        payload = self.payload()
        declaration = b"".join(map(self.field, ("titles", "title", "idx_title")))
        entry = payload[payload.index(declaration):]
        self.publish(payload + entry)
        with self.assertRaisesRegex(ValueError, "Duplicate index declaration"):
            read_snapshot(self.path)
        self.publish(payload + entry.replace(self.field("titles"), self.field("other"), 1))
        with self.assertRaisesRegex(ValueError, "Duplicate index filename"):
            read_snapshot(self.path)

    def test_decoder_preserves_multiline_record_and_chapter_fields(self):
        self.publish(self.payload(values=("arbitrary\ntitle", "7", "target", "chapter\ncontext")))
        self.assertEqual(read_snapshot(self.path)["indices"]["titles"]["events"][0]["title"],
                         "arbitrary\ntitle")
        self.assertEqual(index_events(self.work, "idx_title")[0]["chapter"], "chapter\ncontext")


if __name__ == "__main__":
    unittest.main()
