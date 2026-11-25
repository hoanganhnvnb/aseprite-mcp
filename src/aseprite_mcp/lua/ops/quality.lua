-- Layers whose cels count for `layer`: the layer itself, or every layer in a group.
local function members(spr, layer)
  if not layer.isGroup then
    return { layer }
  end
  local out = {}
  for _, child in ipairs(all_layers(spr)) do
    if not child.isGroup and is_inside(spr, child, layer) then
      table.insert(out, child)
    end
  end
  return out
end

-- A background layer is opaque even where its stored value is the transparent index.
local function has_pixels(layer, cel)
  return cel ~= nil and (layer.isBackground or not cel.image:isEmpty())
end

local function frames_with_pixels(spr, layer)
  local found = {}
  for _, member in ipairs(members(spr, layer)) do
    for _, cel in ipairs(member.cels) do
      if has_pixels(member, cel) then
        found[cel.frameNumber] = true
      end
    end
  end
  return found
end

local function shown(spr, layer)
  local node = layer
  while node ~= spr do
    if not node.isVisible then
      return false
    end
    node = node.parent
  end
  return true
end

local function count_named(spr, name)
  local n = 0
  for _, layer in ipairs(all_layers(spr)) do
    if layer.name == name then
      n = n + 1
    end
  end
  return n
end

local function set_of(list)
  local out = {}
  for _, v in ipairs(list) do
    out[v] = true
  end
  return out
end

local function range_frames(spr, name, spec)
  local ok, res = pcall(frame_list, spr, spec)
  if not ok then
    local reason = type(res) == "table" and res.user or tostring(res)
    fail("layer_frame_ranges['" .. name .. "']: " .. reason)
  end
  return set_of(res)
end

local function opaque_value(spr)
  if spr.colorMode == ColorMode.RGB then
    return app.pixelColor.rgba(0, 0, 0, 255)
  elseif spr.colorMode == ColorMode.GRAY then
    return app.pixelColor.graya(0, 255)
  end
  return spr.transparentColor == 0 and 1 or 0
end

-- Draws the pixels of `layers` in frame n into mask (canvas sized, sprite colour mode)
-- and returns the canvas area they touch, or nil.
local function fill_mask(spr, mask, layers, n)
  mask:clear(clear_value(spr))
  local area
  for _, layer in ipairs(layers) do
    local cel = layer:cel(n)
    if not layer.isTilemap and has_pixels(layer, cel) then
      local box = cel.bounds:intersect(spr.bounds)
      if not box.isEmpty then
        if layer.isBackground then
          mask:clear(opaque_value(spr))
        else
          mask:drawImage(cel.image, cel.position)
        end
        area = area and area:union(box) or box
      end
    end
  end
  return area
end

local function overlap(spr, a, b, area)
  local count, x0, y0, x1, y1 = 0, math.huge, math.huge, -1, -1
  for y = area.y, area.y + area.height - 1 do
    for x = area.x, area.x + area.width - 1 do
      if not is_transparent(spr, a:getPixel(x, y)) and not is_transparent(spr, b:getPixel(x, y)) then
        count = count + 1
        x0, y0 = math.min(x0, x), math.min(y0, y)
        x1, y1 = math.max(x1, x), math.max(y1, y)
      end
    end
  end
  if count == 0 then
    return 0
  end
  return count, { x = x0, y = y0, w = x1 - x0 + 1, h = y1 - y0 + 1 }
end

