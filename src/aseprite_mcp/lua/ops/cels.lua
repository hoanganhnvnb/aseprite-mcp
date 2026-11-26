local SCALE_MIN, SCALE_MAX = 0.05, 16
-- Results list at most this many frames; longer ranges only report the count.
local MAX_LISTED = 64

local function cel_layer(spr, name)
  local layer = get_layer(spr, name)
  local path = layer_path(layer)
  if layer.isGroup then
    fail("'" .. path .. "' is a group; groups have no cels of their own")
  end
  if layer.isBackground then
    fail("'" .. path .. "' is the background layer; its cels always cover the canvas at 0,0, "
      .. "so cel tools cannot move, clear or tween them. Draw on another layer instead")
  end
  require_editable(layer)
  return layer, path
end

local function frames_of(spr, spec, at_least)
  local frames = frame_list(spr, spec)
  if at_least and #frames < at_least then
    fail(string.format("needs at least %d frames, got %d", at_least, #frames))
  end
  return frames
end

local function existing_cels(layer, path, frames)
  local out = {}
  for i, n in ipairs(frames) do
    out[i] = layer:cel(n)
    if out[i] == nil then
      fail(string.format("'%s' has no cel in frame %d", path, n))
    end
  end
  return out
end

local function empty_image(spr, layer)
  if layer.isTilemap then
    local img = Image(ImageSpec { width = 1, height = 1, colorMode = ColorMode.TILEMAP })
    img:clear(0)
    return img
  end
  return new_image(spr, 1, 1)
end

local function listed(list, entry)
  if #list < MAX_LISTED then
    table.insert(list, entry)
  end
end

OPS.set_cel = function(ctx, p)
  local spr = need_sprite(ctx)
  local layer, path = cel_layer(spr, p.layer)
  local frames = frames_of(spr, p.frames)
  local moves = p.x ~= nil or p.y ~= nil
  local users = image_users(layer)
  local created, cels = 0, {}
  for _, n in ipairs(frames) do
    local cel = layer:cel(n)
    if cel == nil then
      if not p.create then
        fail(string.format("'%s' has no cel in frame %d; pass create=true to add one", path, n))
      end
      cel = spr:newCel(layer, n, empty_image(spr, layer), Point(0, 0))
      created = created + 1
    elseif moves or p.opacity ~= nil then
      cel = own_cel(spr, layer, cel, users)
    end
    if moves then
      local x, y = cel.position.x, cel.position.y
      if p.relative then
        x, y = x + (p.x or 0), y + (p.y or 0)
      else
        x, y = p.x or x, p.y or y
      end
      cel.position = Point(x, y)
    end
    if p.opacity ~= nil then
      cel.opacity = p.opacity
    end
    if p.z_index ~= nil then
      cel.zIndex = p.z_index
    end
    listed(cels, {
      frame = n,
      x = cel.position.x,
      y = cel.position.y,
      opacity = cel.opacity,
      z_index = cel.zIndex,
    })
  end
  return { layer = path, frames = #frames, created = created, cels = cels }
end

OPS.clear_cels = function(ctx, p)
  local spr = need_sprite(ctx)
  local layer, path = cel_layer(spr, p.layer)
  local removed = 0
  for _, n in ipairs(frames_of(spr, p.frames)) do
    local cel = layer:cel(n)
    if cel ~= nil then
      spr:deleteCel(cel)
      removed = removed + 1
    end
  end
  return { layer = path, removed = removed }
end

local function lerp(a, b, k)
  return a + (b - a) * k
end

local function clamp(v, low, high)
  return math.max(low, math.min(high, v))
end

-- Eased progress for each frame; with loop the last frame stops one step short of
-- the end so the loop does not show the same pose twice.
local function progress(count, easing, loop)
  local ease = EASINGS[easing or "linear"]
  if ease == nil then
    fail("unknown easing '" .. tostring(easing) .. "'")
  end
  local steps = loop and count or count - 1
  local out = {}
  for i = 1, count do
    out[i] = ease((i - 1) / steps)
  end
  return out
end

local function anchored(bounds, w, h, anchor)
  if anchor == "top_left" then
    return Point(bounds.x, bounds.y)
  end
  local x = bounds.x + round_half_away((bounds.width - w) / 2)
  if anchor == "bottom" then
    return Point(x, bounds.y + bounds.height - h)
  end
  return Point(x, bounds.y + round_half_away((bounds.height - h) / 2))
end

local function tween_scale(spr, layer, path, frames, steps, p)
  if layer.isTilemap then
    fail("cannot scale the tilemap layer '" .. path .. "': its cels hold tile indices")
  end
  local source = p.source_frame or frames[1]
  if source > #spr.frames then
    fail(string.format("source_frame %d is out of range (sprite has %s)",
      source, plural(#spr.frames, "frame")))
  end
  local src = layer:cel(source)
  if src == nil then
    fail(string.format("'%s' has no cel in source frame %d", path, source))
  end
  local image, bounds, props = src.image:clone(), src.bounds, cel_props(src)
  local limit = p.max_size

  local sizes = {}
  for i, k in ipairs(steps) do
    local sx = clamp(lerp(p.start[1], p["end"][1], k), SCALE_MIN, SCALE_MAX)
    local sy = clamp(lerp(p.start[2], p["end"][2], k), SCALE_MIN, SCALE_MAX)
    local w = math.max(1, round_half_away(image.width * sx))
    local h = math.max(1, round_half_away(image.height * sy))
    if w > limit or h > limit then
      fail(string.format("frame %d: the scaled cel would be %dx%d, larger than %dx%d",
        frames[i], w, h, limit, limit))
    end
    sizes[i] = { w, h }
  end

  local values = {}
  for i, n in ipairs(frames) do
    local w, h = sizes[i][1], sizes[i][2]
    local img = image:clone()
    if w ~= img.width or h ~= img.height then
      img:resize { width = w, height = h, method = "nearest" }
    end
    local pos = anchored(bounds, w, h, p.anchor or "center")
    put_cel(spr, layer, n, img, pos, props)
    listed(values, { frame = n, x = pos.x, y = pos.y, width = w, height = h })
  end
  return values
end

OPS.tween_cels = function(ctx, p)
  local spr = need_sprite(ctx)
  local layer, path = cel_layer(spr, p.layer)
  local frames = frames_of(spr, p.frames, 2)
  local steps = progress(#frames, p.easing, p.loop)
  local values = {}
  if p.property == "scale" then
    values = tween_scale(spr, layer, path, frames, steps, p)
  elseif p.property == "position" or p.property == "opacity" then
    local cels = existing_cels(layer, path, frames)
    local users = image_users(layer)
    for i, n in ipairs(frames) do
      local cel = own_cel(spr, layer, cels[i], users)
      local k = steps[i]
      if p.property == "position" then
        local x = round_half_away(lerp(p.start[1], p["end"][1], k))
        local y = round_half_away(lerp(p.start[2], p["end"][2], k))
        cel.position = Point(x, y)
        listed(values, { frame = n, x = x, y = y })
      else
        local opacity = clamp(round_half_away(lerp(p.start, p["end"], k)), 0, 255)
        cel.opacity = opacity
        listed(values, { frame = n, opacity = opacity })
      end
    end
  else
    fail("unknown property '" .. tostring(p.property) .. "'")
  end
  return { layer = path, property = p.property, frames = #frames, values = values }
end

OPS.oscillate_cels = function(ctx, p)
  local spr = need_sprite(ctx)
  local layer, path = cel_layer(spr, p.layer)
  local frames = frames_of(spr, p.frames, 2)
  local cels = existing_cels(layer, path, frames)
  local count, cycles, phase = #frames, p.cycles or 1, p.phase or 0
  local ax, ay = p.amplitude_x or 0, p.amplitude_y or 0

  local function offset(i, amplitude)
    local angle = 2 * math.pi * (cycles * (i - 1) / count + phase)
    return round_half_away(amplitude * math.sin(angle))
  end

  -- The base is placed so the first frame lands where it already is; that keeps a
  -- second run with the same arguments from moving anything.
  local first = cels[1].position
  local base_x, base_y = first.x - offset(1, ax), first.y - offset(1, ay)
  local users = image_users(layer)
  local positions = {}
  for i, n in ipairs(frames) do
    local cel = own_cel(spr, layer, cels[i], users)
    local x, y = cel.position.x, cel.position.y
    if ax ~= 0 then
      x = base_x + offset(i, ax)
    end
    if ay ~= 0 then
      y = base_y + offset(i, ay)
    end
    cel.position = Point(x, y)
    listed(positions, { frame = n, x = x, y = y })
  end
  return { layer = path, frames = count, positions = positions }
end
