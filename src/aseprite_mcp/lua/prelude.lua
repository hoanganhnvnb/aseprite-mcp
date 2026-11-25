-- Helpers shared by every op file. Loaded by main.lua before the ops.

OPS = {}

function fail(msg)
  error({ user = msg }, 2)
end

BLEND_MODES = {
  normal = BlendMode.NORMAL,
  multiply = BlendMode.MULTIPLY,
  screen = BlendMode.SCREEN,
  overlay = BlendMode.OVERLAY,
  darken = BlendMode.DARKEN,
  lighten = BlendMode.LIGHTEN,
  color_dodge = BlendMode.COLOR_DODGE,
  color_burn = BlendMode.COLOR_BURN,
  hard_light = BlendMode.HARD_LIGHT,
  soft_light = BlendMode.SOFT_LIGHT,
  difference = BlendMode.DIFFERENCE,
  exclusion = BlendMode.EXCLUSION,
  hue = BlendMode.HSL_HUE,
  saturation = BlendMode.HSL_SATURATION,
  color = BlendMode.HSL_COLOR,
  luminosity = BlendMode.HSL_LUMINOSITY,
  addition = BlendMode.ADDITION,
  subtract = BlendMode.SUBTRACT,
  divide = BlendMode.DIVIDE,
}

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

function get_layer(spr, name)
  local layer = find_layer(spr, name)
  if layer == nil then
    fail("layer '" .. name .. "' not found")
  end
  return layer
end

function is_inside(spr, layer, group)
  local parent = layer.parent
  while parent ~= spr do
    if parent == group then
      return true
    end
    parent = parent.parent
  end
  return false
end

-- Every layer that can hold cels: all non-group layers, nested ones included.
function cel_layers(spr)
  local out = {}
  for _, layer in ipairs(all_layers(spr)) do
    if not layer.isGroup then
      table.insert(out, layer)
    end
  end
  return out
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

local function is_sequence(t)
  local n = 0
  for _ in pairs(t) do
    n = n + 1
  end
  return n > 0 and n == #t
end

-- nil or "all" means every frame; otherwise one frame number or a non-empty list of
-- them. The result is sorted with duplicates removed.
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
  elseif type(spec) ~= "table" or not is_sequence(spec) then
    local shown = type(spec) == "string" and string.format("%q", spec) or json.encode(spec)
    fail(string.format("invalid frame list %s: use \"all\", a frame number or a list of them",
      shown))
  end
  local seen, out = {}, {}
  for _, n in ipairs(spec) do
    if math.type(n) ~= "integer" then
      fail(string.format("frame %s is not a whole number", tostring(n)))
    end
    if n < 1 or n > count then
      fail(string.format("frame %d is out of range (sprite has %d frames)", n, count))
    end
    if not seen[n] then
      seen[n] = true
      table.insert(out, n)
    end
  end
  table.sort(out)
  return out
end

-- Formats that hold one image; saveCopyAs would write numbered files instead.
local SINGLE_IMAGE = {
  png = true, jpg = true, jpeg = true, bmp = true, tga = true,
  pcx = true, ico = true, webp = true, qoi = true,
}

