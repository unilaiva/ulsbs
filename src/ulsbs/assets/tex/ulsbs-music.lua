-- SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Retained annotation spacing and physical-line geometry for music and bars.
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
  local glyph, kern, whatsit = node.id('glyph'), node.id('kern'), node.id('whatsit')
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
  local function first_of(id, list)
    for n in node.traverse_id(id, list) do return n end
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

  -- Mark independent horizontal parts before TeX overlays them. Most parts use
  -- their retained box dimensions. Beats hide their real extents from TeX.
  function M.tag_spacing_part(id, width, top, bottom)
    local box = tex.box[id]
    width = width or box.width
    if width <= 0 then return end
    node.set_attribute(box, a.spacing_part, width)
    if top then
      node.set_attribute(box, a.spacing_top, top)
      node.set_attribute(box, a.spacing_bottom, bottom)
    end
  end

  -- The enclosing voice box extends down to its baseline even when every note
  -- is raised. The retained circle markers give the height of the actual lane.
  local function visit_circles(list, raise, visit)
    for n in node.traverse_id(hlist, list) do
      local baseline = raise - n.shift
      local center = node.has_attribute(n, a.note_center)
      if center then
        visit(n, baseline, center, assert(node.has_attribute(n, a.note_radius)))
      elseif visible_box(n) then
        visit_circles(n.list, baseline, visit)
      end
    end
  end
  function M.tag_spacing_voice(id)
    local box = tex.box[id]
    if box.width <= 0 then return end
    local top, bottom
    visit_circles(box.list, 0, function(_, baseline, center, radius)
      local y = baseline + center
      top = math.max(top or y, y + radius)
      bottom = math.min(bottom or y, y - radius)
    end)
    M.tag_spacing_part(id, box.width, top or 0, bottom or 0)
  end

  local penalty, disc = node.id('penalty'), node.id('disc')
  local function continuation(n)
    return n and n.id == penalty and node.has_attribute(n, a.spacing)
  end
  local function marked_space(n)
    return n and n.id == glue and node.has_attribute(n, a.spacing)
      and n.shrink_order == 0 and n.shrink >= 0 and n.shrink <= n.width
  end

  local function check_space_range(scale, width)
    if scale ~= math.huge and width <= 1073741823 then return true end
    tex.error('ulsbs: scaled lyric space exceeds the TeX dimension range',
      {'Use a smaller multiplier for \\ulSpace.'})
  end

  function M.scale_space(scale, mark)
    local space = tex.nest.top.tail
    if not space or space.id ~= glue then return end
    if scale ~= 1 then
      local w, stretch, shrink = space.width * scale, space.stretch * scale, space.shrink * scale
      if not check_space_range(scale, math.max(math.abs(w), math.abs(stretch), math.abs(shrink))) then return end
      node.setglue(space, math.floor(w + .5), math.floor(stretch + .5), math.floor(shrink + .5),
        space.stretch_order, space.shrink_order)
    end
    if mark then node.set_attribute(space, a.spacing, 0) end
  end

  -- A starred gap owns its hyphen, including when a preceding annotation
  -- (replayed or explicit) has already reserved width without emitting lyrics.
  function M.continuation_space(dash_id, space, scale, break_cost)
    space = space * scale
    if not check_space_range(scale, space) then return end
    space = math.floor(space + .5)
    local dash, gap, guards = tex.box[dash_id], 0, {}
    local n = tex.nest.top.tail
    while n do
      local advance = node.has_attribute(n, a.lyric_advance)
      if not advance then break end
      if n.id == vlist then
        if advance == 0 then
          gap = gap + n.width
        else
          -- The automatic (not authored) dash carries the natural annotation
          -- width. Restore that width before taking the midpoint of the gap.
          local top, row
          for box in node.traverse_id(hlist, n.list) do
            if top then row = box; break end
            top = box
          end
          if row then
            local old_dash = node.tail(row.list)
            if old_dash and old_dash.id == glue then old_dash = old_dash.prev end
            local ink = old_dash and node.has_attribute(old_dash, a.lyric_advance)
            if ink then
              row.list = node.remove(row.list, old_dash)
              node.flush_node(old_dash)
              local width = math.max(advance, ink)
              n.width, row.width, top.width = width, width, width
              row.glue_set = 0
            end
          end
          node.unset_attribute(n, a.spacing)
          gap = gap + n.width - advance
          break
        end
      elseif n.id == penalty then
        guards[#guards + 1] = n
      elseif n.id ~= glue or n.width ~= 0 or n.stretch ~= 0 or n.shrink ~= 0 then
        break
      end
      n = n.prev
    end
    for _, guard in ipairs(guards) do guard.penalty = 10000 end

    local function with_dash(left, right)
      local before, after = node.new('kern', 1), node.new('kern', 1)
      before.kern, after.kern = left, right
      local glyph = node.copy(dash)
      node.insert_after(before, before, glyph)
      node.insert_after(before, glyph, after)
      return before
    end
    local width = math.max(gap + space, dash.width)
    local left = math.floor((width - dash.width) / 2)
    local wrap = node.new(disc)
    wrap.penalty = break_cost
    wrap.replace = with_dash(left - gap, width - left - dash.width)
    -- At a break, use the already reserved end of the line if the glyph fits.
    wrap.pre = with_dash(-math.min(dash.width, gap), 0)
    node.write(wrap)
  end

  -- Read a candidate's two retained rows and actual bands relative to the
  -- annotation baseline. The source scanner excludes offsets and adjacent runs,
  -- so all parts of this anchor start at the same horizontal position.
  local function spacing_anchor(stack, padding)
    local top, row
    for n in node.traverse_id(hlist, stack.list) do
      if not top then top = n else row = n; break end
    end
    local lyric = row and row.list
    if not lyric or lyric.id ~= hlist then return end
    local dash, printed
    for n in node.traverse(lyric.next) do
      if n.id == hlist then dash, printed = n, true
      elseif n.id == disc then dash = n.pre end
    end
    if not dash then return end
    local bands, empty_slot = {}, false
    local function parts(list, raise)
      for n in node.traverse_id(hlist, list) do
        local baseline = raise - n.shift
        local width = node.has_attribute(n, a.spacing_part)
        if width then
          local low = baseline + (node.has_attribute(n, a.spacing_bottom) or -n.depth)
          local high = baseline + (node.has_attribute(n, a.spacing_top) or n.height)
          if low < high then
            bands[#bands + 1] = {low = low, high = high, width = width}
          else
            -- A voice containing only authored empty slots has no band to test.
            empty_slot = true
          end
        elseif visible_box(n) then
          parts(n.list, baseline)
        end
      end
    end
    parts(top.list, 0)
    if empty_slot or #bands == 0 then return end
    return {stack = stack, row = row, lyric = lyric, dash = dash, printed = printed or false,
      padding = math.max(padding, dash.width), bands = bands}
  end

  -- Change only the horizontal advances. The annotation row is already flush
  -- left; the two original row baselines, ink, and wrappers are kept intact.
  local function set_advance(anchor)
    local row, lyric, width = anchor.row, anchor.lyric, anchor.advance
    if width == anchor.stack.width and (anchor.hyphen or false) == anchor.printed then return end
    local dash = anchor.hyphen and node.copy(anchor.dash)
    local rest = lyric.next
    lyric.next, rest.prev = nil, nil
    node.flush_list(rest)
    local gap = width - lyric.width
    if dash then
      local before = node.new('kern')
      before.kern = math.floor((gap - dash.width) / 2)
      node.insert_after(lyric, lyric, before)
      node.insert_after(lyric, before, dash)
      gap = gap - before.kern - dash.width
    end
    if gap ~= 0 then
      local after = node.new('kern')
      after.kern = gap
      node.insert_after(lyric, node.tail(lyric), after)
    end
    row.width, anchor.stack.width = width, width
  end

  -- Replace a glue breakpoint only when annotation ink needs extra width at
  -- the end of the broken line. On an unbroken line the glue retains its normal
  -- stretch/shrink; at the disc break TeX discards both the guard and the glue.
  local function protect_space(head, space, padding)
    local wrap = node.new(disc)
    wrap.penalty = 0
    local reserve = node.new(hlist)
    reserve.width = padding
    wrap.pre = reserve
    local guard = node.new(penalty)
    guard.penalty = 10000
    head = node.insert_before(head, space, wrap)
    return (node.insert_before(head, space, guard))
  end

  -- Greedily place syllables against all earlier bands. Test marked spaces at
  -- minimum width so justification cannot squeeze their annotations together.
  local function space_run(head, run, available)
    if #run < 2 then return head end
    local previous, x, right, original, line_start, placed = nil, 0, 0, 0, 0, {}
    for _, anchor in ipairs(run) do
      original = original + anchor.stack.width
      anchor.hyphen, anchor.breakable = nil, nil
      if previous then
        local link = previous.link
        local space = link.id == glue and link
        if space then
          previous.wrap_padding = math.max(0, right - x)
          if x + previous.wrap_padding - line_start > available then return end
          local minimum = space.width - space.shrink
          x, original = x + minimum, original + minimum
        end
        local clearance = 0
        for _, band in ipairs(anchor.bands) do
          for _, older in ipairs(placed) do
            if band.low < older.high and older.low < band.high then
              clearance = math.max(clearance, older.right - x)
            end
          end
        end
        if space then
          previous.space_extra = clearance
          x = x + clearance
          line_start = x
        else
          if clearance > 0 then
            if previous.dash.height > previous.row.height or previous.dash.depth > previous.row.depth then return end
            local gap = clearance + previous.padding
            previous.advance, previous.hyphen = previous.advance + gap, true
            x = x + gap
          end
          -- A synthetic break is safe only when no earlier ink protrudes.
          previous.breakable = previous.hyphen and right <= x
        end
      end
      for _, band in ipairs(anchor.bands) do
        local edge = x + band.width
        right = math.max(right, edge)
        placed[#placed + 1] = {low = band.low, high = band.high, right = edge}
      end
      anchor.advance = anchor.lyric.width
      x = x + anchor.advance
      previous = anchor
    end
    local terminal = run[#run]
    terminal.advance = math.max(terminal.stack.width, right - (x - terminal.advance))
    x = x + terminal.advance - terminal.lyric.width
    if x > original or x - line_start > available then return end
    for _, anchor in ipairs(run) do
      set_advance(anchor)
      local link = anchor.link
      if link then
        if link.id == glue then
          if anchor.space_extra > 0 then link.width = link.width + anchor.space_extra end
          if anchor.wrap_padding > 0 then head = protect_space(head, link, anchor.wrap_padding) end
        else
          link.penalty = anchor.breakable and continuation(link) or 10000
        end
      end
    end
    return head
  end

  -- Read a whole word before allowing it to join another across a marked space.
  -- An unsupported word must not disable compaction of its valid neighbors.
  local function read_word(current)
    local word = {}
    while current and current.id == vlist do
      local padding = node.has_attribute(current, a.spacing)
      if not padding then return end
      local anchor = spacing_anchor(current, padding)
      if not anchor then return end
      word[#word + 1] = anchor
      if not continuation(current.next) then return word end
      anchor.link = current.next
      current = current.next.next
    end
  end

  luatexbase.add_to_callback('pre_linebreak_filter', function(head)
    local available, current = nil, head
    while current do
      if current.id == vlist and not continuation(current.prev) then
        local word = read_word(current)
        if word then
          if not available then
            available = tex.hsize - math.max(tex.skip.leftskip.width, 0)
              - math.max(tex.skip.rightskip.width, 0) - math.abs(tex.hangindent)
            for _, line in ipairs(tex.parshape or {}) do available = math.min(available, line[2]) end
          end
          local last, words, run = word[#word], {word}, {}
          for _, anchor in ipairs(word) do run[#run + 1] = anchor end
          while marked_space(last.stack.next) do
            local space = last.stack.next
            local next_word = read_word(space.next)
            if not next_word then break end
            last.link = space
            last = next_word[#next_word]
            words[#words + 1] = next_word
            for _, anchor in ipairs(next_word) do run[#run + 1] = anchor end
          end
          local fitted = space_run(head, run, available)
          if fitted then
            head = fitted
          elseif #words > 1 then
            for _, part in ipairs(words) do
              part[#part].link = nil
              head = space_run(head, part, available) or head
            end
          end
          current = last.stack
        end
      end
      current = current.next
    end
    return head
  end, 'ulsbs-annotation-spacing')

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
    local info = {level = 0, refs = {}, bars = {}, repetitions = {}, inline_repeats = {}, preps = {}}
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
    local function circles(list, anchor)
      visit_circles(list, 0, function(n, raised, center, radius)
        local level = node.has_attribute(n, a.note_level) or 2
        local chord_base = anchor + raised - assert(node.has_attribute(n, a.note_raise))
        local base = assert(node.has_attribute(n, a.chord_a))
        chord_reference(chord_base, base, false)
        info.level = math.max(info.level, level)
        local circle = {level = level, bottom = anchor + raised + center - radius,
          base = 2 * radius, anchor = chord_base, center = center,
          normal = node.has_attribute(n, a.normal_raise), high = node.has_attribute(n, a.high_raise)}
        notes[#notes + 1] = circle
        if level >= 2 then reference(level, circle.bottom, circle.base) end
      end)
    end
    -- Read an annotation's visible chord metric and any retained melody circles.
    local function raw_anchor(n, baseline)
      local metric = node.has_attribute(n, a.row)
      if metric then info.annotated = true end
      if metric and metric > 0 then
        local base = node.has_attribute(n, a.chord_a) or find_attribute(n.list, a.chord_a)
        assert(base, 'visible chord must retain its capital-A metric')
        info.level = math.max(info.level, 1)
        chord_reference(baseline, base, true)
      end
      circles(n.list, baseline)
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
          elseif node.has_attribute(n, a.inline_repeat) then
            info.inline_repeats[#info.inline_repeats + 1] = {box = n, baseline = raised}
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
  -- The upper colon follows visible annotations or the stanza's chord minimum.
  local function inline_repeat_geometry(entry, info, minimum)
    local box = entry.box
    local bar, colon = first_of(rule, box.list), first_of(glyph, box.list)
    local top, level = target(info, configuration(box), 'measure', minimum)
    local reach = math.max(0, top - entry.baseline)
    local height, depth = colon.height, colon.depth
    if info.annotated or level > 0 then
      local dots = first_of(hlist, box.list)
      if not dots then
        dots = node.new(hlist)
        dots.dir, dots.height, dots.depth = box.dir, colon.height, colon.depth
        dots.shift = -node.has_attribute(box, a.inline_raise)
        dots.list = node.copy(colon)
        box.list = node.insert_before(box.list, colon, dots)
      end
      reach = math.max(reach, node.has_attribute(box, a.inline_repeat), dots.height - dots.shift + tex.sp('.5pt'))
      depth = math.max(depth, dots.depth + dots.shift)
    end
    bar.height = reach
    box.height = math.max(reach, height)
    box.depth = math.max(bar.depth, depth)
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
    for _, entry in ipairs(info.inline_repeats) do inline_repeat_geometry(entry, info, minimum) end
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
      for _, entry in ipairs(info.inline_repeats) do
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
  -- The prefix was typeset once, on the first line of the paragraph. Copy its
  -- ink (including color) to wrapped lines at the same x, with no added advance.
  local function repeat_prefix(line)
    local x = line.shift
    for n in node.traverse(line.list) do
      if n.id == hlist and node.has_attribute(n, a.repeat_prefix) then return n, x end
      if n.id == glue then x = x + node.effective_glue(n, line)
      elseif n.id == kern then x = x + n.kern
      elseif n.width then x = x + n.width end
    end
  end
  local function copy_repeat_prefix(line, prefix, x)
    local copy = node.copy(prefix)
    local function continuation_rules(list)
      for n in node.traverse(list) do
        if n.id == rule and node.has_attribute(n, a.repetition) then
          node.unset_attribute(n, a.repetition_start)
          n.height = node.has_attribute(n, a.normal_height)
        elseif n.id == hlist then continuation_rules(n.list) end
      end
    end
    continuation_rules(copy.list)
    copy.width = 0
    local offset = node.new(kern)
    offset.kern = math.floor(x - line.shift + .5)
    local overlay = node.new(hlist)
    overlay.dir = line.dir
    overlay.list = node.insert_before(copy, copy, offset)
    line.list = node.insert_before(line.list, line.list, overlay)
  end
  -- Paragraph phase: capture line policy and baseline glue while still in scope,
  -- then resolve retained ink without repacking or fitting the stanza's lines.
  luatexbase.add_to_callback('post_linebreak_filter', function(head)
    local first_line = first_of(hlist, head)
    local prefix, x
    if first_line then prefix, x = repeat_prefix(first_line) end
    -- Copy before fitting records the first line's authored overlap on its rules.
    if prefix then
      for line in node.traverse_id(hlist, first_line.next) do copy_repeat_prefix(line, prefix, x) end
    end
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
  -- note anchors), fit marked lines, and repair baseline glue.
  -- box_id is the caller-owned TeX box register; its list stays owned by that box.
  function M.finish_verse(box_id)
    local box = tex.box[box_id]
    if not box.list then return end
    -- Keep each semantic end on its final lyric line, not after a potential
    -- page/column break. Several nested repeats can close on the same line.
    local previous_line, cursor = nil, box.list
    while cursor do
      local next_node = cursor.next
      if cursor.id == hlist and (node.getproperty(cursor) or {}).ulsbs_music then
        previous_line = cursor
      elseif previous_line and cursor.id == whatsit and node.has_attribute(cursor, a.repetition_end) then
        box.list = node.remove(box.list, cursor)
        cursor.prev, cursor.next = nil, nil
        previous_line.list = node.insert_after(previous_line.list, node.tail(previous_line.list), cursor)
      end
      cursor = next_node
    end
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
    local previous_depth, pending
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
