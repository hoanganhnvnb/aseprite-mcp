local DIRECTIONS = {
  forward = AniDir.FORWARD,
  reverse = AniDir.REVERSE,
  pingpong = AniDir.PING_PONG,
  pingpong_reverse = AniDir.PING_PONG_REVERSE,
}

local function cel_layers(spr)
  local out = {}
  for _, layer in ipairs(all_layers(spr)) do
    if not layer.isGroup then
      table.insert(out, layer)
    end
  end
  return out
end

-- Makes the cel at `to` an independent copy of the one at `from`, or removes it when
-- `from` has no cel. The old target cel is deleted rather than overwritten: assigning
-- to a linked cel would change every frame it is linked to.
local function copy_cel(spr, layer, from, to)
  local old = layer:cel(to)
  local src = layer:cel(from)
  if src == nil then
    if old ~= nil then
      spr:deleteCel(old)
      return "cleared"
    end
    return nil
  end
  if old ~= nil then
    spr:deleteCel(old)
  end
  local cel = spr:newCel(layer, to, src.image:clone(), src.position)
  cel.opacity = src.opacity
  cel.zIndex = src.zIndex
  cel.color = src.color
  cel.data = src.data
  return "copied"
end

local function set_duration(spr, frames, ms)
  for _, n in ipairs(frames) do
    spr.frames[n].duration = ms / 1000
  end
end

