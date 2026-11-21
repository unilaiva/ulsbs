-- SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Coalesce tagged repeat-bar fragments and draw physical continuation cues.
-- This file is part of the 'ulsbs' package.
--
-- Load: dofile(kpse.find_file('ulsbs-repeats.lua')) at the original directlua
-- site in ulsbs-repeats.code.tex, after spacing policy and repeat counters.
-- Requires: LuaTeX node/token/tex APIs and luatexbase; repeat dimensions and
-- numeric policy macros already exist. No require cache or module framework.
-- State: private attributes, traversal helpers and the one-shot gap warning
-- stay in this file's Lua chunk. Execution allocates attributes and globally
-- publishes the same five TeX attribute macros, then registers the named
-- pre_shipout_filter callback once, in the original order, on file load.
-- TeX grouping/catcodes are not changed. Shipout reads current continuation
-- dimensions and snapshotted rule attributes; public policy overrides remain
-- with the TeX setters/dimensions, not these private helper implementations.

--[[ Attributes survive boxing and page/column splitting. The primary
attribute identifies a repeat occurrence; the others carry semantic
endpoint and unsplit line-height information to the shipout callback. ]]
local attribute = luatexbase.new_attribute("ulsbs.repeatbar")
local start_attribute = luatexbase.new_attribute("ulsbs.repeatbar.start")
local end_attribute = luatexbase.new_attribute("ulsbs.repeatbar.end")
local height_attribute = luatexbase.new_attribute("ulsbs.repeatbar.height")
local gap_attribute = luatexbase.new_attribute("ulsbs.repeatbar.gap")
token.set_macro("ulsbs@rep@attribute", tostring(attribute), "global")
token.set_macro("ulsbs@rep@startattribute", tostring(start_attribute), "global")
token.set_macro("ulsbs@rep@endattribute", tostring(end_attribute), "global")
token.set_macro("ulsbs@rep@heightattribute", tostring(height_attribute), "global")
token.set_macro("ulsbs@rep@gapattribute", tostring(gap_attribute), "global")

local hlist_id = node.id("hlist")
local vlist_id = node.id("vlist")
local rule_id = node.id("rule")
local glue_id = node.id("glue")
local kern_id = node.id("kern")
local whatsit_id = node.id("whatsit")
local user_defined_subtype = node.subtype("user_defined")

--[[ Return a glue node's actual size after its containing box has applied
stretch or shrink. The fallback supports older LuaTeX node libraries. ]]
local function effective_glue(n, parent)
  if node.effective_glue then
    return node.effective_glue(n, parent)
  end
  return n.width
end

--[[ Add one tagged rule fragment to its physical segment. A segment key is
the repeat occurrence plus absolute horizontal position, so the same
repeat split into two columns on one page forms two independent groups.
Keep both the geometric union and the uppermost rule: that rule becomes
the single solid PDF rectangle emitted for this segment. ]]
local function collect_rule(context, n, x, baseline, parent)
  local repeat_id = node.has_attribute(n, attribute)
  if not repeat_id then
    return
  end
  context.sequence = context.sequence + 1
  local key = tostring(repeat_id) .. ":" .. tostring(x)
  local group = context.groups[key]
  local top = baseline - n.height
  local bottom = baseline + n.depth
  local normal_height = node.has_attribute(n, height_attribute) or n.height
  if not group then
    group = { top = top, bottom = bottom, first = n,
              first_parent = parent, baseline = baseline, rules = {},
               normal_height = normal_height,
               x = x, gap = node.has_attribute(n, gap_attribute)
                 or tonumber(token.get_macro("ulsbs@repeat@minimumgap")) or 131072,
               first_sequence = context.sequence,
               repeat_id = repeat_id, last_sequence = context.sequence,
              has_start = false, has_end = false }
    context.groups[key] = group
  else
    if top < group.top then
      group.top = top
      group.first = n
      group.first_parent = parent
      group.baseline = baseline
      group.normal_height = normal_height
    end
    if bottom > group.bottom then
      group.bottom = bottom
    end
    group.last_sequence = context.sequence
  end
  if node.has_attribute(n, start_attribute) then
    group.has_start = true
  end
  table.insert(group.rules, n)
