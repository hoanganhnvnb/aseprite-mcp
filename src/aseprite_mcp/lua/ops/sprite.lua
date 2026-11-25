local MODE_NAMES = {
  [ColorMode.RGB] = "rgb",
  [ColorMode.GRAY] = "grayscale",
  [ColorMode.INDEXED] = "indexed",
}

local BLEND_NAMES = {}
for name, mode in pairs(BLEND_MODES) do
  BLEND_NAMES[mode] = name
end

local DIRECTION_NAMES = {
  [AniDir.FORWARD] = "forward",
  [AniDir.REVERSE] = "reverse",
  [AniDir.PING_PONG] = "pingpong",
  [AniDir.PING_PONG_REVERSE] = "pingpong_reverse",
}

local function layer_type(layer)
  if layer.isGroup then
    return "group"
  elseif layer.isTilemap then
    return "tilemap"
  end
  return "normal"
end

local function layer_tree(layers, prefix)
  local out = {}
  for _, layer in ipairs(layers) do
    local path = prefix and (prefix .. "/" .. layer.name) or layer.name
    table.insert(out, {
      name = layer.name,
      path = path,
      type = layer_type(layer),
      visible = layer.isVisible,
      is_background = layer.isBackground,
      opacity = layer.opacity,
      blend_mode = BLEND_NAMES[layer.blendMode] or "normal",
      children = layer.isGroup and layer_tree(layer.layers, path) or {},
    })
  end
  return out
end

OPS.sprite_info = function(ctx)
  local spr = need_sprite(ctx)
  local frames = {}
  for i, frame in ipairs(spr.frames) do
    frames[i] = { index = i, duration_ms = math.floor(frame.duration * 1000 + 0.5) }
  end
  local tags = {}
  for i, tag in ipairs(spr.tags) do
    tags[i] = {
      name = tag.name,
      from_frame = tag.fromFrame.frameNumber,
      to_frame = tag.toFrame.frameNumber,
      direction = DIRECTION_NAMES[tag.aniDir] or "forward",
      repeats = tag.repeats,
    }
  end
  return {
    width = spr.width,
    height = spr.height,
    color_mode = MODE_NAMES[spr.colorMode] or "unknown",
    frames = frames,
    layers = layer_tree(spr.layers, nil),
    tags = tags,
    slice_count = #spr.slices,
    palette_size = #spr.palettes[1],
  }
end

local FORMAT_NAMES = { rgb = "rgb", grayscale = "gray", indexed = "indexed" }

local function color_distance(a, b)
  local dr, dg, db = a.red - b.red, a.green - b.green, a.blue - b.blue
  return dr * dr + dg * dg + db * db
end

local function nearest_entry(colors, r, g, b)
  local best, best_dist = 1, math.huge
  for i, c in ipairs(colors) do
    local dr, dg, db = c.red - r, c.green - g, c.blue - b
    local dist = dr * dr + dg * dg + db * db
    if dist < best_dist then
      best, best_dist = i, dist
      if dist == 0 then
        break
      end
    end
  end
  return best
end

-- How many opaque pixels (all layers and frames) map to each entry of `colors`.
local function entry_usage(spr, colors)
  local usage, cache = {}, {}
  for i = 1, #colors do
    usage[i] = 0
  end
  for _, cel in ipairs(spr.cels) do
    for px in cel.image:pixels() do
      local value = px()
      local entry = cache[value]
      if entry == nil then
        local r, g, b, a = pixel_rgba(spr, value, cel.layer)
        entry = a > 0 and nearest_entry(colors, r, g, b) or false
        cache[value] = entry
      end
      if entry then
        usage[entry] = usage[entry] + 1
      end
    end
  end
  return usage
end

