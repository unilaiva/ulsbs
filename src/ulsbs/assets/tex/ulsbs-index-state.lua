-- SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Previous-pass storage and the TeX-to-Lua index event lifecycle.
-- This file is part of the 'ulsbs' package.
--
-- Loaded once by ulsbs-index.code.tex as ulsbs_index_state;
-- it loads the pure codec and sorter.
-- start -> declare -> begin_document -> stage/ship or directive -> show -> finish
-- describes the main responsibilities, not a strict event order: show can occur
-- before collection is complete and always renders the previous completed pass.
-- TeX owns serialization and hooks; this module owns validation, job-local files
-- and rerun warnings. finish runs at enddocument/end, after pending pages ship.

local M = {}
local sorter = dofile(assert(kpse.find_file("ulsbs-index.lua", "tex"),
  "Missing ulsbs-index.lua; reinstall the ULSBS TeX assets"))
-- entries is declaration order; previous is immutable prior-pass event data;
-- displayed records requested fragments. events collects this pass, while staged
-- holds data referenced by numeric late-Lua handles, including unshipped boxes.
local entries, previous, displayed = {}, {}, {}
local statefile, jobname, writable, outputdir
local source, sourcehash, oldsource, oldsourcehash
local tagfile
local signature = "ULSBS index snapshot 3 fi-compatible-v1\n"
local records = dofile(assert(kpse.find_file("ulsbs-index-records.lua", "tex"),
  "Missing ulsbs-index-records.lua; reinstall the ULSBS TeX assets"))
local events, staged

-- Return binary file bytes, or nil if opening fails; always close an opened file.
local function read(path)
  local file = io.open(path, "rb")
  if not file then return nil end
  local value = file:read("*a")
  file:close()
  return value
end

-- Replace path with value bytes; opening, writing or closing failures are fatal.
local function write(path, value)
  local file, reason = io.open(path, "wb")
  if not file then error("Cannot write " .. path .. ": " .. tostring(reason), 0) end
  assert(file:write(value))
  assert(file:close())
end

