-- SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Typed-node layout helpers.
-- This file is part of the 'ulsbs' package.
--
-- Never re-evaluate lyric source.
-- Loaded by ulsbs-layout.code.tex as ulsbs_layout. TeX owns layout policy,
-- box registers and actual submission; Lua inspects ownership markers, preserves
-- outer stretch, protects song starts and builds disposable lookahead boxes.
-- Attributes are allocated once per module load and survive node copies. TeX
-- marks submitted song tails with pending_attribute and owned column boundaries
-- with boundary_attribute. outer_glue holds detached copies until TeX writes
-- them back after draining song columns, then explicitly resets it to nil.

local M = {}
M.boundary_attribute = luatexbase.new_attribute("ulsbs-layout-boundary")
M.pending_attribute = luatexbase.new_attribute("ulsbs-layout-pending")

-- Protect a retained body box through its first content box or visible rule.
-- Metadata whatsits followed by even zero paragraph glue can reopen a breakpoint
-- after the prelude's nobreak. Guard each leading glue and optional penalty,
-- skipping empty boxes/zero-height rules used by spacing commands. Forced breaks
-- remain authoritative; later nodes and all dimensions/writes stay untouched.
-- Called once before assembly so fit probes and selected copies share the guard.
function M.protect_song_start(number)
  local body = assert(tex.box[number], "Missing song body for start protection")
  for item in node.traverse(body.list) do
    local kind = node.type(item.id)
    if ((kind == "hlist" or kind == "vlist") and item.list)
      or (kind == "rule" and item.width ~= 0 and (item.height ~= 0 or item.depth ~= 0)) then
      break
    elseif kind == "penalty" and item.penalty > -10000 then
      item.penalty = 10000
    elseif kind == "glue" then
      local stop = node.new("penalty")
      stop.penalty = 10000
      body.list = node.insert_before(body.list, item, stop)
    end
  end
end

-- Return whether either live page-builder list still contains a marked song
-- tail. Scanning both lists detects continuations after a first page has shipped;
-- ordinary prose alone must not keep the song-owned pending state alive.
function M.has_pending_song()
  for _, key in ipairs({"page_head", "contrib_head"}) do
    for item in node.traverse(tex.lists[key]) do
      if node.has_attribute(item, M.pending_attribute) == 1 then return true end
    end
  end
  return false
end

-- Keep outer glue outside owned column stretch; intervening prose keeps its glue.
-- Scan the live page and contribution lists for trailing zero-width, zero-shrink
-- glue after the latest ownership boundary. Copy it into M.outer_glue and write
-- opposite-stretch nodes to neutralize it in the owned columns. Originals stay
-- in place; penalties, whatsits and zero kerns do not end the eligible run.
function M.save_outer_glue()
  local owned = false
  local glues = {}
  for _, key in ipairs({"page_head", "contrib_head"}) do
    for item in node.traverse(tex.lists[key]) do
      if node.has_attribute(item, M.boundary_attribute) == 1 then
        owned = true
        glues = {}
      elseif owned then
        local kind = node.type(item.id)
        if kind == "glue" and item.width == 0 and item.shrink == 0 then
          table.insert(glues, item)
        elseif not (kind == "penalty" or kind == "whatsit"
          or (kind == "kern" and item.kern == 0)) then
          owned = false
        end
      end
    end
  end
  if owned then
    for _, item in ipairs(glues) do
      local saved = node.copy(item)
      if M.outer_glue then
        local tail = node.tail(M.outer_glue)
        tail.next = saved
        saved.prev = tail
      else
        M.outer_glue = saved
      end
      local cancel = node.copy(item)
      cancel.stretch = -cancel.stretch
      -- Hidden intersong blocks may revisit this page: advance the boundary.
      node.set_attribute(cancel, M.boundary_attribute, 1)
      node.write(cancel)
    end
  end
end

-- Build a dry-lookahead vbox in destination from copies of page_head and the
-- song_number box list. Both arguments are TeX box register numbers; source lists
-- remain intact and no late-Lua markers execute during this construction.
-- separator is false/nil or a break penalty; bar_height is in scaled points and
-- bottom_skip names a TeX glue register. The separator models real submission:
-- protect the boundary, offer a break with bottom glue, cancel that glue for the
-- unbroken case, and back out the separator bar height. TeX owns dry splitting
-- and disposal of the resulting destination box. No Lua value is returned.
function M.combine_page(song_number, destination, separator, bar_height, bottom_skip)
  local source = assert(tex.box[song_number], "Missing song box for lookahead")
  local head = node.copy_list(tex.lists.page_head)
  local tail = head and node.tail(head)
  -- Append an owned node/list to the copied chain, maintaining both link directions.
  local function append(item)
    if not item then return end
    if tail then
      tail.next = item
      item.prev = tail
    else
      head = item
    end
    tail = node.tail(item)
  end
  if separator then
    local stop = node.new("penalty")
    stop.penalty = 10000
    append(stop)
    if separator < 10000 then
      local width, stretch, shrink, stretch_order, shrink_order = tex.getglue(bottom_skip)
      -- Clone the skip's dimensions and orders with signed amounts for cancellation.
      local function glue(sign)
        local item = node.new("glue")
        item.width = sign * width
        item.stretch = sign * stretch
        item.shrink = sign * shrink
        item.stretch_order = stretch_order
        item.shrink_order = shrink_order
        return item
      end
      append(glue(1))
      local point = node.new("penalty")
      point.penalty = separator
      append(point)
      append(glue(-1))
    end
    if bar_height > 0 then
      local gap = node.new("glue")
      gap.width = -bar_height
      append(gap)
    end
  end
  append(node.copy_list(source.list))
  tex.box[destination] = node.vpack(head)
end

return M
