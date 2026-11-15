-- SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Retained physical-line geometry for musical annotations, bars and repeats.
-- This file is part of the 'ulsbs' package.
--
-- Loaded with dofile by ulsbs-music.code.tex as ulsbs_music. TeX renders source
-- once and passes its attribute IDs to setup; Lua measures and adjusts retained
-- nodes, never replaying musical source, meter tokens or visual hooks.
-- Attribute markers and metrics survive node copies; node properties hold
-- derived line geometry and glue snapshots. Interned configuration snapshots
-- preserve scoped bar, repeat and spacing policy after TeX groups have ended.
-- The paragraph callback resolves physical-line geometry; finish_verse applies
-- stanza-wide minima, fits line extents and repairs glue in the caller's box.
-- TeX retains ownership of that box and its nodes throughout both phases.

local M = {}

-- Bind the TeX-allocated attribute IDs and install the paragraph callback once.
-- Public helpers share this setup's configuration store and retained-node metrics.
function M.setup(a)
  local hlist, vlist, rule, glue = node.id('hlist'), node.id('vlist'), node.id('rule'), node.id('glue')
  local glue_types, configs, config_ids = {}, {}, {}
  for id, name in pairs(node.subtypes('glue')) do glue_types[name] = id end
  -- Round scaled-point geometry, diagnosing nonfinite or out-of-range results.
  local function rounded(value)
    if value ~= value or value == math.huge or value == -math.huge or math.abs(value) > 1073741823 then
      tex.error('ulsbs: configured bar geometry exceeds the TeX dimension range',
        {'Reduce the bar scale or the selected reference height.'})
      return 0
    end
    return math.floor(value + .5)
  end
  -- Supply the ambient capital-A height when no retained lyric metric is found.
  local function capital_a()
    local current = font.getfont(font.current())
    local char = current and current.characters and current.characters[65]
    return char and char.height or 0
  end
  -- Obtain a mutable property table without discarding another owner's fields.
  local function property(n)
    local p = node.getproperty(n)
    if not p then p = {}; node.setproperty(n, p) end
    return p
  end
  -- Exclude dimensionless wrappers, notably multikey's alternate PDF overlays.
  local function visible_box(n)
    return n.width ~= 0 or n.height ~= 0 or n.depth ~= 0
  end
  -- Find a positive retained metric or snapshot ID through visible box contents.
  local function find_attribute(list, attribute)
    for n in node.traverse(list) do
      local value = node.has_attribute(n, attribute)
      if value and value > 0 then return value end
      if (n.id == hlist or n.id == vlist) and visible_box(n) then
        value = find_attribute(n.list, attribute)
        if value then return value end
      end
    end
  end
  -- Intern an immutable snapshot of the current scoped geometry and spacing
  -- settings; return its attribute-safe ID, reusing identical configurations.
  function M.capture_config()
    local config = {measure = {}, repetition = {}}
    local key = {}
    for _, kind in ipairs({'measure', 'repeat'}) do
      local target = kind == 'measure' and config.measure or config.repetition
      for level = 0, 3 do
        local prefix = 'ulsbs@' .. kind .. '@'
        local selected = tonumber(token.get_macro(prefix .. 'level@' .. level))
        local scale = tonumber(token.get_macro(prefix .. 'scale@' .. level))
        assert(selected and scale, 'bar configuration must be initialized')
        target[level] = {level = selected, scale = scale}
        key[#key + 1] = selected .. ':' .. scale
      end
    end
    config.minimum = token.get_macro('ulsbs@bar@verseminimum') == '1'
    config.bottom = tonumber(token.get_macro('ulsbs@repeat@bottomscale'))
    config.gap = tonumber(token.get_macro('ulsbs@repeat@minimumgap'))
    config.linegap = tonumber(token.get_macro('ulsbs@verse@minimumgap'))
    key[#key + 1] = tostring(config.minimum) .. ':' .. config.bottom .. ':' .. config.gap .. ':' .. config.linegap
    key = table.concat(key, '/')
    local id = config_ids[key]
    if not id then id = #configs + 1; configs[id] = config; config_ids[key] = id end
    return id
  end
  -- Prefer the node's captured policy over settings in the current TeX scope.
  local function configuration(n)
    return configs[node.has_attribute(n, a.config)] or configs[M.capture_config()]
  end
  -- Seed measure/repetition ink from level-zero policy before line breaking.
  -- lyric_a and returned dimensions are in scaled points.
  function M.initial_height(kind, lyric_a)
    return rounded(configs[M.capture_config()][kind][0].scale * lyric_a)
  end
  -- Seed repeat low hang from the retained lyric capital-A height.
  function M.initial_depth(lyric_a)
    return rounded(configs[M.capture_config()].bottom * lyric_a)
  end
  -- Freeze the current policy on the measure box in TeX register id.
  function M.tag_measure(id)
    node.set_attribute(tex.box[id], a.config, M.capture_config())
  end

  -- Per-anchor TeX stacking protects deep chord tails and tall lyric glyphs, but
  -- can leave neighboring anchors on different annotation baselines. Raise each
  -- retained row to the largest required clearance on its physical lyric line.
  -- Explicitly raised/lowered horizontal wrappers form separate baseline groups;
  -- independent vertical boxes and raw no-lyrics runs retain their own placement.
  local function align_line(line)
    local groups = {}
    local function collect(list, baseline)
      for n in node.traverse(list) do
        if n.id == hlist or n.id == vlist then
          local raised = baseline - n.shift
          if n.id == vlist and node.has_attribute(n, a.annotation) then
            for row in node.traverse_id(hlist, n.list) do
              local required = n.height - row.height
              local group = groups[raised]
              if not group then group = {baseline = required, rows = {}}; groups[raised] = group end
              group.baseline = math.max(group.baseline, required)
              group.rows[#group.rows + 1] = {box = n, row = row, baseline = required}
              break
            end
          elseif n.id == hlist and not node.has_attribute(n, a.annotation) then
            collect(n.list, raised)
          end
        end
      end
    end
    collect(line.list, 0)
    for _, group in pairs(groups) do
      for _, entry in ipairs(group.rows) do
        local extra = group.baseline - entry.baseline
        if extra > 0 then
          -- Increasing both this gap and the outer height lifts only the first
          -- row. The last lyric row's baseline/depth and horizontal advance stay
          -- fixed. A second inspection is idempotent: all clearances now match.
          local gap = node.new('kern')
          gap.kern = extra
          entry.box.list = node.insert_after(entry.box.list, entry.row, gap)
          entry.box.height = entry.box.height + extra
        end
      end
    end
  end

  -- Collect effective-original geometry relative to the physical-line baseline.
  -- Logical levels are lyrics (0), chords (1), normal melody (2) and high melody
  -- (3), independent of visual placement. References retain bottom and base
  -- separately: capital-A height for text, actual circle diameter for melody.
  local function inspect_line(line)
    local info = {level = 0, refs = {}, bars = {}, repetitions = {}, preps = {}}
    local notes = {}
    -- Keep the reference with the highest unscaled top at this logical level.
    local function reference(level, bottom, base)
      local old = info.refs[level]
      if base > 0 and (not old or bottom + base > old.bottom + old.base) then
        info.refs[level] = {bottom = bottom, base = base}
      end
    end
    -- Actual visible chords supersede nominal chord anchors supplied by notes.
    local function chord_reference(bottom, base, actual)
      if actual and not info.chord then info.refs[1] = nil; info.chord = true end
      if actual or not info.chord then reference(1, bottom, base) end
    end
    -- Recover circle ink and nominal lane raises through visible hbox wrappers;
    -- anchor is the annotation baseline and baseline tracks nested box shifts.
    local function circles(list, baseline, anchor)
      for n in node.traverse_id(hlist, list) do
        local raised = baseline - n.shift
        local center = node.has_attribute(n, a.note_center)
        if center then
          local level = node.has_attribute(n, a.note_level) or 2
          local radius = assert(node.has_attribute(n, a.note_radius))
          local chord_base = anchor + raised - assert(node.has_attribute(n, a.note_raise))
          local base = assert(node.has_attribute(n, a.chord_a))
          chord_reference(chord_base, base, false)
          info.level = math.max(info.level, level)
          local circle = {level = level, bottom = anchor + raised + center - radius,
            base = 2 * radius, anchor = chord_base, center = center,
            normal = node.has_attribute(n, a.normal_raise), high = node.has_attribute(n, a.high_raise)}
          notes[#notes + 1] = circle
          if level >= 2 then reference(level, circle.bottom, circle.base) end
        elseif visible_box(n) then
          -- Only effective-original geometry is visited, never zero-sized PDF overlays.
          circles(n.list, raised, anchor)
        end
      end
    end
    -- Read an annotation's visible chord metric and any retained melody circles.
    local function raw_anchor(n, baseline)
      local metric = node.has_attribute(n, a.row)
      if metric and metric > 0 then
        local base = node.has_attribute(n, a.chord_a) or find_attribute(n.list, a.chord_a)
        assert(base, 'visible chord must retain its capital-A metric')
        info.level = math.max(info.level, 1)
        chord_reference(baseline, base, true)
      end
      circles(n.list, 0, baseline)
    end
    -- Locate annotation anchors inside the effective-original chord row.
    local function run(list, baseline)
      for n in node.traverse_id(hlist, list) do
        local raised = baseline - n.shift
        if node.has_attribute(n, a.annotation) then raw_anchor(n, raised)
        else run(n.list, raised) end
      end
    end
    -- Collect owned rules/boxes, reading only the first row of layered
    -- annotations so multikey alternatives cannot enlarge original geometry.
    local function collect(list, baseline)
      for n in node.traverse(list) do
        if n.id == rule and node.has_attribute(n, a.repetition) then
          info.repetitions[#info.repetitions + 1] = {box = n, baseline = baseline}
        elseif n.id == hlist or n.id == vlist then
          local raised = baseline - n.shift
          if node.has_attribute(n, a.prep) then
            info.preps[#info.preps + 1] = {box = n, baseline = baseline}
          elseif node.has_attribute(n, a.measure) == 1 then
            info.bars[#info.bars + 1] = {box = n, baseline = raised}
          elseif node.has_attribute(n, a.annotation) then
            if n.id == vlist then
              for row in node.traverse_id(hlist, n.list) do
                run(row.list, raised + n.height - row.height)
                break
              end
            else raw_anchor(n, raised) end
          elseif n.id == hlist then collect(n.list, raised) end
        end
      end
    end
    collect(line.list, 0)
    local lyric_a = find_attribute(line.list, a.lyric_a) or capital_a()
    reference(0, 0, lyric_a)
    -- A selected but empty melody lane uses its nominal position and the nearest
    -- visible circle's actual dimensions, not an invisible renderer or phantom row.
    for level = 2, info.level do
      if not info.refs[level] then
        local nearest
        for _, circle in ipairs(notes) do
          if not nearest or math.abs(circle.level - level) < math.abs(nearest.level - level) then
            nearest = circle
          end
        end
        assert(nearest, 'melody level must have a visible reference circle')
        local raise = assert(level == 2 and nearest.normal or nearest.high)
        reference(level, nearest.anchor + raise + nearest.center - nearest.base / 2, nearest.base)
      end
    end
    return info
  end
  -- Select policy by the line's logical level, then compute bottom + base * scale
  -- from its chosen reference. A stanza chord minimum can promote lyric-only
  -- lines without inventing visible chords or changing their recorded level.
  local function target(info, config, kind, minimum)
    local level = info.level
    if config.minimum and minimum and level == 0 then level = 1 end
    local policy = config[kind][level]
    local ref = info.refs[policy.level] or (policy.level == 1 and minimum)
    assert(ref, 'configured bar reference is unavailable')
    return math.max(0, rounded(ref.bottom + ref.base * policy.scale)), level
  end
  -- Resize only the retained measure rule and its wrappers; preserve the meter's
  -- measured contribution above it, even when that leaves no room for bar ink.
  local function measure_geometry(entry, target_top)
    local bar, row = entry.box
    for item in node.traverse_id(hlist, bar.list) do row = item end
    local ink
    for item in node.traverse_id(rule, row.list) do ink = item end
    assert(ink, 'measure bar must contain its retained rule')
    local meter = bar.height - ink.height
    ink.height = math.max(0, target_top - entry.baseline - meter)
    row.height = ink.height
    bar.height = meter + ink.height
  end
  -- Apply each bar's captured policy and lift prep markers to the active lane's
  -- bottom, never below their original raise. Repeat reach excludes continuation
  -- overlap, which is preserved separately; low hang uses the lyric reference.
  -- Only the stanza pass requests fit_ink and updates the line's outer extents.
  local function adjust_line(line, minimum, fit_ink)
    align_line(line)
    local info = inspect_line(line)
    local config = configuration(line)
    for _, entry in ipairs(info.bars) do
      local cfg = configuration(entry.box)
      measure_geometry(entry, target(info, cfg, 'measure', minimum))
    end
    for _, entry in ipairs(info.preps) do
      local ref = info.refs[info.level]
      local fallback = entry.baseline + node.has_attribute(entry.box, a.prep)
      entry.box.shift = entry.baseline - math.max(fallback, ref and info.level > 0 and ref.bottom or fallback)
    end
    for _, entry in ipairs(info.repetitions) do
      local bar = entry.box
      local cfg = configuration(bar)
      local p = property(bar)
      if not p.ulsbs_overlap then
        p.ulsbs_overlap = math.max(0, bar.height - (node.has_attribute(bar, a.normal_height) or bar.height))
      end
      local reach = target(info, cfg, 'repetition', minimum)
      local normal = math.max(0, reach - entry.baseline)
      bar.height = normal + p.ulsbs_overlap
      bar.depth = rounded(info.refs[0].base * cfg.bottom)
      node.set_attribute(bar, a.normal_height, normal)
      node.set_attribute(bar, a.repeat_gap, cfg.gap)
    end
    -- Include owned nested bars explicitly; repeat starts reserve normal reach,
    -- not the extra overlap used solely to join continuation fragments.
    if fit_ink then
      local _, height, depth = node.dimensions(line.list)
      line.height, line.depth = height, depth
      if minimum and config.minimum then
        line.height = math.max(line.height, minimum.bottom + minimum.base)
      end
      for _, entry in ipairs(info.bars) do
        line.height = math.max(line.height, entry.baseline + entry.box.height)
        line.depth = math.max(line.depth, entry.box.depth - entry.baseline)
      end
      for _, entry in ipairs(info.repetitions) do
        if node.has_attribute(entry.box, a.repetition_start) then
          line.height = math.max(line.height, entry.baseline + node.has_attribute(entry.box, a.normal_height))
        end
        line.depth = math.max(line.depth, entry.box.depth - entry.baseline)
      end
    end
    local p = property(line).ulsbs_music
    p.level, p.references, p.geometry = info.level, info.refs, info
    return info
  end
  -- Copy glue values, not a live register whose TeX scope may end before fitting.
  local function skip_spec(skip)
    return {width = skip.width, stretch = skip.stretch, shrink = skip.shrink,
      stretch_order = skip.stretch_order, shrink_order = skip.shrink_order}
  end
  -- Paragraph phase: capture line policy and baseline glue while still in scope,
  -- then resolve retained ink without repacking or fitting the stanza's lines.
  luatexbase.add_to_callback('post_linebreak_filter', function(head)
    for line in node.traverse_id(hlist, head) do
      node.set_attribute(line, a.config, find_attribute(line.list, a.config)
        or node.has_attribute(line, a.config) or M.capture_config())
      property(line).ulsbs_music = {baseline = skip_spec(tex.skip.baselineskip),
        lineskip = skip_spec(tex.skip.lineskip), limit = tex.dimen.lineskiplimit}
      adjust_line(line)
    end
    return head
  end, 'ulsbs-measure-reach')

  -- Stanza phase: find a shared chord minimum (actual chords outrank nominal
  -- note anchors), fit marked lines, and repair baseline glue and repeat endings.
  -- box_id is the caller-owned TeX box register; its list stays owned by that box.
  function M.finish_verse(box_id)
    local box = tex.box[box_id]
    if not box.list then return end
    local minimum, actual_chord
    for line in node.traverse_id(hlist, box.list) do
      if (node.getproperty(line) or {}).ulsbs_music then
        align_line(line)
        local info = inspect_line(line)
        if info.level > 0 then
          local ref = info.refs[1]
          if info.chord and not actual_chord then minimum = nil; actual_chord = true end
          if info.chord or not actual_chord then
            if not minimum then minimum = {bottom = ref.bottom, base = ref.base}
            else minimum.bottom = math.min(minimum.bottom, ref.bottom); minimum.base = math.max(minimum.base, ref.base) end
          end
        end
      end
    end
    -- Revisit only baseline/lineskip glue between retained lines; unrelated glue
    -- and intervening boxes retain their own layout semantics.
    local previous_depth, pending, previous_line
    for n in node.traverse(box.list) do
      if n.id == glue and (n.subtype == glue_types.baselineskip or n.subtype == glue_types.lineskip) then
        pending = n
      elseif n.id == hlist or n.id == vlist or n.id == rule then
        local data = (node.getproperty(n) or {}).ulsbs_music
        if data then
          adjust_line(n, minimum, true)
          if pending and previous_depth then
            local minimum_gap = configuration(n).linegap
            local width = data.baseline.width - previous_depth - n.height
            local spec = data.baseline
            pending.subtype = glue_types.baselineskip
            if width < data.limit then spec, width = data.lineskip, data.lineskip.width; pending.subtype = glue_types.lineskip end
            -- Preserve stretch but cap finite shrink at the minimum separation;
            -- infinite-order shrink must not collapse the protected ink gap.
            width = math.max(width, minimum_gap)
            pending.width, pending.stretch, pending.stretch_order = width, spec.stretch, spec.stretch_order
            pending.shrink = spec.shrink_order == 0 and math.min(spec.shrink, width - minimum_gap) or 0
            pending.shrink_order = 0
          end
          previous_line = n
        -- A separately boxed repeat endpoint uses its source line's references
        -- and its own captured policy, including scaled low hang and overlap.
        elseif node.has_attribute(n, a.end_fragment) and previous_line then
          local info = property(previous_line).ulsbs_music.geometry
          local cfg = configuration(n)
          local depth = rounded(info.refs[0].base * cfg.bottom)
          previous_line.depth = math.max(previous_line.depth, depth)
          -- The inner raisebox already compensates the source line's old depth.
          -- Only add the delta introduced by fitting the scaled repeat low hang.
          local old_depth = node.has_attribute(n, a.end_fragment)
          for wrapper in node.traverse_id(hlist, n.list) do
            wrapper.shift = old_depth - previous_line.depth
          end
          -- Repair retained endpoint rules through their horizontal wrappers.
          local function fragments(list)
            for item in node.traverse(list) do
              if item.id == rule and node.has_attribute(item, a.repetition) then
                local old = node.has_attribute(item, a.normal_height) or item.height
                local overlap = math.max(0, item.height - old)
                local normal = target(info, cfg, 'repetition', minimum)
                item.height, item.depth = normal + overlap, depth
                node.set_attribute(item, a.normal_height, normal)
                node.set_attribute(item, a.repeat_gap, cfg.gap)
              elseif item.id == hlist then fragments(item.list) end
            end
          end
          fragments(n.list)
        end
        previous_depth, pending = n.depth, nil
      end
    end
    -- Borrow the list for natural packing and copy back only box metadata.
    -- Detach it before freeing the temporary shell; the caller still owns it.
    local packed = node.vpack(box.list)
    box.height, box.depth = packed.height, packed.depth
    box.glue_set, box.glue_sign, box.glue_order = packed.glue_set, packed.glue_sign, packed.glue_order
    packed.list = nil
    node.free(packed)
  end
end

return M