OPS.add_frames = function(ctx, p)
  local spr = need_sprite(ctx)
  local count = #spr.frames
  local after = p.after or count
  if after < 0 or after > count then
    fail(string.format("after=%d is out of range: use 0 to %d (sprite has %d frames)",
      after, count, count))
  end
  local created = {}
  for i = 1, p.count do
    spr:newEmptyFrame(after + i)
    created[i] = after + i
  end
  if p.copy_content then
    -- With after=0 the old first frame now sits right after the new ones.
    local from = after > 0 and after or p.count + 1
    for _, layer in ipairs(cel_layers(spr)) do
      for _, n in ipairs(created) do
        copy_cel(spr, layer, from, n)
      end
    end
  end
  if p.duration_ms then
    set_duration(spr, created, p.duration_ms)
  end
  return { frames = created, frame_count = #spr.frames }
end

OPS.delete_frames = function(ctx, p)
  local spr = need_sprite(ctx)
  local frames = frame_list(spr, p.frames)
  if #frames >= #spr.frames then
    fail(string.format("cannot delete all %d frames: a sprite needs at least one frame",
      #spr.frames))
  end
  for i = #frames, 1, -1 do
    spr:deleteFrame(frames[i])
  end
  return { deleted = frames, frame_count = #spr.frames }
end

OPS.set_frame_duration = function(ctx, p)
  local spr = need_sprite(ctx)
  local frames = frame_list(spr, p.frames)
  set_duration(spr, frames, p.duration_ms)
  return { frames = frames, duration_ms = p.duration_ms }
end

local function in_group(spr, layer, group)
  local parent = layer.parent
  while parent ~= spr do
    if parent == group then
      return true
    end
    parent = parent.parent
  end
  return false
end

local function copy_layers(spr, names)
  if names == nil then
    return cel_layers(spr)
  end
  local out, seen = {}, {}
  local function add(layer)
    if not seen[layer] then
      seen[layer] = true
      table.insert(out, layer)
    end
  end
  for _, name in ipairs(names) do
    local layer = find_layer(spr, name)
    if layer == nil then
      fail("layer '" .. name .. "' not found")
    end
    if layer.isGroup then
      for _, child in ipairs(all_layers(spr)) do
        if not child.isGroup and in_group(spr, child, layer) then
          add(child)
        end
      end
    else
      add(layer)
    end
  end
  return out
end

local function link_cels(spr, layer, source, frames)
  app.sprite = spr
  app.range.layers = { layer }
  local range = { spr.frames[source] }
  for _, n in ipairs(frames) do
    table.insert(range, spr.frames[n])
  end
  app.range.frames = range
  -- The command skips locked layers; the plain copy above ignores the lock, so match it.
  local editable = layer.isEditable
  layer.isEditable = true
  app.command.LinkCels()
  layer.isEditable = editable
  app.range:clear()
  local image = layer:cel(source).image
  for _, n in ipairs(frames) do
    local cel = layer:cel(n)
    if cel == nil or cel.image ~= image then
      fail(string.format("Aseprite did not link the cel of '%s' in frame %d",
        layer_path(layer), n))
    end
  end
end

OPS.copy_frames = function(ctx, p)
  local spr = need_sprite(ctx)
  local count = #spr.frames
  if p.source < 1 or p.source > count then
    fail(string.format("source frame %d is out of range (sprite has %d frames)", p.source, count))
  end
  local layers = copy_layers(spr, p.layers)
  local appended = {}
  local targets
  if p.append then
    for i = 1, p.append do
      appended[i] = spr:newEmptyFrame(count + i).frameNumber
    end
    targets = appended
  else
    targets = frame_list(spr, p.targets)
  end
  local frames = {}
  for _, n in ipairs(targets) do
    if n ~= p.source then
      table.insert(frames, n)
    end
  end

  local copied, cleared, paths = 0, 0, {}
  for _, layer in ipairs(layers) do
    table.insert(paths, layer_path(layer))
    local filled = {}
    for _, n in ipairs(frames) do
      if p.mode ~= "missing_only" or layer:cel(n) == nil then
        local what = copy_cel(spr, layer, p.source, n)
        if what == "copied" then
          copied = copied + 1
          table.insert(filled, n)
        elseif what == "cleared" then
          cleared = cleared + 1
        end
      end
    end
    if p.link and #filled > 0 then
      link_cels(spr, layer, p.source, filled)
    end
  end
  return {
    source = p.source,
    frames = frames,
    appended = appended,
    layers = paths,
    cels_copied = copied,
    cels_cleared = cleared,
  }
end

local function find_tag(spr, name)
  for _, tag in ipairs(spr.tags) do
    if tag.name == name then
      return tag
    end
  end
  return nil
end

OPS.set_tag = function(ctx, p)
  local spr = need_sprite(ctx)
  local count = #spr.frames
  for _, key in ipairs({ "from_frame", "to_frame" }) do
    if p[key] < 1 or p[key] > count then
      fail(string.format("%s %d is out of range (sprite has %d frames)", key, p[key], count))
    end
  end
  if p.from_frame > p.to_frame then
    fail(string.format("from_frame %d is after to_frame %d", p.from_frame, p.to_frame))
  end
  local direction = DIRECTIONS[p.direction or "forward"]
  if direction == nil then
    fail("unknown tag direction '" .. tostring(p.direction) .. "'")
  end
  local tag = find_tag(spr, p.name)
  local created = tag == nil
  if created then
    tag = spr:newTag(p.from_frame, p.to_frame)
    tag.name = p.name
  elseif p.from_frame > tag.toFrame.frameNumber then
    -- Move the end first so the tag never has from > to in between.
    tag.toFrame = p.to_frame
    tag.fromFrame = p.from_frame
  else
    tag.fromFrame = p.from_frame
    tag.toFrame = p.to_frame
  end
  tag.aniDir = direction
  tag.repeats = p["repeat"] or 0
  return {
    tag = tag.name,
    from_frame = tag.fromFrame.frameNumber,
    to_frame = tag.toFrame.frameNumber,
    direction = p.direction or "forward",
    ["repeat"] = tag.repeats,
    created = created,
  }
end

OPS.delete_tag = function(ctx, p)
  local spr = need_sprite(ctx)
  local tag = find_tag(spr, p.name)
  if tag == nil then
    fail("tag '" .. p.name .. "' not found")
  end
  spr:deleteTag(tag)
  return { deleted = p.name, tags_left = #spr.tags }
end
