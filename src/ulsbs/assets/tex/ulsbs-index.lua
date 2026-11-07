-- SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Pure index sorting and rendering.
-- This file is part of the 'ulsbs' package.
--
-- Index conventions follow songidx.lua (C) 2018 Kevin W. Hamlen, GPL-2.0-or-later.
-- See the README acknowledgement for the ULSBS derivative-work account.
--
-- No files, TeX callbacks or locale changes are involved.
-- The caller owns snapshot provenance and publication.
-- Loaded with dofile by ulsbs-index-state.lua, which passes decoded, normalized
-- previous-pass records to render and writes its returned TeX fragment. Module
-- tables below are fixed collation data, not per-document collection state.

local M = {}
local U = unicode.utf8

-- Abort with an owned diagnostic; callers may wrap it with the index identifier.
local function fail(message)
  error("ULSBS index: " .. message, 0)
end

-- Validate UTF-8 bytes and return CRLF/LF lines, accepting a missing final LF.
-- description identifies the input in errors; no input file is opened here.
local function lines(bytes, description)
  if type(bytes) ~= "string" then fail(description .. " bytes are required") end
  local length, position = utf8.len(bytes)
  if not length then fail(description .. " contains invalid UTF-8 at byte " .. position) end
  local result = {}
  for line in (bytes .. (bytes:sub(-1) == "\n" and "" or "\n")):gmatch("(.-)\n") do
    result[#result + 1] = line:gsub("\r$", "")
  end
  return result
end

-- Return s without Unicode whitespace at either end.
local function trim(s)
  return U.match(s, "^%s*(.-)%s*$")
end

-- Lexicographically compare numeric arrays, returning -1, 0 or 1; prefixes sort first.
local function compare_array(a, b)
  for i = 1, math.min(#a, #b) do
    if a[i] ~= b[i] then return a[i] < b[i] and -1 or 1 end
  end
  return #a == #b and 0 or (#a < #b and -1 or 1)
end

-- Finnish SFS-EN 13710 primary order: A..Z, then ring-A, umlaut-A,
-- umlaut-O; umlaut-U belongs to Y. Accents are secondary differences.
-- Numeric arrays deliberately avoid Lua's locale-sensitive string comparison.
-- These Latin weights cover the frozen corpus and the differential fixtures;
-- unknown letters fail rather than silently acquiring a host-specific order.
local letters = {}
for c = 65, 90 do letters[utf8.char(c)] = {c - 64, 0} end
local variants = {
  {"ÀÈÌÒÙ", 2}, {"ÁÉÍÓÚÝ", 1}, {"ÂÊÎÔÛ", 4},
  {"ÃẼĨÕŨÑ", 10}, {"ËÏŸ", 8}, {"ĀĒĪŌŪ", 15},
  {"ĂĔĬŎŬ", 3}, {"ĄĘĮŲ", 14}, {"ÇŞŢ", 13},
  {"ČŠŽĚŘĎŤŇ", 5}, {"ŐŰ", 9}, {"ḤṂṆṚ", 18},
}
local bases = {
  "AEIOU", "AEIOUY", "AEIOU", "AEIOUN", "EIY", "AEIOU",
  "AEIOU", "AEIU", "CST", "CSZERDTN", "OU", "HMNR",
}
for i, row in ipairs(variants) do
  local n = 0
  for _, cp in utf8.codes(row[1]) do
    n = n + 1
    letters[utf8.char(cp)] = {bases[i]:byte(n) - 64, row[2]}
  end
end
letters[utf8.char(0x00c5)] = {27, 0}
letters[utf8.char(0x00c4)] = {28, 0}
letters[utf8.char(0x00c6)] = {28, 1}
letters[utf8.char(0x00d6)] = {29, 0}
letters[utf8.char(0x00d8)] = {29, 1}
letters[utf8.char(0x00dc)] = {25, 8}
-- Persian letters occurring in the corpus's bilingual Wild Gazelle title.
-- Their Arabic-script order follows Latin, independent of process locale.
for rank, cp in ipairs({0x0627, 0x062d, 0x0634, 0x0647, 0x0648, 0x06cc}) do
  letters[utf8.char(cp)] = {100 + rank, 0}
end

-- Turn an uppercase word into primary, accent and punctuation weight arrays.
-- Apostrophes affect only the last level; unsupported letters are fatal rather
-- than receiving an unverified fallback order. The input is not modified.
local function word_key(word)
  local primary, secondary, punctuation = {}, {}, {}
  local position, previous = 0, 0
  for _, cp in utf8.codes(word) do
    local c = utf8.char(cp)
    position = position + 1
    -- Finnish umlaut-U has no final-level weight. Preserve the gap before
    -- the next character, which matters when comparing it with umlaut-Y.
    if cp ~= 0x00dc then
      punctuation[#punctuation + 1] = position - previous
      punctuation[#punctuation + 1] = c == "'" and 1 or (c == "`" and 2 or cp + 1000)
      previous = position
    end
    local weight = letters[c]
    if weight then
      primary[#primary + 1], secondary[#secondary + 1] = weight[1], weight[2]
    elseif c:match("%d") then
      primary[#primary + 1], secondary[#secondary + 1] = cp - 48 - 10, 0
    elseif c == "'" or c == "`" then
      -- Ignored at primary/secondary levels, retained at the final level.
    else
      fail("unsupported collation character U+" .. string.format("%04X", cp) ..
           "; extend the verified Finnish collation table")
    end
  end
  return {primary, secondary, punctuation}
end

-- Compare word_key results level by level, returning -1, 0 or 1.
local function compare_word(a, b)
  for level = 1, 3 do
    local diff = compare_array(a[level], b[level])
    if diff ~= 0 then return diff end
  end
  return 0
end

-- Derive uppercase sorting text, not display text: discard TeX control names,
-- grouping braces and escaped nonspaces, retaining command arguments. This is
-- the supported title-cleaning convention, not a TeX parser or macro evaluator.
local function clean_title(s)
  local chars, output = {}, {}
  for _, cp in utf8.codes(s) do chars[#chars + 1] = utf8.char(cp) end
  local i = 1
  while i <= #chars do
    local c = chars[i]
    if c == "\\" then
      i = i + 1
      if chars[i] and chars[i]:match("^[A-Za-z]$") then
        repeat i = i + 1 until not chars[i] or not chars[i]:match("^[A-Za-z]$")
        while chars[i] and U.match(chars[i], "%s") do i = i + 1 end
      elseif chars[i] and U.match(chars[i], "%s") then
        output[#output + 1] = chars[i]
        i = i + 1
      else
        i = i + 1
      end
    elseif c == "{" then
      i = i + 1
      while chars[i] and U.match(chars[i], "%s") do i = i + 1 end
    else
      if c ~= "}" then output[#output + 1] = c end
      i = i + 1
    end
  end
  return U.upper(table.concat(output))
end

-- Return natural-sort tokens plus the first alphanumeric heading character.
-- Skip separators, prefer the longest numeric prefix, and weight remaining
-- words explicitly. The original title remains available for TeX rendering.
local function title_key(title)
  local clean, tokens = clean_title(title), {}
  local rest = clean
  while true do
    rest = U.match(rest, "%w.*")
    if not rest then break end
    local prefix = U.match(rest, "^%S*")
    local number, consumed
    for n = #prefix, 1, -1 do
      -- Lua always accepts a decimal point, but only accepts a comma when
      -- LC_NUMERIC permits it. Normalize Finnish decimal commas explicitly.
      number = tonumber((prefix:sub(1, n):gsub(",", ".")))
      if number then consumed = n; break end
    end
    if number then
      tokens[#tokens + 1] = {number = number}
      rest = rest:sub(consumed + 1)
    else
      local word = U.match(rest, "^[%a'`]+")
      if not word then fail("cannot tokenize title '" .. title .. "'") end
      tokens[#tokens + 1] = {word = word_key(word)}
      rest = rest:sub(#word + 1)
    end
  end
  return tokens, U.match(clean, "%w")
end

-- Move a configured first word to the end as ',~article', preserving an optional
-- alternate-title '*' marker and uppercasing the new initial. Return unchanged
-- text when there is no eligible article or no nonblank remainder.
local function rotate_title(title, prefixes)
  local star = title:sub(1, 1) == "*" and "*" or ""
  local body = title:sub(#star + 1)
  local first, tail = U.match(body, "^(%S+)%s+(.*)$")
  if first and prefixes[U.upper(first)] and U.match(tail, "%S") then
    local punctuation, initial, remaining = U.match(tail, "^(%W*)(%w?)(.*)$")
    -- A TeX control-space at the end must survive ordinary whitespace trim.
    remaining = remaining:gsub("\\%s", "%0\1")
    remaining = U.match(remaining, "^(.-)%s*$"):gsub("\1", "")
    return star .. punctuation .. U.upper(initial) .. remaining .. ",~" .. first
  end
  return title
end

-- Prefix keys are uppercase; title data never needs line serialization.
-- Validate text and return trimmed, article-rotated display text. Omitted prefixes
-- mean A/THE; an explicit empty table disables rotation. Preserve TeX control-spaces.
function M.normalize_title(text, prefixes)
  if type(text) ~= "string" then fail("title string is required") end
  local length, position = utf8.len(text)
  if not length then fail("title contains invalid UTF-8 at byte " .. position) end
  local star = text:sub(1, 1) == "*" and "*" or ""
  text = star .. U.gsub(text:sub(#star + 1), "^%s+", "")
  text = U.gsub(text, "([^%s\\])%s+$", "%1")
  return rotate_title(text, prefixes or {A = true, THE = true})
end

-- Author policies use cleaned, case-folded text, never expanded TeX. Whitespace
-- serialization differences do not change whole-name ignore matching.
function M.author_word(text)
  return U.gsub(trim(clean_title(text)), "%s+", " ")
end

-- Split only unprotected top-level syntax. A control word and its delimiter
-- spaces are one token; braces and escaped symbols are copied without execution.
-- Names retain their authored spelling, including grouping and leading '*'.
function M.normalize_authors(text, separators, after, ignored)
  if type(text) ~= "string" then fail("author string is required") end
  local length, position = utf8.len(text)
  if not length then fail("author contains invalid UTF-8 at byte " .. position) end
  separators, after, ignored = separators or {AND = true}, after or {BY = true}, ignored or {}
  local chars, names, seen, part, protected = {}, {}, {}, {}, {}
  for _, cp in utf8.codes(text) do chars[#chars + 1] = utf8.char(cp) end
  local function emit()
    local name = table.concat(part):gsub("\\%s", "%0\1")
    name = trim(name):gsub("\1", "")
    local cleaned = M.author_word(name)
    if name ~= "" and not ignored[cleaned] and not seen[name] then
      names[#names + 1], seen[name] = name, true
    end
    part = {}
  end
  local i, depth = 1, 0
  while i <= #chars do
    local c = chars[i]
    if c == "\\" then
      protected[i] = true
      part[#part + 1], i = c, i + 1
      if chars[i] and U.match(chars[i], "^%a$") then
        repeat
          protected[i] = true
          part[#part + 1], i = chars[i], i + 1
        until not chars[i] or not U.match(chars[i], "^%a$")
        while chars[i] and U.match(chars[i], "%s") do
          protected[i] = true
          part[#part + 1], i = chars[i], i + 1
        end
      elseif chars[i] then
        protected[i] = true
        part[#part + 1], i = chars[i], i + 1
      end
    elseif c == "{" or c == "}" then
      depth = depth + (c == "{" and 1 or -1)
      if depth < 0 then fail("author text has unmatched closing brace; balance grouping braces") end
      part[#part + 1], i = c, i + 1
    elseif depth == 0 and (c == "," or c == ";") then
      emit()
      i = i + 1
    elseif depth == 0 and U.match(c, "^%a$") then
      local first = i
      repeat i = i + 1 until not chars[i] or not U.match(chars[i], "^%a$")
      local word = table.concat(chars, "", first, i - 1)
      local before, following = chars[first - 1], chars[i]
       local standalone = not protected[first - 1] and not (before and U.match(before, "[%w_'`%-]")) and
         not (following and U.match(following, "[%w_'`%-]"))
      local key = U.upper(word)
      if standalone and separators[key] then emit()
      elseif standalone and after[key] then part = {}
      else part[#part + 1] = word end
    else
      part[#part + 1], i = c, i + 1
    end
  end
  if depth ~= 0 then fail("author text has unclosed group; balance grouping braces") end
  emit()
  return names
end

-- Return a songlink from trusted, already TeX-serialized target/label fields;
-- this is fragment construction, not escaping arbitrary external text.
local function link(record)
  return "\\ulSongLink{" .. record.target .. "}{" .. record.label .. "}"
end

-- Add cached sort keys to records and sort the array in place. Equal sort keys
-- put main titles before alternates, then use producer ordinal for stable ties.
-- Return idxblock/entry TeX, coalescing identical display titles into references.
local function titles(records, author)
  local first = {}
  for _, record in ipairs(records) do
    record.key, record.initial = title_key(record.title)
    first[record.title] = math.min(first[record.title] or record.ordinal, record.ordinal)
  end
  table.sort(records, function(a, b)
    for i = 1, math.min(#a.key, #b.key) do
      local x, y, diff = a.key[i], b.key[i], 0
      if x.number then
        if not y.number then return true end
        if x.number ~= y.number then return x.number < y.number end
      elseif y.number then return false
      else diff = compare_word(x.word, y.word) end
      if diff ~= 0 then return diff < 0 end
    end
    if #a.key ~= #b.key then return #a.key < #b.key end
    if author and first[a.title] ~= first[b.title] then return first[a.title] < first[b.title] end
    local alt_a, alt_b = not author and a.title:sub(1, 1) == "*", not author and b.title:sub(1, 1) == "*"
    if alt_a ~= alt_b then return not alt_a end
    return a.ordinal < b.ordinal
  end)
  local blocks, block = {}, nil
  for _, record in ipairs(records) do
    local c = record.initial
    local key = c and word_key(c) or nil
    if not block or (key and not block.key) or (not key and block.key) or
       (key and block.key and compare_word(block.key, key) < 0) then
      block = {heading = c or "\\#", key = key, records = {}}
      blocks[#blocks + 1] = block
    elseif c then
      -- Equivalent initials share a block; choose its shortest, then byte-lowest
      -- spelling deterministically rather than depending on record order.
      local a, b = {c:byte(1, #c)}, {block.heading:byte(1, #block.heading)}
      if #c < #block.heading or (#c == #block.heading and compare_array(a, b) < 0) then
        block.heading, block.key = c, key
      end
    end
    block.records[#block.records + 1] = record
  end
  local output = {}
  for _, group in ipairs(blocks) do
    output[#output + 1] = "\\begin{ulIndexBlock}{" .. group.heading .. "}\n"
    local last
    for _, record in ipairs(group.records) do
      if last and last.title == record.title then
        output[#output + 1] = "\\\\" .. link(record)
      else
        if last then output[#output + 1] = "}\n" end
        local alternate = not author and record.title:sub(1, 1) == "*"
        output[#output + 1] = (alternate and "\\ulIndexDisplayAltEntry{" or "\\ulIndexDisplayEntry{") ..
          record.title:sub(alternate and 2 or 1) .. "}{" .. link(record)
      end
      last = record
    end
    output[#output + 1] = "}\n\\end{ulIndexBlock}\n"
  end
  return table.concat(output)
end

-- Parse ordered name|alias definitions, one per line, and return tag-block TeX.
-- References split on comma/semicolon; each record appears once per canonical
-- group. Definition order controls groups; input record order controls links.
local function tags(records, definitions)
  local source = lines(definitions, "tag definitions")
  local groups, aliases = {}, {}
  for i, text in ipairs(source) do
    text = trim(text)
    if text ~= "" and not text:match("^[#%%]") then
      if text:match("^[%d%s]+$") then
        fail("tag definitions line " .. i .. ": numeric definition; migrate old .can files with ulsbs-migrate-syntax-v2 --write --tags-file FILE")
      end
      local group = {cells = {}}
      groups[#groups + 1] = group
      for name in (text .. "|"):gmatch("(.-)|") do
        name = trim(name)
        if name == "" then fail("tag definitions line " .. i .. ": empty alias") end
        if name:find("[,;]") then fail("tag definitions line " .. i .. ": tag names cannot contain comma or semicolon") end
        if not group.name then group.name = name end
        local canonical = U.upper(name)
        -- The first definition wins when aliases collide, including case aliases.
        if not aliases[canonical] then aliases[canonical] = group end
      end
    end
  end
  if #groups == 0 then fail("tag definitions contain no definitions") end
  for _, record in ipairs(records) do
    for ref in (record.title .. ","):gmatch("([^,;]*)([,;])") do
      ref = trim(ref)
      if ref == "" and trim(record.title) ~= "" then
        fail("tag input line " .. record.line .. ": empty tag reference between separators")
      end
      if ref ~= "" then
        local group = aliases[U.upper(ref)]
        if not group then
          fail("tag input line " .. record.line .. ": unknown tag '" .. ref .. "' (song " .. record.label .. ")")
        end
        group.cells[record.ordinal] = record
      end
    end
  end
  local output = {}
  local escapes = { ["\\"] = "\\textbackslash{}", ["{"] = "\\{", ["}"] = "\\}",
    ["#"] = "\\#", ["$"] = "\\$", ["%"] = "\\%", ["&"] = "\\&", ["_"] = "\\_",
    ["^"] = "\\textasciicircum{}", ["~"] = "\\textasciitilde{}" }
  for _, group in ipairs(groups) do
    local refs = {}
    for _, record in ipairs(records) do
      if group.cells[record.ordinal] then refs[#refs + 1] = link(record) end
    end
    if #refs > 0 then
      -- Definitions are plain text, unlike serialized TeX song/reference fields.
      local heading = group.name:gsub(".", function(char) return escapes[char] or char end)
      output[#output + 1] = "\\begin{ulIndexBlock}{" .. heading .. "}\n\\ulIndexDisplayEntry{}{" ..
        table.concat(refs, "\\\\") .. "}\n\\end{ulIndexBlock}\n"
    end
  end
  return table.concat(output)
end

-- Producers supply normalized records containing
-- title (already article-rotated), label, target, ordinal and diagnostic line.
-- Rendering sorts the title record array in place; tag order uses ordinal.
-- Return TeX fragment bytes; only tags require UTF-8 definitions_bytes.
function M.render(records, kind, definitions_bytes)
  if kind == "title" then return titles(records) end
  if kind == "author" then return titles(records, true) end
  if kind == "tag" then return tags(records, definitions_bytes) end
  fail("unsupported index kind '" .. tostring(kind) .. "'; expected title, author or tag")
end

return M