end

--[[ Record a semantic end-repeat marker in traversal order. Its physical
group is resolved after traversal because the zero-size marker has no
useful horizontal coordinate of its own. ]]
local function collect_end_marker(context, n)
  local repeat_id = node.has_attribute(n, attribute)
  if repeat_id and node.has_attribute(n, end_attribute) then
    context.sequence = context.sequence + 1
    table.insert(context.end_markers,
                 { repeat_id = repeat_id, sequence = context.sequence })
  end
end

local walk_box

--[[ Traverse a horizontal list while tracking the absolute x coordinate
and baseline. Nested boxes are visited recursively; glue must use its final
stretched or shrunk width to keep column positions exact. ]]
local function walk_hlist(list, x, baseline, parent, context)
  local cursor = x
  for n in node.traverse(list) do
    if n.id == rule_id then
      collect_rule(context, n, cursor, baseline, parent)
    elseif n.id == hlist_id or n.id == vlist_id then
      walk_box(n, cursor, baseline + n.shift, context)
    elseif n.id == whatsit_id and n.subtype == user_defined_subtype then
      collect_end_marker(context, n)
    end
    if n.id == glue_id then
      cursor = cursor + effective_glue(n, parent)
    elseif n.id == kern_id then
      cursor = cursor + n.kern
    elseif n.width then
      cursor = cursor + n.width
    end
  end
end