-- Frame a string with its byte length; this outer snapshot format also frames
-- the codec's complete inner event stream as a single field.
local function field(value)
  return tostring(#value) .. ":" .. value
end

-- Emit a package warning to both terminal and log, without changing state.
local function warning(message)
  texio.write_nl("term and log", "\nPackage ulsbs-index Warning: " .. message .. "\n")
end

-- Emit the rerun wording consumed by the compiler's bounded convergence loop.
local function rerun(message)
  warning(message .. ". Rerun LuaLaTeX to refresh the index.")
end

-- Resolve a relative output filename under the engine output directory.
local function outputpath(filename)
  if filename:sub(1, 1) == "/" then return filename end
  return outputdir .. "/" .. filename
end

-- Return an absolute spelling for TeX input, bypassing unrelated TEXINPUTS files.
local function absolutepath(path)
  if path:sub(1, 1) == "/" then return path end
  return lfs.currentdir() .. "/" .. path
end

-- Reset all per-pass state for job and the initial file-writing flag. Load and
-- validate a previous snapshot before begin_document can overwrite it. The MD5
-- detects accidental corruption, not hostile data; version, job and completion
-- checks prevent reuse of incompatible, foreign or interrupted passes.
function M.start(job, files)
  entries, previous, displayed = {}, {}, {}
  source, sourcehash, oldsource, oldsourcehash = nil, nil, nil, nil
  tagfile = nil
  events, staged = {}, {}
  M.replay, M.replays = 0, 0
  jobname, writable = job, files
  outputdir = status.output_directory
  if not outputdir or outputdir == "" then outputdir = "." end
  -- Keep the engine's spelling for Lua I/O: openout_any permits an absolute
  -- output path only when -output-directory itself was absolute.
  statefile = outputpath(job .. ".ulsbs-index-state")
  local bytes = read(statefile)
  if not bytes then return end
  local digest, payload = bytes:match("^([0-9a-f]+)\n(.*)$")
  if not payload or md5.sumhexa(payload) ~= digest then
    error("Malformed or incomplete " .. statefile .. "; remove it and rerun LuaLaTeX twice", 0)
  end
  if payload:sub(1, #signature) ~= signature then
    error("Unsupported index snapshot/locale in " .. statefile .. "; remove it and rerun LuaLaTeX twice", 0)
  end
  local position = #signature + 1
  -- Add the snapshot filename and recovery instructions to a parsing failure.
  local function malformed(reason)
    error(reason .. " index snapshot " .. statefile .. "; remove it and rerun LuaLaTeX twice", 0)
  end
  -- Consume the next byte-counted outer field, advancing the local cursor.
  local function take()
    local first, last, count = payload:find("(%d+):", position)
    if first ~= position then malformed("Malformed") end
    count = tonumber(count)
    if count > #payload - last then malformed("Truncated") end
    local value = payload:sub(last + 1, last + count)
    position = last + count + 1
    return value
  end
  if take() ~= jobname then error("Index snapshot belongs to another job: " .. statefile, 0) end
  if take() ~= "complete" then
    error("Aborted earlier index pass in " .. statefile .. "; remove it and rerun LuaLaTeX twice", 0)
  end
  oldsource, oldsourcehash = take(), take()
  while position <= #payload do
    local id, kind, filename, data = take(), take(), take(), take()
    if previous[id] then malformed("Duplicate entry in") end
    if kind ~= "title" and kind ~= "tag" and kind ~= "author" then malformed("Unknown index kind in") end
    local ok, result = pcall(records.decode, data, kind)
    if not ok then malformed(tostring(result) .. " in") end
    previous[id] = {kind = kind, filename = filename, data = data}
  end
end

-- Atomically replace the snapshot with status ('collecting' or 'complete') and
-- id-keyed values containing encoded data, emitted in current declaration order.
-- The temporary write/rename protects completion, not concurrent same-job builds.
local function save(status, values)
  local parts = {signature, field(jobname), field(status), field(source or ""), field(sourcehash or "")}
  for _, entry in ipairs(entries) do
    local value = values[entry.id]
    if value then
      parts[#parts + 1] = field(entry.id) .. field(entry.kind)
        .. field(entry.filename) .. field(value.data)
    end
  end
  local payload = table.concat(parts)
  local temporary = statefile .. ".tmp"
  write(temporary, md5.sumhexa(payload) .. "\n" .. payload)
  assert(os.rename(temporary, statefile))
end

-- Register a unique index id/kind and fragment basename (without .sbx), create
-- its current event stream and reject incompatible previous declarations.
function M.declare(id, kind, filename)
  records.string(id, "index identifier")
  records.string(filename, "index filename")
  if kind ~= "title" and kind ~= "tag" and kind ~= "author" then
    error("Unknown index kind: " .. tostring(kind), 0)
  end
  for _, entry in ipairs(entries) do
    if entry.id == id or entry.filename == filename then
      error("Duplicate index identifier or output filename: " .. id .. " (" .. filename .. ")", 0)
    end
  end
  entries[#entries + 1] = {id = id, kind = kind, filename = filename}
  events[id] = {}
  local old = previous[id]
  if old and (old.kind ~= kind or old.filename ~= filename) then
    error("Stale index declaration for " .. id .. "; remove " .. statefile .. " and rerun", 0)
  end
end

-- Return the declared index descriptor or fail before accepting unknown events.
local function declared_index(id)
  for _, entry in ipairs(entries) do if entry.id == id then return entry end end
  error("Unknown index identifier: " .. tostring(id), 0)
end

-- Validate and append a resolved record when writable; chapter defaults to ''.
-- Fields are trusted TeX spellings, not source to execute here. No return value.
function M.collect(id, title, label, target, chapter)
  declared_index(id)
  local event = {type = "record", title = records.string(title, "title"),
    label = records.string(label, "reference label"), target = records.string(target, "link target"),
    chapter = records.string(chapter or "", "chapter context")}
  if writable then events[id][#events[id] + 1] = event end
end

-- Validate an index-specific setting and append it at this point in the stream
-- when writable; replay applies settings only to following records.
function M.directive(id, name, value)
  local entry = declared_index(id)
  records.directive(entry.kind, name, value)
  if writable then events[id][#events[id] + 1] = {type = "directive", name = name, value = value} end
end

-- Stage only trusted, TeX-serialized strings immediately. A late Lua node carries
-- the numeric handle; copies/dry splits cannot execute title data or double ship.
-- A field may instead be literal string parts split at deferred \thepage tokens.
-- Return a validated string or a copied, dense nonempty array of UTF-8 strings;
-- gaps between array parts are typed page substitutions, not textual searches.
local function staged_field(value, description)
  if type(value) ~= "table" then return records.string(value, description) end
  local parts, count = {}, 0
  for key, part in pairs(value) do
    if type(key) ~= "number" or key < 1 or key % 1 ~= 0 then
      error("Invalid page template for " .. description .. "; expected an array of literal strings", 0)
    end
    parts[key] = records.string(part, description .. " template part")
    count = count + 1
  end
  if count == 0 then error("Empty page template for " .. description, 0) end
  for i = 1, count do
    if not parts[i] then error("Sparse page template for " .. description, 0) end
  end
  return parts
end

-- Canonicalize control-word delimiters as data, never by evaluating tokens.
-- Literal \string\thepage characters remain distinct from a deferred page.
-- Return text with one delimiter space after each control word, leaving control
-- symbols intact; TeX's current letter catcodes identify non-ASCII word letters.
local function canonical_tex(text)
  local result, i = {}, 1
  -- Test the UTF-8 character at this byte offset using the serialization catcodes.
  local function letter_at(position)
    if position > #text then return false end
    local code = utf8.codepoint(text, position)
    return code == 64 or code >= 65 and code <= 90 or code >= 97 and code <= 122
      or code >= 128 and tex and tex.getcatcode and tex.getcatcode(code) == 11
  end
  while i <= #text do
    local ch = text:sub(i, i)
    if ch == "\\" and letter_at(i + 1) then
      local following = i + 1
      repeat following = utf8.offset(text, 2, following) or #text + 1
      until not letter_at(following)
      result[#result + 1] = text:sub(i, following - 1) .. " "
      i = following
      while text:sub(i, i):match("%s") do i = i + 1 end
    elseif ch == "\\" and i < #text then
      local following = utf8.offset(text, 2, i + 1) or #text + 1
      result[#result + 1], i = text:sub(i, following - 1), following
    else
      local following = utf8.offset(text, 2, i) or #text + 1
      result[#result + 1], i = text:sub(i, following - 1), following
    end
  end
  return table.concat(result)
end

-- Freeze serialized fields for id and return a one-based handle for a late-Lua
-- node. tex_spelling requests delimiter canonicalization at shipout. No record
-- is collected yet: discarded or measurement-only node lists must leave no trace.
function M.stage(id, title, label, target, chapter, tex_spelling, sequential_label)
  declared_index(id)
  local item = {id = id, title = staged_field(title, "title"),
    label = staged_field(label, "reference label"), target = staged_field(target, "link target"),
    chapter = staged_field(chapter or "", "chapter context"),
    tex_spelling = tex_spelling, sequential_label = sequential_label, shipped = {}}
  staged[#staged + 1] = item
  return #staged
end

-- Commit a staged handle once per replay occurrence (0 for ordinary output).
-- pageLabel fills typed template gaps in every field; optional label overrides
-- the staged reference label. Copied markers in the same occurrence are no-ops.
function M.ship(handle, label, pageLabel)
  local item = staged[handle]
  if not item then error("Unknown staged index event: " .. tostring(handle), 0) end
  local occurrence = M.replay or 0
  if item.shipped[occurrence] then return end
  -- Resolve typed page gaps, then normalize TeX spelling without evaluating it.
  local function resolve(value)
    if type(value) == "table" then
      records.string(pageLabel, "shipout page label for staged template")
      value = table.concat(value, pageLabel)
    end
    return item.tex_spelling and canonical_tex(value) or value
  end
  local target = resolve(item.target)
  if M.replay_target then
    target = M.replay_target .. assert(target:match("(%.[12])$"), "Missing song outline level")
    if item.sequential_label then label = M.replay_label end
  end
  M.collect(item.id, resolve(item.title), label or resolve(item.label), target, resolve(item.chapter))
  item.shipped[occurrence] = true
end

-- An intentional repeated selection is a distinct output occurrence. Mark
-- its retained node list without replaying metadata, lyrics or other source.
-- number is a TeX box register; mutate its list with bracketing late-Lua markers
-- so identical handles may commit once again under a fresh replay identifier.
function M.replay_box(number, label, target)
  M.replays = (M.replays or 0) + 1
  local box = assert(tex.box[number], "Missing selected song box")
  local first, last = node.new("whatsit", "late_lua"), node.new("whatsit", "late_lua")
  first.data = "ulsbs_index_state.replay=" .. M.replays
  last.data = "ulsbs_index_state.replay=0"
  if label then
    first.data = first.data .. string.format(";ulsbs_index_state.replay_label=%q;ulsbs_index_state.replay_target=%q",
      label, target)
    last.data = last.data .. ";ulsbs_index_state.replay_label=nil;ulsbs_index_state.replay_target=nil"
  end
  if box.list then
    local tail = node.tail(box.list)
    first.next, box.list.prev = box.list, first
    tail.next, last.prev = last, tail
  else
    first.next, last.prev = last, first
  end
  box.list = first
end

-- Set the effective writing flag and root-source identity, invalidate previous
-- data on a root mismatch, then persist an interrupted-pass guard when writable.
-- The hash covers root only, not its input graph; finish compares actual events.
function M.begin_document(files, root)
  writable = files
  source = root
  sourcehash = md5.sumhexa(read(source) or "")
  if oldsource and (oldsource ~= source or oldsourcehash ~= sourcehash) then
    previous = {}
    warning("Source identity changed for " .. jobname .. "; discarding the previous index snapshot")
  end
  if writable then save("collecting", previous) end
end

-- Select a nonempty tag-definition filename during the consumer preamble.
-- A configured name uses TeX lookup without falling back to the default file.
function M.tag_file(filename)
  records.string(filename, "tag definition filename")
  if filename:match("^%s*$") then error("Tag definition filename must not be empty", 0) end
  tagfile = filename
end

-- Materialize a requested .sbx from previous records, never current
-- events. Return its filename and exact absolute input path, or nil path while
-- waiting for a first complete pass. Repeated calls reuse that fragment. All
-- indices need writable files. Definitions are loaded only for requested tags.
function M.show(id)
  local entry
  for _, item in ipairs(entries) do if item.id == id then entry = item end end
  if not entry then error("Unknown index identifier: " .. tostring(id), 0) end
  if not writable then
    error("Cannot refresh index " .. id .. " with \\nofiles; enable file writing and rerun LuaLaTeX twice", 0)
  end
  local filename = entry.filename .. ".sbx"
  local path = outputpath(filename)
  if displayed[id] then return filename, previous[id] and absolutepath(path) or nil end
  displayed[id] = true
  -- Never display an unrelated old external-index result on a first pass.
  os.remove(path)
  local old = previous[id]
  if not old then
    rerun("No complete previous-pass data for " .. id .. "; collecting this pass")
    return filename, nil
  end
  local definitions
  if entry.kind == "tag" then
    local name = tagfile or "tags.txt"
    if not tagfile then definitions = read("include/" .. name) end
    if not definitions then
      local resolved = kpse.find_file(name, "tex")
      if resolved then definitions = read(resolved) end
    end
    if not definitions then
      error("Missing tag definitions '" .. name .. "' for requested tag index " .. id
        .. "; set \\ulTagFile{...} to an existing file and rerun", 0)
    end
  end
  local ok, result = pcall(function()
    return sorter.render(records.normalize(records.decode(old.data, entry.kind), entry.kind, sorter),
      entry.kind, definitions)
  end)
  if not ok then error("Index " .. id .. ": " .. tostring(result), 0) end
  write(path, result)
  return filename, absolutepath(path)
end

-- After shipout, encode this pass, clear eligible empty fragments,
-- warn if any displayed index differs, and publish a complete snapshot. With
-- writing disabled this is a no-op.
function M.finish()
  if not writable then return end
  local current = {}
  for _, entry in ipairs(entries) do
    local data = records.encode(events[entry.id])
    local empty = true
    for _, event in ipairs(events[entry.id]) do
      if event.type == "record" then empty = false; break end
    end
    -- Directives alone generate no entries. Preserve empty resources even
    -- when unused, without loading tag definitions.
    -- The CLI skips unused index generation for ul-selection jobs.
    if empty and (displayed[entry.id] or jobname:sub(1, 12) ~= "ul-selection") then
      write(outputpath(entry.filename .. ".sbx"), "")
    end
    current[entry.id] = {data = data}
    if displayed[entry.id] and (not previous[entry.id] or previous[entry.id].data ~= data) then
      rerun("Collected records changed for " .. entry.id .. "; displayed index is not final")
    end
  end
  save("complete", current)
end

return M
