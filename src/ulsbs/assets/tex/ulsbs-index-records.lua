-- SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Index event codec.
-- This file is part of the 'ulsbs' package.
--
-- Strings are UTF-8 byte-length-prefixed data, never executable Lua/TeX;
-- the enclosing snapshot owns checksum and job provenance.
-- Loaded by ulsbs-index-state.lua for collection validation, snapshot replay and
-- normalization before sorting. This module keeps no document state: event order
-- belongs to the caller and is preserved through encoding and decoding.

local M = {}
local signature = "ULSBS index records 1\n"
local fields = {record = {"title", "label", "target", "chapter"},
  directive = {"name", "value"}}

-- Raise a codec-owned error without adding a Lua source location.
local function fail(message)
  error("ULSBS index records: " .. message, 0)
end

-- Return value unchanged if it is a UTF-8 string; otherwise report description.
-- Validation permits embedded newlines and delimiters; framing uses byte counts.
function M.string(value, description)
  if type(value) ~= "string" then fail(description .. " must be a string") end
  local length, position = utf8.len(value)
  if not length then fail(description .. " contains invalid UTF-8 at byte " .. position) end
  return value
end

-- Validate directive strings and the kind/name pairing; return nothing and do
-- not apply it. Separator/after markers must be single literal words.
function M.directive(kind, name, value)
  M.string(name, "directive name")
  M.string(value, "directive value")
  if not ((kind == "title" and name == "prefix") or
      (kind == "author" and (name == "sep" or name == "after" or name == "ignore"))) then
    fail("unknown directive '" .. name .. "' for " .. tostring(kind) .. " index")
  end
  if kind == "author" and name ~= "ignore" and value ~= "" and
      not unicode.utf8.match(value, "^%a+$") then
    fail("author " .. name .. " directive requires one literal word or an empty value; no TeX commands or punctuation")
  end
end

-- Return versioned bytes for an ordered array of record/directive events.
-- Each event starts with its framed type followed by the fixed fields above;
-- there is no separator between fields and no executable serialization.
function M.encode(events)
  local parts = {signature}
  -- Append one validated string, counting UTF-8 bytes rather than characters.
  local function put(value)
    M.string(value, "event field")
    parts[#parts + 1] = tostring(#value) .. ":" .. value
  end
  for _, event in ipairs(events) do
    local names = fields[event.type]
    if not names then fail("unknown event type '" .. tostring(event.type) .. "'") end
    put(event.type)
    for _, name in ipairs(names) do put(event[name]) end
  end
  return table.concat(parts)
end

-- Return newly allocated events from exactly one versioned byte stream. Reject
-- bad framing, truncation, invalid UTF-8 and directives unsupported for kind.
function M.decode(bytes, kind)
  if type(bytes) ~= "string" or bytes:sub(1, #signature) ~= signature then
    fail("unsupported index record version")
  end
  local position, events = #signature + 1, {}
  -- Consume one field at position; embedded ':' or LF bytes are ordinary data.
  local function take()
    local first, last, digits = bytes:find("(%d+):", position)
    if first ~= position then fail("malformed length-prefixed event field") end
    local count = tonumber(digits)
    if not count or count > #bytes - last then fail("truncated event field") end
    local value = bytes:sub(last + 1, last + count)
    position = last + count + 1
    return M.string(value, "event field")
  end
  while position <= #bytes do
    local event = {type = take()}
    local names = fields[event.type]
    if not names then fail("unknown event type '" .. event.type .. "'") end
    for _, name in ipairs(names) do event[name] = take() end
    if event.type == "directive" then M.directive(kind, event.name, event.value) end
    events[#events + 1] = event
  end
  return events
end

-- Return fresh renderer records without mutating events; sorter supplies title
-- normalization. First custom policies replace defaults, later words extend
-- them, and earlier records stay fixed. Author events fan out into fresh names.
-- ordinal counts normalized names; line is the source event diagnostic index.
function M.normalize(events, kind, sorter)
  local records, prefixes, custom = {}, {A = true, THE = true}, false
  local policies = {sep = {AND = true}, after = {BY = true}, ignore = {}}
  local configured = {}
  for i, event in ipairs(events) do
    if event.type == "directive" then
      M.directive(kind, event.name, event.value)
      if kind == "title" then
        if not custom then prefixes, custom = {}, true end
        prefixes[unicode.utf8.upper(event.value)] = true
      elseif kind == "author" then
        local name = event.name
        if not configured[name] then policies[name], configured[name] = {}, true end
        local word = name == "ignore" and sorter.author_word(event.value) or unicode.utf8.upper(event.value)
        if word ~= "" then policies[name][word] = true end
      end
    else
      local names = kind == "author" and sorter.normalize_authors(event.title,
        policies.sep, policies.after, policies.ignore) or
        {kind == "title" and sorter.normalize_title(event.title, prefixes) or event.title}
      for _, name in ipairs(names) do
        records[#records + 1] = {
          title = name, label = event.label, target = event.target, chapter = event.chapter,
          ordinal = #records + 1, line = i,
        }
      end
    end
  end
  return records
end

return M
