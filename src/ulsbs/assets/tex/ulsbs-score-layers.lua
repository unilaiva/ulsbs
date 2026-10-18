-- SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
-- SPDX-License-Identifier: GPL-3.0-or-later
-- Write private draft-pass score-variant requests to <jobname>.ulsbs-scores.json:
-- snippet and song-occurrence identities, titles, source keys and target tonics.

local M = {}
local requests, seen = {}, {}

-- Validate UTF-8 and encode a JSON string for the private request sidecar.
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
local function integer(value, maximum)
  assert(type(value) == "number" and value % 1 == 0
    and value >= 0 and value <= maximum, "ULSBS scores: invalid key tuple")
  return tostring(value)
end

-- Encode a tonic tuple, optionally with mode, or null for an unknown key.
local function tonic(value, with_mode)
  if value == nil then return "null" end
  local result = '{"letter":' .. integer(value.letter, 6)
    .. ',"pitch":' .. integer(value.pitch, 11)
  if with_mode then result = result .. ',"minor":' .. integer(value.minor, 1) end
  return result .. '}'
end

-- Record each snippet/occurrence once, requiring twelve targets for known keys.
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
function M.finish()
  local filename = tex.jobname .. ".ulsbs-scores.json"
  local file = assert(io.open(filename, "w"))
  assert(file:write('{"schema_version":1,"requests":['
    .. table.concat(requests, ',') .. ']}\n'))
  assert(file:close())
end

return M
