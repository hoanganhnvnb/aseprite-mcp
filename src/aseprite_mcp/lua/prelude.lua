-- Helpers shared by every op file. Loaded by main.lua before the ops.

OPS = {}

function fail(msg)
  error({ user = msg }, 2)
end

function need_sprite(ctx)
  if ctx.spr == nil then
    fail("no sprite is open")
  end
  return ctx.spr
end

function all_layers(spr)
  local out = {}
  local function walk(layers)
    for _, layer in ipairs(layers) do
      table.insert(out, layer)
      if layer.isGroup then
        walk(layer.layers)
      end
    end
  end
  walk(spr.layers)
  return out
end

local function match_path(layers, path)
  for _, layer in ipairs(layers) do
    if layer.name == path then
      return layer
    end
    local prefix = layer.name .. "/"
    if layer.isGroup and path:sub(1, #prefix) == prefix then
      local found = match_path(layer.layers, path:sub(#prefix + 1))
      if found then
        return found
      end
    end
  end
  return nil
end

-- Exact name first, breadth-first so the shallowest match wins; then "group/child".
-- Plain string comparisons only: layer names may contain pattern characters.
function find_layer(spr, name)
  if name == nil or name == "" then
    for _, layer in ipairs(all_layers(spr)) do
      if not layer.isGroup then
        return layer
      end
    end
    return nil
  end
  local queue = {}
  for _, layer in ipairs(spr.layers) do
    table.insert(queue, layer)
  end
  local i = 1
  while i <= #queue do
    local layer = queue[i]
    if layer.name == name then
      return layer
    end
    if layer.isGroup then
      for _, child in ipairs(layer.layers) do
        table.insert(queue, child)
      end
    end
    i = i + 1
  end
  return match_path(spr.layers, name)
end

function layer_path(layer)
  local parts = { layer.name }
  local root = layer.sprite
  local parent = layer.parent
  while parent ~= root do
    table.insert(parts, 1, parent.name)
    parent = parent.parent
  end
  return table.concat(parts, "/")
end

-- nil means every frame; otherwise a list of 1-based frame numbers.
function frame_list(spr, spec)
  local count = #spr.frames
  if spec == nil or spec == "all" then
    local out = {}
    for i = 1, count do
      out[i] = i
    end
    return out
  end
  if type(spec) == "number" then
    spec = { spec }
  end
  local out = {}
  for _, n in ipairs(spec) do
    if math.type(n) ~= "integer" or n < 1 or n > count then
      fail(string.format("frame %s is out of range (sprite has %d frames)", tostring(n), count))
    end
    table.insert(out, n)
  end
  return out
end

local pc = app.pixelColor

local function luma(r, g, b)
  -- Rec. 709 weights, the same ones Aseprite uses when converting to grayscale.
  return (r * 2126 + g * 7152 + b * 722 + 5000) // 10000
end

local function nearest_index(spr, r, g, b)
  local pal = spr.palettes[1]
  local skip = spr.transparentColor
  local best, best_dist = nil, math.huge
  for i = 0, #pal - 1 do
    if i ~= skip then
      local c = pal:getColor(i)
      local dr, dg, db = c.red - r, c.green - g, c.blue - b
      local dist = dr * dr + dg * dg + db * db
      if dist < best_dist then
        best, best_dist = i, dist
        if dist == 0 then
          break
        end
      end
    end
  end
  return best or skip
end

function color_value(spr, rgba)
  local r, g, b = rgba[1], rgba[2], rgba[3]
  local a = rgba[4] or 255
  local mode = spr.colorMode
  if mode == ColorMode.RGB then
    return pc.rgba(r, g, b, a)
  elseif mode == ColorMode.GRAY then
    return pc.graya(luma(r, g, b), a)
  elseif mode == ColorMode.INDEXED then
    if a == 0 then
      return spr.transparentColor
    end
    return nearest_index(spr, r, g, b)
  end
  fail("unsupported color mode")
end

function pixel_rgba(spr, value)
  local mode = spr.colorMode
  if mode == ColorMode.RGB then
    return pc.rgbaR(value), pc.rgbaG(value), pc.rgbaB(value), pc.rgbaA(value)
  elseif mode == ColorMode.GRAY then
    local v = pc.grayaV(value)
    return v, v, v, pc.grayaA(value)
  elseif mode == ColorMode.INDEXED then
    local pal = spr.palettes[1]
    if value == spr.transparentColor or value < 0 or value >= #pal then
      return 0, 0, 0, 0
    end
    local c = pal:getColor(value)
    return c.red, c.green, c.blue, c.alpha
  end
  fail("unsupported color mode")
end

function is_transparent(spr, value)
  local mode = spr.colorMode
  if mode == ColorMode.RGB then
    return pc.rgbaA(value) == 0
  elseif mode == ColorMode.GRAY then
    return pc.grayaA(value) == 0
  end
  return value == spr.transparentColor
end

function clear_value(spr)
  if spr.colorMode == ColorMode.INDEXED then
    return spr.transparentColor
  end
  return 0
end

function new_image(spr, w, h)
  local img = Image(ImageSpec {
    width = w,
    height = h,
    colorMode = spr.colorMode,
    transparentColor = spr.transparentColor,
  })
  img:clear(clear_value(spr))
  return img
end

local function as_rect(rect)
  if rect.width then
    return rect
  end
  return Rectangle(rect.x, rect.y, rect.w, rect.h)
end

-- Returns the cel at (layer, frame) grown to cover rect. Pixels outside the canvas
-- are kept: the old image is copied whole instead of going through a canvas-sized crop.
function ensure_cel_bounds(spr, layer, frame, rect)
  if layer.isGroup or layer.isTilemap then
    fail("layer '" .. layer.name .. "' cannot hold pixels")
  end
  rect = as_rect(rect)
  local cel = layer:cel(frame)
  if layer.isBackground then
    if cel == nil then
      cel = spr:newCel(layer, frame, new_image(spr, spr.width, spr.height), Point(0, 0))
    end
    return cel
  end
  if cel == nil then
    return spr:newCel(layer, frame, new_image(spr, rect.width, rect.height), Point(rect.x, rect.y))
  end
  local old = cel.bounds
  local want = old:union(rect)
  if want == old then
    return cel
  end
  local img = new_image(spr, want.width, want.height)
  img:drawImage(cel.image, Point(old.x - want.x, old.y - want.y), 255, BlendMode.SRC)
  cel.image = img
  cel.position = Point(want.x, want.y)
  return cel
end