-- Least used entry; ties go to the one closest to another entry, so the colour it
-- stood for is still well covered.
local function entry_to_drop(colors, usage)
  local best, best_use, best_dist = nil, math.huge, math.huge
  for i, c in ipairs(colors) do
    if usage[i] <= best_use then
      local nearest = math.huge
      for j, other in ipairs(colors) do
        if j ~= i then
          nearest = math.min(nearest, color_distance(c, other))
        end
      end
      if usage[i] < best_use or nearest < best_dist then
        best, best_use, best_dist = i, usage[i], nearest
      end
    end
  end
  return best
end

-- Converting to indexed maps transparent pixels to the transparent index, and opaque
-- pixels can no longer use that entry. When it holds an opaque colour, give
-- transparency its own entry at 0 first (as new indexed sprites have), dropping the
-- least used colour if the palette is full. Returns the dropped colours.
local function reserve_transparent_entry(spr)
  local pal = spr.palettes[1]
  if spr.transparentColor ~= 0 or #pal == 0 or pal:getColor(0).alpha == 0 then
    return {}
  end
  local colors = {}
  for i = 0, #pal - 1 do
    colors[#colors + 1] = pal:getColor(i)
  end
  local dropped = {}
  if #colors >= 256 then
    local index = entry_to_drop(colors, entry_usage(spr, colors))
    local c = table.remove(colors, index)
    dropped[1] = string.format("#%02x%02x%02x%02x", c.red, c.green, c.blue, c.alpha)
  end
  local shifted = Palette(#colors + 1)
  shifted:setColor(0, Color { r = 0, g = 0, b = 0, a = 0 })
  for i, c in ipairs(colors) do
    shifted:setColor(i, c)
  end
  spr:setPalette(shifted)
  return dropped
end

OPS.set_color_mode = function(ctx, p)
  local spr = need_sprite(ctx)
  local format = FORMAT_NAMES[p.mode]
  if format == nil then
    fail("unknown color mode '" .. tostring(p.mode) .. "' (use rgb, grayscale or indexed)")
  end
  if MODE_NAMES[spr.colorMode] == p.mode then
    return { color_mode = p.mode, changed = false, dropped_palette_entries = {} }
  end
  local dropped = {}
  if p.mode == "indexed" then
    dropped = reserve_transparent_entry(spr)
  end
  app.sprite = spr
  app.command.ChangePixelFormat { ui = false, format = format }
  return { color_mode = MODE_NAMES[spr.colorMode], changed = true, dropped_palette_entries = dropped }
end

OPS.resize_sprite = function(ctx, p)
  local spr = need_sprite(ctx)
  spr:resize(p.width, p.height)
  return { width = spr.width, height = spr.height }
end

OPS.crop_sprite = function(ctx, p)
  local spr = need_sprite(ctx)
  local r = p.rect
  local rect = Rectangle(r.x, r.y, r.w, r.h)
  if not rect:intersects(spr.bounds) then
    fail(string.format("crop rectangle (%d, %d, %d x %d) does not overlap the %d x %d canvas",
      r.x, r.y, r.w, r.h, spr.width, spr.height))
  end
  spr:crop(rect)
  return { width = spr.width, height = spr.height }
end

-- p.output is a temporary name next to the real target; the server moves it into
-- place once the whole run has succeeded.
OPS.save_copy = function(ctx, p)
  local spr = need_sprite(ctx)
  check_save_format(spr, p.output)
  spr:saveCopyAs(p.output)
  -- saveCopyAs reports success even when no file was written.
  if not app.fs.isFile(p.output) then
    fail(string.format("Aseprite could not write a .%s file from this %s sprite",
      app.fs.fileExtension(p.output), MODE_NAMES[spr.colorMode]))
  end
end

-- Version probe for the doctor command; "fail" and "crash" exercise both error
-- paths and "echo" comes back as decoded, to check parameter passing.
OPS._ping = function(_, p)
  if p.fail then
    fail(p.fail)
  end
  if p.crash then
    local missing = nil
    return missing.field
  end
  return { api = app.apiVersion, version = tostring(app.version), echo = p.echo }
end