--[[ Traverse a vertical list from its absolute top edge. Box heights,
depths, shifts, glue, and kerns advance the physical y position used to
calculate each rule fragment's top, bottom, and baseline. ]]
local function walk_vlist(list, x, top, parent, context)
  local cursor = top
  for n in node.traverse(list) do
    if n.id == rule_id then
      collect_rule(context, n, x, cursor + n.height, parent)
      cursor = cursor + n.height + n.depth
    elseif n.id == hlist_id or n.id == vlist_id then
      walk_box(n, x + n.shift, cursor + n.height, context)
      cursor = cursor + n.height + n.depth
    elseif n.id == glue_id then
      cursor = cursor + effective_glue(n, parent)
    elseif n.id == kern_id then
      cursor = cursor + n.kern
    elseif n.id == whatsit_id and n.subtype == user_defined_subtype then
      collect_end_marker(context, n)
    end
  end
end

--[[ Dispatch traversal using the reference-point convention of each box
type. Horizontal boxes receive a baseline; vertical boxes receive a
baseline and convert it to their top edge before walking their list. ]]
walk_box = function(box, x, baseline, context)
  if box.id == hlist_id then
    walk_hlist(box.list, x, baseline, box, context)
  elseif box.id == vlist_id then
    walk_vlist(box.list, x, baseline - box.height, box, context)
  end
end

--[[ Insert one zero-width overlay box immediately before the retained
solid rule. Its copied rule inherits width, color state, direction, and
other backend properties, while the wrapper shift positions the short dash
at the requested vertical interval without affecting TeX layout. ]]
local function add_dash(group, top, bottom)
  local dash = node.copy(group.first)
  dash.height = bottom - top
  dash.depth = 0
  local wrapper = node.new(hlist_id)
  wrapper.width = 0
  wrapper.height = 0
  wrapper.depth = 0
  wrapper.dir = group.first_parent.dir
  wrapper.shift = bottom - group.baseline
  wrapper.list = dash
  group.first_parent.list = node.insert_before(
    group.first_parent.list, group.first, wrapper)
end

--[[ Associate each semantic end marker with the latest preceding physical
segment of the same repeat on this shipped page. Earlier segments lack an
end marker and are therefore known to continue on another column or page.
Traversal order disambiguates multiple columns at the same repeat nesting
level. ]]
local function mark_ended_groups(context)
  for _, marker in ipairs(context.end_markers) do
    local candidate = nil
    for _, group in pairs(context.groups) do
      if group.repeat_id == marker.repeat_id
         and group.last_sequence < marker.sequence
         and (not candidate
              or group.last_sequence > candidate.last_sequence) then
        candidate = group
      end
    end
    if candidate then
      candidate.has_end = true
      candidate.end_sequence = marker.sequence
    end
  end
end

--[[ Only separate, completed occurrences at the same x can constrain one
another. Semantic order, not extended ink tops, excludes nested/ongoing
occurrences; split page/column segments never participate. ]]
local gap_warning_emitted = false
local function clip_minimum_gaps(context)
  local ordered = {}
  for _, group in pairs(context.groups) do
    table.insert(ordered, group)
  end
  table.sort(ordered, function(a, b)
    return a.first_sequence < b.first_sequence
  end)
  local previous_at_x = {}
  for _, group in ipairs(ordered) do
    local previous = previous_at_x[group.x]
    if previous and previous.has_start and previous.has_end
       and group.has_start and group.has_end
       and not (previous.repeat_id == group.repeat_id)
       and previous.end_sequence < group.first_sequence
       and group.gap > 0 then
      local original_top = group.top
      group.top = math.min(group.bottom,
        math.max(group.top, previous.bottom + group.gap))
      group.gap_clipped = group.top > original_top
      if group.top == group.bottom and not gap_warning_emitted then
        texio.write_nl("term and log", "Package ulsbs Warning: Repeat minimum gap suppressed a bar with no positive stroke.")
        gap_warning_emitted = true
      end
    end
    previous_at_x[group.x] = group
  end
end

--[[ Add two outward-facing dashes only at split boundaries. On an incoming
segment, reset the solid rule to the normal first-line height and place the
dashes above it. On an outgoing segment, preserve the normal bottom and
place the dashes below it. Genuine repeat endpoints stay solid and receive
no continuation marks. ]]
local function add_continuation_dashes(group)
  local dash = tex.dimen.ulRepeatBarContinuationDashLength
  local gap = tex.dimen.ulRepeatBarContinuationDashGap
  if not group.has_start then
    local normal_top = group.baseline - group.normal_height
    group.top = normal_top
    add_dash(group, normal_top - 2 * dash - 2 * gap,
                    normal_top - dash - 2 * gap)
    add_dash(group, normal_top - dash - gap, normal_top - gap)
  end
  if not group.has_end then
    local normal_bottom = group.bottom
    add_dash(group, normal_bottom + gap,
                    normal_bottom + dash + gap)
    add_dash(group, normal_bottom + dash + 2 * gap,
                    normal_bottom + 2 * dash + 2 * gap)
  end
end

--[[ Shipout entry point: discover physical repeat segments, resolve their
semantic endpoints, add continuation cues, then enlarge one fragment to
cover the whole segment and zero all remaining fragments. LuaTeX omits
zero-sized rules, leaving one solid PDF rectangle plus any break dashes. ]]
local function coalesce_repeat_bars(head)
  local context = { groups = {}, end_markers = {}, sequence = 0 }
  walk_box(head, 0, head.height, context)
  mark_ended_groups(context)
  clip_minimum_gaps(context)
  for _, group in pairs(context.groups) do
    add_continuation_dashes(group)
    if group.gap_clipped
       and (group.top >= group.bottom or group.top > group.baseline) then
      if group.top < group.bottom then
        add_dash(group, group.top, group.bottom)
      end
      group.first.width = 0
      group.first.height = 0
      group.first.depth = 0
    else
      group.first.height = group.baseline - group.top
      group.first.depth = group.bottom - group.baseline
    end
    for _, rule in ipairs(group.rules) do
      if not (rule == group.first) then
        rule.width = 0
        rule.height = 0
        rule.depth = 0
      end
    end
  end
  return true
end

luatexbase.add_to_callback(
  "pre_shipout_filter", coalesce_repeat_bars, "ulsbs.repeatbars")
