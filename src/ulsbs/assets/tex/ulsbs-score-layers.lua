-- SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Engraving requests and page-local fitting for layered score alternatives.
-- This file is part of the 'ulsbs' package.
--
-- Write private draft-pass score-variant requests to <jobname>.ulsbs-scores.json:
-- snippet and song-occurrence identities, titles, source keys and target tonics.
-- Loaded by ulsbs-score-layers.tex as ulsbs_score_layers. Its TeX helpers call
-- request with already resolved key tuples; an enddocument/afterlastpage hook
-- calls finish. Python consumes the draft requests between draft/full passes,
-- engraves alternatives and supplies variant dispatch bindings. Full passes
-- adjust alternate drawing matrices on the physical page, after layout.
-- requests preserves first-seen order and seen deduplicates each snippet within
-- a layer-prefix occurrence. State lasts for this module load/LuaLaTeX pass;
-- finish writes it but does not clear it or prevent subsequent requests.

local M = {}
local requests, seen = {}, {}
local selection_requests, selection_seen = {}, {}
local alternatives, alternative_attribute = {}, nil

-- Tag a zero-advance matrix wrapper with its score-placement/key group and
-- largest scale that fits the system's displayed original. Attributes survive
-- copies and splits of the retained song boxes.
function M.tag_alternative(box_number, group, scale)
  if not alternative_attribute then
    alternative_attribute = luatexbase.new_attribute("ulsbs.score.alternative")
  end
  local id = #alternatives + 1
  alternatives[id] = {group = group, scale = scale}
  node.set_attribute(tex.box[box_number], alternative_attribute, id)
end

-- Fit each score/key independently on this physical page. Every candidate
-- keeps its original slot, so the tightest slot bounds the shared scale. Only
-- alternate matrices are changed; originals and TeX dimensions are untouched.
function M.fit_page(page)
  if not alternative_attribute then return end
  local scales, pending = {}, {}
  local whatsit_id, matrix_subtype = node.id("whatsit"), node.subtype("pdf_setmatrix")
  local function visit(list)
    for box in node.traverse_list(list) do
      local id = node.has_attribute(box, alternative_attribute)
      if id then
        local alternative = alternatives[id]
        local group, scale = alternative.group, alternative.scale
        scales[group] = math.min(scales[group] or 1, scale)
        for n in node.traverse_id(whatsit_id, box.head) do
          if n.subtype == matrix_subtype then
            pending[#pending + 1] = {matrix = n, group = group}
            break
          end
        end
      else
        visit(box.head)
      end
    end
  end
  visit(page.head)
  for _, item in ipairs(pending) do
    local scale = scales[item.group]
    item.matrix.data = string.format("%.10f 0 0 %.10f", scale, scale)
  end
end

-- Validate UTF-8 and encode a JSON string for the private request sidecar.
-- Return a quoted JSON value; invalid type/encoding raises an assertion.
local function json_string(value)
  assert(type(value) == "string" and utf8.len(value),
    "ULSBS scores: expected a UTF-8 string")
  -- Escape JSON delimiters and control bytes, preserving other UTF-8 bytes.
  return '"' .. value:gsub('[%z\1-\31\\"]', function(char)
    if char == '"' then return '\\"' end
    if char == '\\' then return '\\\\' end
    return string.format("\\u%04x", string.byte(char))
  end) .. '"'
end

-- Validate and encode a nonnegative integer within a key component's range.
-- Return decimal text; maximum is inclusive and invalid values assert.
local function integer(value, maximum)
  assert(type(value) == "number" and value % 1 == 0
    and value >= 0 and value <= maximum, "ULSBS scores: invalid key tuple")
  return tostring(value)
end

-- Encode a tonic tuple, optionally with mode, or null for an unknown key.
-- value uses zero-based letter 0..6 and pitch 0..11; with_mode additionally
-- requires minor 0/1. Return JSON without altering the caller's tuple.
local function tonic(value, with_mode)
  if value == nil then return "null" end
  local result = '{"letter":' .. integer(value.letter, 6)
    .. ',"pitch":' .. integer(value.pitch, 11)
  if with_mode then result = result .. ',"minor":' .. integer(value.minor, 1) end
  return result .. '}'
end

-- Record each snippet/occurrence once, requiring twelve targets for known keys.
-- snippet_id identifies the score; layer_prefix scopes it to a song occurrence.
-- song_id/title are diagnostic metadata, not deduplication keys. key contains
-- letter/pitch/minor; targets is t00..t11 in array slots 1..12 with letter/pitch.
-- Unknown keys require nil targets. Append encoded data on the first identity
-- only; duplicate calls return before validation, retaining the first request.
function M.request(snippet_id, layer_prefix, song_id, title, key, targets)
  local identity = layer_prefix .. "/" .. snippet_id
  if seen[identity] then return end
  local encoded_targets = "null"
  if key ~= nil then
    assert(type(targets) == "table" and #targets == 12,
      "ULSBS scores: expected twelve target tonics")
    local values = {}
    for i, target in ipairs(targets) do values[i] = tonic(target, false) end
    encoded_targets = '[' .. table.concat(values, ',') .. ']'
  else
    assert(targets == nil, "ULSBS scores: unknown key must have null targets")
  end
  requests[#requests + 1] = '{"snippet_id":' .. json_string(snippet_id)
    .. ',"layer_prefix":' .. json_string(layer_prefix)
    .. ',"song_id":' .. json_string(song_id)
    .. ',"title":' .. json_string(title)
    .. ',"key":' .. tonic(key, true) .. ',"targets":' .. encoded_targets .. '}'
  seen[identity] = true
end

-- Write the accumulated private requests as a schema-versioned JSON sidecar.
-- Replace the job-local file even when requests is empty; assert on I/O errors.
-- Unlike the public multikey envelope, this schema-1 artifact requests work and
-- makes no assertion about final shipout pages or accepted score alternatives.
function M.finish()
  local filename = tex.jobname .. ".ulsbs-scores.json"
  local file = assert(io.open(filename, "w"))
  assert(file:write('{"schema_version":1,"requests":['
    .. table.concat(requests, ',') .. ']}\n'))
  assert(file:close())
end

-- Ordinary selection requests identify the original graphics without wrapping
-- or re-engraving scores in books that have no effective key overrides.
function M.request_selection(file, graphic, song_id, title, key, target)
  local source, destination = tonic(key, true), tonic(target, true)
  local identity = table.concat({file, graphic, source, destination}, "\0")
  if selection_seen[identity] then return end
  selection_seen[identity] = true
  selection_requests[#selection_requests + 1] = '{"file":' .. json_string(file)
    .. ',"graphic":' .. json_string(graphic) .. ',"song_id":' .. json_string(song_id)
    .. ',"title":' .. json_string(title) .. ',"key":' .. source .. ',"target":' .. destination .. '}'
end

function M.finish_selection()
  if #selection_requests == 0 then return end
  local file = assert(io.open(tex.jobname .. ".ulsbs-selection-scores.json", "w"))
  assert(file:write('{"schema_version":1,"requests":['
    .. table.concat(selection_requests, ',') .. ']}\n'))
  assert(file:close())
end

return M
