-- SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
-- SPDX-License-Identifier: GPL-3.0-or-later
-- Fit alternate chords within lyric space and track physical-page usage for
-- the multikey manifest, embedded in PDF XMP and written as a JSON sidecar.

local M = {}
local songs, by_id = {}, {}
local finished = false
local shipping_page
local sp_per_bp = 65536 * 72.27 / 72

-- Raise a consistently prefixed error at the caller's location.
local function fail(message)
  error("ULSBS multikey: " .. message, 2)
end

local chord_width = luatexbase.new_attribute("ulsbs.multikey.chord_width")
local alternate_width = luatexbase.new_attribute("ulsbs.multikey.alternate_width")
local hlist_id = node.id("hlist")
local vlist_id = node.id("vlist")
local glyph_id = node.id("glyph")
local rule_id = node.id("rule")
local glue_id = node.id("glue")
local kern_id = node.id("kern")
local whatsit_id = node.id("whatsit")
local matrix_subtype = node.subtype("pdf_setmatrix")
local late_lua_subtype = node.subtype("late_lua")

-- Attributes survive the copies and nested boxes used by songs and melody
-- annotations. Tag only the explicit alternate wrapper, not its descendants.
function M.tag_chord(box_number, original, alternative)
  if original > 0 and alternative > 0 then
    local box = tex.box[box_number]
    node.set_attribute(box, chord_width, original)
    node.set_attribute(box, alternate_width, alternative)
  end
end