OPS.check_animation = function(ctx, p)
  local spr = need_sprite(ctx)
  local frames = frame_list(spr, p.frames)
  local ranges = {}
  for name, spec in pairs(p.layer_frame_ranges or {}) do
    table.insert(ranges, { name = name, allowed = range_frames(spr, name, spec) })
  end
  table.sort(ranges, function(a, b)
    return a.name < b.name
  end)

  local findings, total = {}, 0
  local function add(kind, severity, message, extra)
    total = total + 1
    if #findings < p.max_findings then
      local f = { kind = kind, severity = severity, message = message }
      for k, v in pairs(extra or {}) do
        f[k] = v
      end
      table.insert(findings, f)
    end
  end

  local looked_up = {}
  local function lookup(name)
    local entry = looked_up[name]
    if entry == nil then
      entry = { layer = find_layer(spr, name) }
      looked_up[name] = entry
      if entry.layer == nil then
        add("missing_layer", "error", "layer '" .. name .. "' does not exist", { layer = name })
      else
        local n = count_named(spr, name)
        if n > 1 then
          add("ambiguous_layer", "warning", string.format(
            "%d layers are named '%s'; '%s' was checked, use a 'group/name' path for another",
            n, name, layer_path(entry.layer)), { layer = layer_path(entry.layer) })
        end
      end
    end
    return entry.layer
  end

  for _, name in ipairs(p.required_layers or {}) do
    lookup(name)
  end

  for _, range in ipairs(ranges) do
    local layer = lookup(range.name)
    if layer ~= nil then
      local path = layer_path(layer)
      local filled = frames_with_pixels(spr, layer)
      for _, n in ipairs(frames) do
        if filled[n] and not range.allowed[n] then
          add("out_of_range", "error", string.format(
            "'%s' has pixels in frame %d, outside its frames", path, n),
            { layer = path, frame = n })
        elseif not filled[n] and range.allowed[n] then
          add("missing_in_range", "warning", string.format(
            "'%s' has no pixels in frame %d, inside its frames", path, n),
            { layer = path, frame = n })
        end
      end
    end
  end

  local pairs_to_check = {}
  for _, pair in ipairs(p.overlap_pairs or {}) do
    local a, b = lookup(pair[1]), lookup(pair[2])
    if a ~= nil and b ~= nil then
      table.insert(pairs_to_check, { a, b })
    end
  end
  if #pairs_to_check > 0 then
    -- Two canvas-sized masks for the whole call: images are not counted by Lua's
    -- collector, so allocating them per frame piles up memory.
    local mask_a = new_image(spr, spr.width, spr.height)
    local mask_b = new_image(spr, spr.width, spr.height)
    for _, pair in ipairs(pairs_to_check) do
      local la, lb = members(spr, pair[1]), members(spr, pair[2])
      local pa, pb = layer_path(pair[1]), layer_path(pair[2])
      for _, n in ipairs(frames) do
        local area_a = fill_mask(spr, mask_a, la, n)
        local area_b = area_a and fill_mask(spr, mask_b, lb, n)
        local area = area_b and area_a:intersect(area_b)
        if area and not area.isEmpty then
          local count, bounds = overlap(spr, mask_a, mask_b, area)
          if count > 0 then
            add("overlap", "error", string.format(
              "'%s' and '%s' overlap on %d pixel%s in frame %d", pa, pb, count,
              count == 1 and "" or "s", n),
              { layer = pa, other_layer = pb, frame = n, pixels = count, bounds = bounds })
          end
        end
      end
    end
  end

  local layers = cel_layers(spr)
  for _, n in ipairs(frames) do
    local visible = false
    for _, layer in ipairs(layers) do
      local cel = layer:cel(n)
      if has_pixels(layer, cel) then
        if cel.bounds:intersect(spr.bounds).isEmpty then
          add("cel_off_canvas", "warning", string.format(
            "the cel of '%s' in frame %d lies entirely outside the canvas", layer_path(layer), n),
            { layer = layer_path(layer), frame = n })
        elseif shown(spr, layer) then
          visible = true
        end
      end
    end
    if not visible then
      add("empty_frame", "warning", string.format("frame %d shows no pixels", n), { frame = n })
    end
    local ms = math.floor(spr.frames[n].duration * 1000 + 0.5)
    if ms < 10 or ms > 10000 then
      add("frame_duration", "warning", string.format(
        "frame %d lasts %d ms (expected 10 to 10000)", n, ms), { frame = n, duration_ms = ms })
    end
  end

  return { frames_checked = #frames, findings = findings, finding_count = total }
end

local function split_path(name)
  local cut
  for i = #name, 1, -1 do
    if name:sub(i, i) == "/" then
      cut = i
      break
    end
  end
  if cut == nil then
    return nil, name
  end
  return name:sub(1, cut - 1), name:sub(cut + 1)
end

-- Where each missing layer of `names` goes: {parent, name, path}. Nothing is created.
local function plan_new_layers(spr, names)
  local plan, planned = {}, {}
  for _, path in ipairs(names) do
    if find_layer(spr, path) == nil and not planned[path] then
      planned[path] = true
      local parent_path, name = split_path(path)
      local parent = spr
      if parent_path ~= nil then
        parent = find_layer(spr, parent_path)
        if parent == nil or not parent.isGroup then
          fail(string.format("cannot create '%s': '%s' is not an existing group",
            path, parent_path))
        end
      end
      if name == "" then
        fail("cannot create '" .. path .. "': the layer name is empty")
      end
      table.insert(plan, { parent = parent, name = name })
    end
  end
  return plan
end

local function reorder(spr, names)
  local listed, parent = {}, nil
  for i, name in ipairs(names) do
    local layer = get_layer(spr, name)
    if parent ~= nil and layer.parent ~= parent then
      fail(string.format("layer_order mixes layers from different groups ('%s' and '%s')",
        layer_path(listed[1]), layer_path(layer)))
    end
    parent = layer.parent
    for _, seen in ipairs(listed) do
      if seen == layer then
        fail("layer_order names '" .. layer_path(layer) .. "' twice")
      end
    end
    listed[i] = layer
  end

  local slots = {}
  for i, layer in ipairs(listed) do
    slots[i] = layer.stackIndex
  end
  table.sort(slots)
  -- Layer objects are new wrappers on every access, so they are compared with ==
  -- rather than used as table keys.
  local function is_listed(layer)
    for _, other in ipairs(listed) do
      if other == layer then
        return true
      end
    end
    return false
  end
  local final = {}
  for i, layer in ipairs(listed) do
    final[slots[i]] = layer
  end
  for i, layer in ipairs(parent.layers) do
    if not is_listed(layer) then
      final[i] = layer
    end
  end

  local moves = 0
  for i, layer in ipairs(final) do
    if layer.stackIndex ~= i then
      if layer.isBackground then
        fail("'" .. layer_path(layer) .. "' is the background layer and must stay at the bottom")
      end
      if is_listed(layer) then
        require_editable(layer)
        moves = moves + 1
      end
    end
  end
  for i, layer in ipairs(final) do
    if layer.stackIndex ~= i then
      layer.stackIndex = i
    end
  end
  local order = {}
  for i, layer in ipairs(listed) do
    order[i] = layer_path(layer)
  end
  return order, moves
end

OPS.repair_animation = function(ctx, p)
  local spr = need_sprite(ctx)
  local frames = frame_list(spr, p.frames)
  local creating = plan_new_layers(spr, p.ensure_layers or {})
  local pending = set_of(p.ensure_layers or {})
  local ranges = {}
  for name, spec in pairs(p.layer_frame_ranges or {}) do
    local allowed = range_frames(spr, name, spec)
    if find_layer(spr, name) == nil and not pending[name] then
      fail("layer '" .. name .. "' not found")
    end
    table.insert(ranges, { name = name, allowed = allowed })
  end
  table.sort(ranges, function(a, b)
    return a.name < b.name
  end)

  local created = {}
  for _, entry in ipairs(creating) do
    local layer = spr:newLayer()
    layer.name = entry.name
    layer.parent = entry.parent
    layer.stackIndex = #entry.parent.layers
    table.insert(created, layer_path(layer))
  end

  local order, moves = nil, 0
  if p.layer_order ~= nil then
    order, moves = reorder(spr, p.layer_order)
  end

  -- Everything that would change is checked first, so a refusal leaves no half-repair.
  local reports, missing, work = {}, {}, {}
  for _, range in ipairs(ranges) do
    local layer = get_layer(spr, range.name)
    local path = layer_path(layer)
    local filled = frames_with_pixels(spr, layer)
    local outside, absent = {}, {}
    for _, n in ipairs(frames) do
      if filled[n] and not range.allowed[n] then
        table.insert(outside, n)
      elseif not filled[n] and range.allowed[n] then
        table.insert(absent, n)
      end
    end
    if #absent > 0 then
      table.insert(missing, { layer = path, frames = absent })
    end
    if #outside > 0 then
      table.insert(reports, { layer = path, frames = outside })
      if p.out_of_range == "hide" and layer.isVisible then
        require_editable(layer)
        table.insert(work, { hide = layer })
      elseif p.out_of_range == "delete" then
        local is_out = set_of(outside)
        for _, member in ipairs(members(spr, layer)) do
          for _, cel in ipairs(member.cels) do
            if is_out[cel.frameNumber] and has_pixels(member, cel) then
              require_editable(member)
              if member.isBackground then
                fail("'" .. layer_path(member) .. "' is the background layer; its cels "
                  .. "cannot be deleted")
              end
              table.insert(work, { delete = cel })
            end
          end
        end
      end
    end
  end

  local hidden, deleted = {}, 0
  for _, job in ipairs(work) do
    if job.hide ~= nil then
      job.hide.isVisible = false
      table.insert(hidden, layer_path(job.hide))
    else
      spr:deleteCel(job.delete)
      deleted = deleted + 1
    end
  end

  local changed = #created > 0 or moves > 0 or #hidden > 0 or deleted > 0
  ctx.changed = changed
  return {
    changed = changed,
    created = created,
    order = order,
    moved = moves,
    action = p.out_of_range,
    out_of_range = reports,
    missing_in_range = missing,
    hidden = hidden,
    deleted_cels = deleted,
  }
end

-- copy_layers

local function all_layers_in(group)
  local out = {}
  for _, child in ipairs(group.layers) do
    table.insert(out, child)
    if child.isGroup then
      for _, inner in ipairs(all_layers_in(child)) do
        table.insert(out, inner)
      end
    end
  end
  return out
end

local function source_layers(src, names)
  local chosen = {}
  for _, name in ipairs(names) do
    local layer = find_layer(src, name)
    if layer == nil then
      fail("layer '" .. name .. "' not found in the source")
    end
    local dup = false
    for _, other in ipairs(chosen) do
      if other == layer then
        dup = true
      elseif is_inside(src, layer, other) or is_inside(src, other, layer) then
        local outer = is_inside(src, layer, other) and other or layer
        local inner = outer == layer and other or layer
        fail(string.format("'%s' is inside '%s', which is copied too",
          layer_path(inner), layer_path(outer)))
      end
    end
    if not dup then
      table.insert(chosen, layer)
    end
  end
  for _, layer in ipairs(chosen) do
    for _, member in ipairs(layer.isGroup and all_layers_in(layer) or { layer }) do
      if member.isTilemap then
        fail("'" .. layer_path(member) .. "' is a tilemap layer; tilemaps cannot be copied")
      end
    end
  end
  return chosen
end

local function top_level_named(spr, name)
  local out = {}
  for _, layer in ipairs(spr.layers) do
    if layer.name == name then
      table.insert(out, layer)
    end
  end
  return out
end

local function last_cel_frame(layer)
  local last = 0
  for _, member in ipairs(layer.isGroup and all_layers_in(layer) or { layer }) do
    if not member.isGroup then
      for _, cel in ipairs(member.cels) do
        last = math.max(last, cel.frameNumber)
      end
    end
  end
  return last
end

local function copy_cels(spr, from, to, stats)
  local first_of, links = {}, {}
  for n = 1, #from.sprite.frames do
    local cel = from:cel(n)
    if cel ~= nil and n > #spr.frames then
      stats.skipped = stats.skipped + 1
    elseif cel ~= nil then
      local id = cel.image.id
      local first = first_of[id]
      if first == nil then
        first_of[id] = n
        put_cel(spr, to, n, cel.image:clone(), cel.position, cel_props(cel))
      else
        -- Frames sharing an image in the source are linked to the first copy below.
        links[first] = links[first] or {}
        table.insert(links[first], n)
      end
      stats.cels = stats.cels + 1
    end
  end
  for first, frames in pairs(links) do
    link_cels(spr, to, first, frames)
  end
end

local function copy_tree(spr, from, parent, stats)
  local layer = from.isGroup and spr:newGroup() or spr:newLayer()
  layer.parent = parent
  layer.stackIndex = #parent.layers
  layer.name = from.name
  layer.isVisible = from.isVisible
  layer.color = from.color
  layer.data = from.data
  if from.isGroup then
    for _, child in ipairs(from.layers) do
      copy_tree(spr, child, layer, stats)
    end
  else
    if not from.isBackground then
      layer.opacity = from.opacity
      layer.blendMode = from.blendMode
    end
    copy_cels(spr, from, layer, stats)
  end
  return layer
end

local MODE_NAMES = {
  [ColorMode.RGB] = "rgb",
  [ColorMode.GRAY] = "grayscale",
  [ColorMode.INDEXED] = "indexed",
}

local function copy_from(spr, src, p)
  if src.colorMode ~= spr.colorMode then
    fail(string.format("the source is %s but the target is %s; convert one of them first",
      MODE_NAMES[src.colorMode] or "?", MODE_NAMES[spr.colorMode] or "?"))
  end
  local chosen = source_layers(src, p.layers)
  local replacing, names = {}, {}
  for _, layer in ipairs(chosen) do
    if names[layer.name] then
      fail("two copied layers are named '" .. layer.name .. "'")
    end
    names[layer.name] = true
    local clash = top_level_named(spr, layer.name)
    if #clash > 0 and not p.replace then
      fail("the target already has a layer '" .. layer.name .. "'; pass replace=true to "
        .. "replace it")
    elseif #clash > 1 then
      fail(string.format("the target has %d top-level layers named '%s'; cannot tell which "
        .. "to replace", #clash, layer.name))
    elseif #clash == 1 then
      require_editable(clash[1])
      replacing[layer] = clash[1]
    end
  end

  local added = 0
  if p.create_missing_frames then
    local last = 0
    for _, layer in ipairs(chosen) do
      last = math.max(last, last_cel_frame(layer))
    end
    while #spr.frames < last do
      local n = #spr.frames + 1
      local frame = spr:newEmptyFrame(n)
      frame.duration = src.frames[n].duration
      added = added + 1
    end
  end

  local stats = { cels = 0, skipped = 0 }
  local paths, replaced = {}, {}
  for _, from in ipairs(chosen) do
    local layer = copy_tree(spr, from, spr, stats)
    local old = replacing[from]
    if old ~= nil then
      local index = old.stackIndex
      spr:deleteLayer(old)
      layer.stackIndex = index
      table.insert(replaced, layer.name)
    end
    table.insert(paths, layer_path(layer))
  end
  return {
    layers = paths,
    cels = stats.cels,
    frames_added = added,
    skipped_cels = stats.skipped,
    replaced = replaced,
  }
end

OPS.copy_layers = function(ctx, p)
  local spr = need_sprite(ctx)
  local src = app.open(p.source)
  if src == nil then
    fail("Aseprite could not open " .. p.source)
  end
  local ok, res = pcall(copy_from, spr, src, p)
  src:close()
  app.sprite = spr
  if not ok then
    error(res, 0)
  end
  return res
end