function check_save_format(spr, target)
  local ext = (target or ""):match("%.([^.\\/]+)$")
  if ext and SINGLE_IMAGE[ext:lower()] and #spr.frames > 1 then
    fail(string.format(
      "a .%s file holds one frame but the sprite has %d; save it as .aseprite or .gif",
      ext, #spr.frames))
  end
end

local pc = app.pixelColor

local function luma(r, g, b)
  -- Rec. 709 weights, the same ones Aseprite uses when converting to grayscale.
  return (r * 2126 + g * 7152 + b * 722 + 5000) // 10000
end

local function nearest_index(spr, r, g, b, skip)
  local pal = spr.palettes[1]
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

-- The transparent index only means "transparent" on transparent layers; a
-- background layer shows it as its opaque palette colour.
local function transparent_index(spr, layer)
  if layer ~= nil and layer.isBackground then
    return nil
  end
  return spr.transparentColor
end

-- `layer` is optional; pass it so background layers are handled right. Background
-- layers cannot be transparent, so alpha is ignored there: RGB and gray store the
-- colour opaque, indexed maps it to its nearest palette entry.
function color_value(spr, rgba, layer)
  local r, g, b = rgba[1], rgba[2], rgba[3]
  local a = rgba[4] or 255
  if layer ~= nil and layer.isBackground then
    a = 255
  end
  local mode = spr.colorMode
  if mode == ColorMode.RGB then
    return pc.rgba(r, g, b, a)
  elseif mode == ColorMode.GRAY then
    return pc.graya(luma(r, g, b), a)
  elseif mode == ColorMode.INDEXED then
    local tindex = transparent_index(spr, layer)
    if tindex == nil then
      return nearest_index(spr, r, g, b, nil)
    end
    if a == 0 then
      return tindex
    end
    return nearest_index(spr, r, g, b, tindex)
  end
  fail("unsupported color mode")
end

function pixel_rgba(spr, value, layer)
  local mode = spr.colorMode
  if mode == ColorMode.RGB then
    return pc.rgbaR(value), pc.rgbaG(value), pc.rgbaB(value), pc.rgbaA(value)
  elseif mode == ColorMode.GRAY then
    local v = pc.grayaV(value)
    return v, v, v, pc.grayaA(value)
  elseif mode == ColorMode.INDEXED then
    local pal = spr.palettes[1]
    if value == transparent_index(spr, layer) or value < 0 or value >= #pal then
      return 0, 0, 0, 0
    end
    local c = pal:getColor(value)
    if layer ~= nil and layer.isBackground then
      return c.red, c.green, c.blue, 255
    end
    return c.red, c.green, c.blue, c.alpha
  end
  fail("unsupported color mode")
end

function is_transparent(spr, value, layer)
  local mode = spr.colorMode
  if mode == ColorMode.RGB then
    return pc.rgbaA(value) == 0
  elseif mode == ColorMode.GRAY then
    return pc.grayaA(value) == 0
  end
  return value == transparent_index(spr, layer)
end

-- Indexed sprites get a dedicated transparent entry at index 0 so the default
-- palette's own colours (black included) all stay usable as opaque colours.
function set_default_palette(spr)
  local base = app.defaultPalette
  if spr.colorMode ~= ColorMode.INDEXED then
    spr:setPalette(base)
    return
  end
  local size = math.min(#base + 1, 256)
  local pal = Palette(size)
  pal:setColor(0, Color { r = 0, g = 0, b = 0, a = 0 })
  for i = 1, size - 1 do
    pal:setColor(i, base:getColor(i - 1))
  end
  spr:setPalette(pal)
  spr.transparentColor = 0
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

function cel_props(cel)
  return { opacity = cel.opacity, z_index = cel.zIndex, color = cel.color, data = cel.data }
end

-- Puts a new cel with `image` at (layer, frame), with the opacity, z-index, colour and
-- user data in `props` (from cel_props) when given. The old cel is deleted rather than
-- overwritten: writing into a linked cel would change every frame it is linked to.
function put_cel(spr, layer, frame, image, position, props)
  local old = layer:cel(frame)
  if old ~= nil then
    spr:deleteCel(old)
  end
  local cel = spr:newCel(layer, frame, image, position)
  if props ~= nil then
    cel.opacity = props.opacity
    cel.zIndex = props.z_index
    cel.color = props.color
    cel.data = props.data
  end
  return cel
end

-- Runs fn with the layer and all its parent groups unlocked, then restores every lock.
function with_unlocked(layer, fn)
  local chain, node = {}, layer
  while node ~= layer.sprite do
    table.insert(chain, { node, node.isEditable })
    node.isEditable = true
    node = node.parent
  end
  local ok, err = pcall(fn)
  for _, entry in ipairs(chain) do
    entry[1].isEditable = entry[2]
  end
  if not ok then
    error(err, 0)
  end
end

function require_editable(layer)
  local path = layer_path(layer)
  if not layer.isEditable then
    fail("'" .. path .. "' is locked; unlock it first")
  end
  local parent = layer.parent
  while parent ~= layer.sprite do
    if not parent.isEditable then
      fail(string.format("'%s' is inside the locked group '%s'; unlock it first",
        path, layer_path(parent)))
    end
    parent = parent.parent
  end
end

-- Linked cels share position and opacity along with the image, so a cel whose image
-- other frames use as well gets replaced by its own copy before it is changed.
function image_users(layer)
  local users = {}
  for _, cel in ipairs(layer.cels) do
    local id = cel.image.id
    users[id] = (users[id] or 0) + 1
  end
  return users
end

function own_cel(spr, layer, cel, users)
  local id = cel.image.id
  if (users[id] or 0) <= 1 then
    return cel
  end
  users[id] = users[id] - 1
  if layer.isBackground then
    -- deleteCel leaves background cels in place, so put_cel cannot replace them.
    -- Running UnlinkCel on a locked layer crashes Aseprite, hence the unlock.
    local frame = cel.frameNumber
    app.sprite = spr
    app.range.layers = { layer }
    app.range.frames = { cel.frame }
    local ok, err = pcall(with_unlocked, layer, app.command.UnlinkCel)
    app.range:clear()
    if not ok then
      error(err, 0)
    end
    cel = layer:cel(frame)
    if cel.image.id == id then
      fail(string.format("could not unlink the cel of '%s' in frame %d", layer.name, frame))
    end
    return cel
  end
  return put_cel(spr, layer, cel.frameNumber, cel.image:clone(), cel.position, cel_props(cel))
end

-- The cels of `layer` in `frames`, each image once, plus the number of frames without
-- a cel. A cel linked only to frames in the list is returned once, so changing it
-- changes all of them; one also linked to frames outside the list gets its own copy
-- per listed frame, so the other frames keep their pixels.
function cels_to_change(spr, layer, frames)
  local users = image_users(layer)
  local asked, missing = {}, 0
  for _, n in ipairs(frames) do
    local cel = layer:cel(n)
    if cel == nil then
      missing = missing + 1
    else
      local id = cel.image.id
      asked[id] = (asked[id] or 0) + 1
    end
  end
  local shared = {}
  for id, count in pairs(asked) do
    shared[id] = count == users[id]
  end
  local out, seen = {}, {}
  for _, n in ipairs(frames) do
    local cel = layer:cel(n)
    if cel ~= nil then
      local id = cel.image.id
      if not shared[id] then
        table.insert(out, own_cel(spr, layer, cel, users))
      elseif not seen[id] then
        seen[id] = true
        table.insert(out, cel)
      end
    end
  end
  return out, missing
end

-- The part of rect {x, y, w, h} that lies on the canvas; fails when nothing does.
function canvas_rect(spr, r)
  local area = Rectangle(r.x, r.y, r.w, r.h):intersect(spr.bounds)
  if area.isEmpty then
    fail(string.format("rect (%d, %d, %d x %d) is outside the canvas (%d x %d)",
      r.x, r.y, r.w, r.h, spr.width, spr.height))
  end
  return area
end

-- Native commands such as filters only work on the active cel, inside the selection,
-- and silently do nothing on hidden layers. This makes (layer, frame) active, selects
-- `region` (a Rectangle, or nil for the whole cel), shows the layer and its groups,
-- runs fn(cel), then clears the selection and puts visibility and the active layer
-- and frame back as they were.
function with_target(spr, layer, frame, region, fn)
  local cel = layer:cel(frame)
  if cel == nil then
    fail(string.format("'%s' has no cel in frame %d", layer_path(layer), frame))
  end
  local hidden, node = {}, layer
  while node ~= spr do
    if not node.isVisible then
      table.insert(hidden, node)
      node.isVisible = true
    end
    node = node.parent
  end
  local old_sprite = app.sprite
  local old_layer, old_frame
  if old_sprite == spr then
    old_layer, old_frame = app.layer, app.frame
  end
  app.sprite = spr
  app.layer = layer
  app.frame = spr.frames[frame]
  app.range:clear()
  if region ~= nil then
    spr.selection:select(region)
  else
    spr.selection:deselect()
  end
  local ok, err = pcall(fn, cel)
  spr.selection:deselect()
  for _, l in ipairs(hidden) do
    l.isVisible = false
  end
  if old_layer ~= nil then
    pcall(function()
      app.layer = old_layer
      app.frame = old_frame
    end)
  end
  if old_sprite ~= nil and old_sprite ~= spr then
    app.sprite = old_sprite
  end
  if not ok then
    error(err, 0)
  end
end

-- A layer that holds plain pixels: groups and tilemaps are refused.
function image_layer(spr, name)
  local layer = get_layer(spr, name)
  local path = layer_path(layer)
  if layer.isGroup then
    fail("'" .. path .. "' is a group; name one of its layers")
  end
  if layer.isTilemap then
    fail("'" .. path .. "' is a tilemap layer; only image layers can be changed this way")
  end
  return layer, path
end

-- Makes the cel at `to` an independent copy of the one at `from`, or removes it when
-- `from` has no cel.
function copy_cel(spr, layer, from, to)
  local src = layer:cel(from)
  if src == nil then
    local old = layer:cel(to)
    if old ~= nil then
      spr:deleteCel(old)
      return "cleared"
    end
    return nil
  end
  put_cel(spr, layer, to, src.image:clone(), src.position, cel_props(src))
  return "copied"
end

function round_half_away(v)
  if v >= 0 then
    return math.floor(v + 0.5)
  end
  return -math.floor(-v + 0.5)
end

-- Easing curves map t in [0, 1] to progress; all start at 0 and end at 1.
local BACK = 1.70158

local function bounce_out(t)
  local n, d = 7.5625, 2.75
  if t < 1 / d then
    return n * t * t
  elseif t < 2 / d then
    t = t - 1.5 / d
    return n * t * t + 0.75
  elseif t < 2.5 / d then
    t = t - 2.25 / d
    return n * t * t + 0.9375
  end
  t = t - 2.625 / d
  return n * t * t + 0.984375
end

EASINGS = {
  linear = function(t)
    return t
  end,
  ease_in = function(t)
    return t * t
  end,
  ease_out = function(t)
    return 1 - (1 - t) * (1 - t)
  end,
  ease_in_out = function(t)
    if t < 0.5 then
      return 2 * t * t
    end
    return 1 - 2 * (1 - t) * (1 - t)
  end,
  ease_out_back = function(t)
    local u = t - 1
    return 1 + (BACK + 1) * u * u * u + BACK * u * u
  end,
  bounce = bounce_out,
}

-- Ordered dither matrices, built recursively: each doubling puts 4m, 4m+2, 4m+3 and
-- 4m+1 in the four quadrants. bayer(n)[y + 1][x + 1] holds 0..n*n-1, each once.
local bayer_cache = { [1] = { { 0 } } }

function bayer(n)
  local m = bayer_cache[n]
  if m ~= nil then
    return m
  end
  if math.type(n) ~= "integer" or n < 2 or n & (n - 1) ~= 0 then
    fail("dither matrix size must be a power of two, got " .. tostring(n))
  end
  local half, h = bayer(n // 2), n // 2
  m = {}
  for y = 1, n do
    m[y] = {}
  end
  for y = 1, h do
    for x = 1, h do
      local v = 4 * half[y][x]
      m[y][x], m[y][x + h] = v, v + 2
      m[y + h][x], m[y + h][x + h] = v + 3, v + 1
    end
  end
  bayer_cache[n] = m
  return m
end

-- Threshold in (0, 1) at canvas pixel (x, y); the matrix repeats over the canvas.
function bayer_threshold(n, x, y)
  return (bayer(n)[y % n + 1][x % n + 1] + 0.5) / (n * n)
end