-- The original chord/lyric pair reserves max(chord width, lyric width). Only
-- a trailing chord chunk may borrow the spare lyric width: growing an earlier
-- chunk could cover a following chord, inline hint or other shared material.
-- Ignore paragraph spaces and broken-word hyphen padding, since they are not
-- a guaranteed part of this pair. No dimensions or t00 nodes are ever changed.
function M.fit_chords(box_number, lyric_width, minimum_scale)
  local chord = tex.box[box_number]
  if not chord or lyric_width <= chord.width then return end
  local candidates, rightmost = {}, 0

  -- Collect alternate wrappers and the rightmost non-chord content position.
  local function visit(box, x)
    for n in node.traverse(box.head) do
      if n.id == hlist_id then
        local original = node.has_attribute(n, chord_width)
        if original then
          candidates[#candidates + 1] = {box = n, x = x, original = original}
        else
          visit(n, x)
        end
        x = x + n.width
      elseif n.id == glue_id then
        x = x + node.effective_glue(n, box)
      elseif n.id == kern_id then
        x = x + n.kern
      else
        if n.id == glyph_id or n.id == rule_id or n.id == vlist_id then
          rightmost = math.max(rightmost, x + n.width)
        end
        x = x + (n.width or 0)
      end
    end
  end
  visit(chord, 0)
  for _, candidate in ipairs(candidates) do
    if candidate.x + candidate.original >= rightmost - 1 then
      -- Preserve songs' trailing chord separation (and any other padding),
      -- borrowing only the extra width already reserved by these lyrics.
      local available = candidate.original + lyric_width - chord.width
      local natural = node.has_attribute(candidate.box, alternate_width)
      local scale = math.max(minimum_scale, math.min(1, available / natural))
      -- This is our own wrapper's matrix, not any nested glyph scaling.
      for transform in node.traverse(candidate.box.head) do
        if transform.id == whatsit_id and transform.subtype == matrix_subtype then
          transform.data = string.format("%.8f 0 0 %.8f", scale, scale)
          break
        end
      end
    end
  end
end

-- Encode a JSON string with valid UTF-8 and XML-compatible Unicode values.
local function json_string(value)
  if type(value) ~= "string" then
    fail("expected a string")
  end
  if not utf8.len(value) then
    fail("manifest strings must be valid UTF-8")
  end
  -- Lua 5.3's UTF-8 library also accepts surrogate code points; XML does not.
  for _, codepoint in utf8.codes(value) do
    if codepoint >= 0xd800 and codepoint <= 0xdfff then
      fail("manifest strings must not contain Unicode surrogates")
    end
  end
  -- Escape JSON delimiters and control bytes without altering UTF-8 bytes.
  local escaped = value:gsub('[%z\1-\31\\"]', function(char)
    if char == '"' then return '\\"' end
    if char == '\\' then return '\\\\' end
    return string.format("\\u%04x", string.byte(char))
  end)
  -- These two valid Unicode values are forbidden literally in XML 1.0.
  escaped = escaped:gsub(utf8.char(0xfffe), "\\ufffe")
    :gsub(utf8.char(0xffff), "\\uffff")
  return '"' .. escaped .. '"'
end

-- Encode an optional string, using JSON null for an absent value.
local function nullable_string(value)
  if value == nil then return "null" end
  return json_string(value)
end

-- Encode a finite number in trimmed fixed-point JSON notation.
local function number(value)
  if type(value) ~= "number" or value ~= value or math.abs(value) == math.huge then
    fail("expected a finite number")
  end
  -- LuaTeX uses the C numeric locale; fixed-point also avoids exponent quirks.
  return string.format("%.8f", value):gsub("0+$", ""):gsub("%.$", "")
end

-- Resolve a registered occurrence while the manifest is still writable.
local function song_for(internal_id)
  local song = by_id[internal_id]
  if not song then fail("unknown internal song ID " .. tostring(internal_id)) end
  if finished then fail("manifest already finished") end
  return song
end

-- Registration order is document order. The internal ID never leaves Lua.
function M.begin_song(internal_id, song_id, occurrence, layer_prefix, original_key, key_labels)
  if finished then fail("manifest already finished") end
  if type(internal_id) ~= "string" or by_id[internal_id] then
    fail("invalid or duplicate internal song ID")
  end
  if type(song_id) ~= "string" or type(layer_prefix) ~= "string" then
    fail("song ID and layer prefix must be strings")
  end
  if type(occurrence) ~= "number" or occurrence < 1 or occurrence % 1 ~= 0 then
    fail("occurrence must be a positive integer")
  end
  if original_key ~= nil then json_string(original_key) end
  local labels
  if key_labels ~= nil then
    if type(key_labels) ~= "table" or #key_labels ~= 12 then
      fail("keyLabels must contain exactly twelve display strings")
    end
    labels = {}
    for i = 1, 12 do
      json_string(key_labels[i])
      labels[i] = key_labels[i]
    end
  end
  local song = {
    song_id = song_id,
    occurrence = occurrence,
    original_key = original_key,
    key_labels = labels,
    layer_prefix = layer_prefix,
    has_transposable_content = false,
    layer_pages = {},
  }
  songs[#songs + 1] = song
  by_id[internal_id] = song
end

-- Resolve and validate a zero-based page index within physical shipout.
local function physical_page_index(absolute_shipout_counter)
  if shipping_page == nil then
    fail("marked content outside physical page shipout (reusable PDF forms are unsupported)")
  end
  local page_index = status.total_pages
  if absolute_shipout_counter ~= nil then
    page_index = absolute_shipout_counter - 1
  end
  if type(page_index) ~= "number" or page_index < 0 or page_index % 1 ~= 0 then
    fail("tracking requires a physical shipout page index")
  end
  if page_index ~= shipping_page then fail("inconsistent physical shipout page index") end
  return page_index
end

-- Page-list sentinels exclude PDF form serialization, whose late Lua runs once
-- per form, not once per placement. Imported graphics remain inside our marks.
function M.start_page()
  if shipping_page ~= nil then fail("nested physical page shipout") end
  shipping_page = status.total_pages
end

-- Clear the physical-page sentinel after that page's late Lua has run.
function M.stop_page()
  if shipping_page == nil then fail("physical page shipout was not tracked") end
  shipping_page = nil
end

-- Reject untrackable leader content and bracket the shipout list with sentinels.
function M.track_page(box)
  if not box then fail("missing physical shipout box") end
  -- LuaTeX suppresses late Lua in leaders. Refuse those placements rather than
  -- silently omit their dependencies; ordinary copied boxes execute normally.
  -- Recursively detect usage markers inside leaders, including nested boxes.
  local function check_leaders(list, in_leader)
    for n in node.traverse(list) do
      if n.id == hlist_id or n.id == vlist_id then
        check_leaders(n.head, in_leader)
      elseif n.id == glue_id and n.leader then
        check_leaders(n.leader, true)
      elseif in_leader and n.id == whatsit_id and n.subtype == late_lua_subtype
        and type(n.data) == "string" and n.data:find("ulsbs_multikey.mark_used", 1, true) then
        fail("transposable content in TeX leaders has unknown page dependencies")
      end
    end
  end
  check_leaders(box.head, false)
  local first = node.new("whatsit", "late_lua")
  first.data = "ulsbs_multikey.start_page()"
  local last = node.new("whatsit", "late_lua")
  last.data = "ulsbs_multikey.stop_page()"
  box.head = node.insert_before(box.head, box.head, first)
  box.head = node.insert_after(box.head, node.tail(box.head), last)
end

-- Every alternative records its actual shipout, including hidden content and
-- copied boxes. OCG allocation and discarded measurement boxes record nothing.
function M.mark_used(internal_id, absolute_shipout_counter)
  local song = song_for(internal_id)
  song.layer_pages[physical_page_index(absolute_shipout_counter)] = true
  song.has_transposable_content = true
end

-- Call from late Lua at the header anchor, immediately after primitive savepos.
-- pdf.getpos() is in sp, with the PDF bottom-left origin already applied.
-- The optional override is LaTeX's one-based absolute shipout counter.
function M.anchor(internal_id, absolute_shipout_counter)
  local song = song_for(internal_id)
  if song.anchor then return end
  local x, y
  if type(pdf.getpos) == "function" then
    x, y = pdf.getpos()
  else
    x, y = tex.lastxpos, tex.lastypos
  end
  local page_index = physical_page_index(absolute_shipout_counter)
  number(x)
  number(y)
  song.page_index = page_index
  song.anchor = { x = x / sp_per_bp, y = y / sp_per_bp }
end

-- Serialize transposable occurrences with sorted, validated dependency pages.
local function manifest()
  local records = {}
  for _, song in ipairs(songs) do
    if song.has_transposable_content then
      local pages = {}
      for page in pairs(song.layer_pages) do
        if page >= status.total_pages then fail("dependency page was not shipped") end
        pages[#pages + 1] = page
      end
      table.sort(pages)
      if #pages == 0 then fail("transposable occurrence has no dependency pages") end
      local labels = "null"
      if song.key_labels then
        local entries = {}
        for k = 1, 12 do entries[k] = json_string(song.key_labels[k]) end
        labels = "[" .. table.concat(entries, ",") .. "]"
      end
      local anchor = "null"
      if song.anchor then
        anchor = '{"x":' .. number(song.anchor.x) .. ',"y":' .. number(song.anchor.y) .. '}'
      end
      records[#records + 1] = '{"song_id":' .. json_string(song.song_id)
        .. ',"occurrence":' .. number(song.occurrence)
        .. ',"original_key":' .. nullable_string(song.original_key)
        .. ',"key_labels":' .. labels
        .. ',"layer_prefix":' .. json_string(song.layer_prefix)
        .. ',"page_index":' .. (song.page_index and number(song.page_index) or "null")
        .. ',"anchor":' .. anchor
        .. ',"layer_page_indices":[' .. table.concat(pages, ",") .. ']'
        .. ',"has_transposable_content":' .. tostring(song.has_transposable_content) .. '}'
    end
  end
  return '{"has_multikey_info":true,"multikey_info":{"schema_version":2,'
    .. '"layer_protocol":"ulsbs:transpose:v1","coordinate_space":"pdf-user-space","songs":['
    .. table.concat(records, ",") .. ']}}'
end

-- Write the compile-status sidecar, checking both writing and closing errors.
local function write_status(json)
  local filename = tex.jobname .. ".ulsbs-multikey.json"
  local file, message = io.open(filename, "wb")
  if not file then fail("cannot open " .. filename .. ": " .. tostring(message)) end
  local written, write_message = file:write(json)
  local closed, close_message = file:close()
  if not written or not closed then
    fail("cannot write " .. filename .. ": " .. tostring(write_message or close_message))
  end
end

-- A lyric-mode or non-ULSBS source explicitly reports no renderer. This is not
-- interchangeable with a missing manifest, which could indicate a failed build.
function M.finish_disabled()
  if finished then return end
  write_status('{"has_multikey_info":false,"multikey_info":null}')
  finished = true
end

-- Run after the final page has shipped. Standard PDF Info is deliberately untouched.
function M.finish()
  if finished then return end
  if shipping_page ~= nil then fail("physical page shipout did not finish") end
  if type(pdf.getcatalog) ~= "function" or type(pdf.setcatalog) ~= "function" then
    fail("LuaTeX catalog inspection and update APIs are required")
  end
  local catalog = pdf.getcatalog() or ""
  -- Decode PDF name escapes before checking, so /Meta#64ata is also protected.
  local names = catalog:gsub("#(%x%x)", function(hex) return string.char(tonumber(hex, 16)) end)
  if names:find("/Metadata%f[%z%s/%[%]()<>{}]") or names:match("/Metadata$") then
    fail("catalog already has /Metadata; refusing to overwrite existing XMP")
  end
  local json = manifest()
  -- Internal compile artifact for publication merging; the PDF remains self-contained.
  write_status(json)
  local xml_json = json:gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;")
  local xmp = '<?xpacket begin="' .. utf8.char(0xfeff) .. '" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
    .. '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
    .. '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
    .. '<rdf:Description rdf:about="" xmlns:ulsbs="urn:ulsbs:multikey:1">\n'
    .. '<ulsbs:multikey>' .. xml_json .. '</ulsbs:multikey>\n'
    .. '</rdf:Description>\n</rdf:RDF>\n</x:xmpmeta>\n<?xpacket end="w"?>'
  local object = pdf.immediateobj("stream", xmp, "/Type /Metadata /Subtype /XML")
  pdf.setcatalog(catalog .. " /Metadata " .. object .. " 0 R")
  finished = true
end

return M
