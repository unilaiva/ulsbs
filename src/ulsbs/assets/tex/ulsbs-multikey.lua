-- SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
-- SPDX-License-Identifier: GPL-3.0-or-later
-- Lyric-safe chord fitting and a shipout-derived multikey manifest in XMP.

local M = {}
local songs, by_id = {}, {}
local finished = false
local sp_per_bp = 65536 * 72.27 / 72

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

local function nullable_string(value)
  if value == nil then return "null" end
  return json_string(value)
end

local function number(value)
  if type(value) ~= "number" or value ~= value or math.abs(value) == math.huge then
    fail("expected a finite number")
  end
  -- LuaTeX uses the C numeric locale; fixed-point also avoids exponent quirks.
  return string.format("%.8f", value):gsub("0+$", ""):gsub("%.$", "")
end

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
  }
  songs[#songs + 1] = song
  by_id[internal_id] = song
end

-- Call only from late Lua inside the actual marked-content box, not while sizing.
function M.mark_used(internal_id)
  song_for(internal_id).has_transposable_content = true
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
  local page_index = status.total_pages
  if absolute_shipout_counter ~= nil then
    page_index = absolute_shipout_counter - 1
  end
  if type(page_index) ~= "number" or page_index < 0 or page_index % 1 ~= 0 then
    fail("anchor requires a physical shipout page index")
  end
  number(x)
  number(y)
  song.page_index = page_index
  song.anchor = { x = x / sp_per_bp, y = y / sp_per_bp }
end

local function manifest()
  local records = {}
  for i, song in ipairs(songs) do
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
    records[i] = '{"song_id":' .. json_string(song.song_id)
      .. ',"occurrence":' .. number(song.occurrence)
      .. ',"original_key":' .. nullable_string(song.original_key)
      .. ',"key_labels":' .. labels
      .. ',"layer_prefix":' .. json_string(song.layer_prefix)
      .. ',"page_index":' .. (song.page_index and number(song.page_index) or "null")
      .. ',"anchor":' .. anchor
      .. ',"has_transposable_content":' .. tostring(song.has_transposable_content) .. '}'
  end
  return '{"has_multikey_info":true,"multikey_info":{"schema_version":1,'
    .. '"layer_protocol":"ulsbs:transpose:v1","coordinate_space":"pdf-user-space","songs":['
    .. table.concat(records, ",") .. ']}}'
end

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
