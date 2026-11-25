-- Palette and colour ops. Pixel rewrites (replace, quantize) are worked out on a copy
-- of the touched area, with one lookup per distinct pixel value, and drawn back in one
-- undoable call. Adjustments, outline and convolution run Aseprite's own filters.

local pc = app.pixelColor

-- Filter channel bits, as the filter commands take them.
local RGB, ALPHA, GRAY, INDEX = 1 | 2 | 4, 8, 16, 32

local function hex(c)
  if c.alpha == 255 then
    return string.format("#%02x%02x%02x", c.red, c.green, c.blue)
  end
  return string.format("#%02x%02x%02x%02x", c.red, c.green, c.blue, c.alpha)
end

local function region_area(spr, region)
  if region == nil then
    return nil
  end
  return canvas_rect(spr, region)
end

OPS.get_palette = function(ctx)
  local spr = need_sprite(ctx)
  local pal = spr.palettes[1]
  local colors = {}
  for i = 0, #pal - 1 do
    colors[i + 1] = hex(pal:getColor(i))
  end
  local out = { colors = colors, size = #pal }
  if spr.colorMode == ColorMode.INDEXED then
    out.transparent_index = spr.transparentColor + 1
  end
  return out
end

-- Highest palette index stored anywhere in an indexed sprite: cel images of image
-- layers and the tiles of every tileset.
local function highest_index(spr)
  local top, seen = -1, {}
  local function scan(img)
    if seen[img.id] then
      return
    end
    seen[img.id] = true
    for px in img:pixels() do
      local v = px()
      if v > top then
        top = v
      end
    end
  end
  for _, layer in ipairs(cel_layers(spr)) do
    if not layer.isTilemap then
      for _, cel in ipairs(layer.cels) do
        scan(cel.image)
      end
    end
  end
  for _, tileset in ipairs(spr.tilesets) do
    for i = 0, #tileset - 1 do
      local tile = tileset:tile(i)
      if tile ~= nil then
        scan(tile.image)
      end
    end
  end
  return top
end

OPS.set_palette = function(ctx, p)
  local spr = need_sprite(ctx)
  local colors = p.colors or {}
  local n = #colors
  if n < 1 or n > 256 then
    fail(string.format("a palette holds 1 to 256 colours, got %d", n))
  end
  if spr.colorMode == ColorMode.INDEXED then
    local top = math.max(highest_index(spr), spr.transparentColor)
    if top >= n then
      fail(string.format("the sprite uses palette index %d, so the new palette needs at "
        .. "least %d colours (pixels keep their indices)", top + 1, top + 1))
    end
  end
  local pal = Palette(n)
  for i, c in ipairs(colors) do
    pal:setColor(i - 1, Color { r = c[1], g = c[2], b = c[3], a = c[4] })
  end
  spr:setPalette(pal)
  return { size = n }
end

-- Fully transparent pixels compare equal whatever their colour channels hold.
local function visible_rgba(r, g, b, a)
  if a == 0 then
    return 0, 0, 0, 0
  end
  return r, g, b, a
end

-- Returns fn(value) -> new value, or false when no mapping matches. All mappings look
-- at the pixel as it was, so A->B together with B->A swaps the two colours.
local function replacer(spr, layer, mappings, tolerance)
  local rules = {}
  for i, m in ipairs(mappings) do
    local r, g, b, a = visible_rgba(m.from[1], m.from[2], m.from[3], m.from[4])
    rules[i] = { r, g, b, a, color_value(spr, m.to, layer) }
  end
  local memo = {}
  return function(value)
    local out = memo[value]
    if out ~= nil then
      return out
    end
    out = false
    local r, g, b, a = visible_rgba(pixel_rgba(spr, value, layer))
    for _, rule in ipairs(rules) do
      if math.abs(r - rule[1]) <= tolerance and math.abs(g - rule[2]) <= tolerance
          and math.abs(b - rule[3]) <= tolerance and math.abs(a - rule[4]) <= tolerance then
        out = rule[5]
        break
      end
    end
    memo[value] = out
    return out
  end
end

-- Runs lookup over the cel inside area (canvas coordinates; nil for the whole cel) and
-- writes the pixels it maps back into the cel. Returns how many pixels matched.
local function remap_cel(spr, cel, area, lookup)
  local box = cel.bounds
  if area ~= nil then
    box = box:intersect(area)
  end
  if box.isEmpty then
    return 0
  end
  local pos = cel.position
  local patch = new_image(spr, box.width, box.height)
  patch:drawImage(cel.image, Point(pos.x - box.x, pos.y - box.y), 255, BlendMode.SRC)
  local count = 0
  for px in patch:pixels() do
    local new = lookup(px())
    if new then
      px(new)
      count = count + 1
    end
  end
  if count > 0 then
    cel.image:drawImage(patch, Point(box.x - pos.x, box.y - pos.y), 255, BlendMode.SRC)
  end
  return count
end

OPS.replace_colors = function(ctx, p)
  local spr = need_sprite(ctx)
  local layer, path = image_layer(spr, p.layer)
  require_editable(layer)
  local tolerance = p.tolerance or 0
  if math.type(tolerance) ~= "integer" or tolerance < 0 or tolerance > 255 then
    fail("tolerance must be a whole number from 0 to 255")
  end
  if #(p.mappings or {}) == 0 then
    fail("give at least one mapping")
  end
  local area = region_area(spr, p.region)
  local frames = frame_list(spr, p.frames)
  local lookup = replacer(spr, layer, p.mappings, tolerance)
  local cels, skipped = cels_to_change(spr, layer, frames)
  local replaced = 0
  for _, cel in ipairs(cels) do
    replaced = replaced + remap_cel(spr, cel, area, lookup)
  end
  return { layer = path, cels = #cels, replaced = replaced, skipped_frames = skipped }
end

OPS.quantize_to_palette = function(ctx, p)
  local spr = need_sprite(ctx)
  local layer, path = image_layer(spr, p.layer)
  require_editable(layer)
  if spr.colorMode == ColorMode.INDEXED then
    fail("the sprite is indexed, so its pixels are palette entries already")
  end
  local pal = spr.palettes[1]
  local entries = {}
  for i = 0, #pal - 1 do
    local c = pal:getColor(i)
    if c.alpha > 0 then
      table.insert(entries, { c.red, c.green, c.blue })
    end
  end
  if #entries == 0 then
    fail("the palette has no visible colours to snap to")
  end
  local frames = frame_list(spr, p.frames)
  local memo = {}
  local function lookup(value)
    local out = memo[value]
    if out ~= nil then
      return out
    end
    out = false
    local r, g, b, a = pixel_rgba(spr, value, layer)
    if a > 0 then
      local best, best_dist = nil, math.huge
      for _, e in ipairs(entries) do
        local dr, dg, db = e[1] - r, e[2] - g, e[3] - b
        local dist = dr * dr + dg * dg + db * db
        if dist < best_dist then
          best, best_dist = e, dist
        end
      end
      local new = color_value(spr, { best[1], best[2], best[3], a }, layer)
      if new ~= value then
        out = new
      end
    end
    memo[value] = out
    return out
  end
  local cels, skipped = cels_to_change(spr, layer, frames)
  local changed = 0
  for _, cel in ipairs(cels) do
    changed = changed + remap_cel(spr, cel, nil, lookup)
  end
  return { layer = path, cels = #cels, changed = changed, skipped_frames = skipped }
end

OPS.extract_palette = function(ctx, p)
  local spr = need_sprite(ctx)
  local max = p.max_colors
  if math.type(max) ~= "integer" or max < 2 or max > 256 then
    fail("max_colors must be a whole number from 2 to 256")
  end
  -- The command replaces the palette, so it runs on a throwaway copy of the sprite.
  -- It always puts a transparent entry first, which is not one of the sprite's colours.
  local copy = Sprite(spr)
  local ok, res = pcall(function()
    app.sprite = copy
    if copy.colorMode ~= ColorMode.RGB then
      app.command.ChangePixelFormat { ui = false, format = "rgb" }
    end
    app.command.ColorQuantization {
      ui = false,
      maxColors = math.min(max + 1, 256),
      withAlpha = p.with_alpha == true,
    }
    local pal = copy.palettes[1]
    local colors = {}
    for i = 0, #pal - 1 do
      local c = pal:getColor(i)
      if not (i == 0 and c.alpha == 0) and #colors < max then
        table.insert(colors, hex(c))
      end
    end
    return colors
  end)
  copy:close()
  app.sprite = spr
  if not ok then
    error(res, 0)
  end
  return { colors = res }
end

-- Image layer, editable, with a cel in every requested frame; returns its unique cels'
-- frame numbers (linked cels once, or owned when only some of their frames are asked).
local function native_targets(spr, p)
  local layer, path = image_layer(spr, p.layer)
  require_editable(layer)
  local frames = frame_list(spr, p.frames)
  for _, n in ipairs(frames) do
    if layer:cel(n) == nil then
      fail(string.format("'%s' has no cel in frame %d", path, n))
    end
  end
  local targets = {}
  for _, cel in ipairs((cels_to_change(spr, layer, frames))) do
    table.insert(targets, cel.frameNumber)
  end
  return layer, path, targets
end

local function in_range(name, v, lo, hi)
  if math.type(v) ~= "integer" or v < lo or v > hi then
    fail(string.format("%s must be a whole number from %d to %d", name, lo, hi))
  end
  return v
end

OPS.adjust_colors = function(ctx, p)
  local spr = need_sprite(ctx)
  local hue = in_range("hue", p.hue or 0, -180, 180)
  local saturation = in_range("saturation", p.saturation or 0, -100, 100)
  local lightness = in_range("lightness", p.lightness or 0, -100, 100)
  local brightness = in_range("brightness", p.brightness or 0, -100, 100)
  local contrast = in_range("contrast", p.contrast or 0, -100, 100)
  local hsl = hue ~= 0 or saturation ~= 0 or lightness ~= 0
  local bc = brightness ~= 0 or contrast ~= 0
  if not (hsl or bc or p.invert) then
    fail("nothing to change: set hue, saturation, lightness, brightness, contrast or invert")
  end
  -- On indexed sprites these two commands rewrite the shared palette instead of the cel.
  if spr.colorMode == ColorMode.INDEXED and (hsl or bc) then
    fail("hue, saturation, lightness, brightness and contrast would change the palette of "
      .. "an indexed sprite, not this layer; edit the palette or convert to rgb first "
      .. "(invert works)")
  end
  local layer, path, targets = native_targets(spr, p)
  local area = region_area(spr, p.region)
  -- Colour channels only: alpha is never touched.
  local channels = RGB | GRAY
  for _, frame in ipairs(targets) do
    with_target(spr, layer, frame, area, function()
      if hsl then
        app.command.HueSaturation {
          ui = false, mode = "hsl", channels = channels,
          hue = hue, saturation = saturation, lightness = lightness, alpha = 0,
        }
      end
      if bc then
        app.command.BrightnessContrast {
          ui = false, channels = channels, brightness = brightness, contrast = contrast,
        }
      end
      if p.invert then
        app.command.InvertColor { ui = false, channels = channels }
      end
    end)
  end
  return { layer = path, cels = #targets }
end

local OUTLINE_PLACES = { outside = true, inside = true }
local OUTLINE_MATRICES = { circle = true, square = true, horizontal = true, vertical = true }

-- The command matches colours per channel, so indexed sprites need the index channel
-- and palette indices; RGB and gray need the alpha channel to see transparency.
local function outline_colors(spr, rgba, layer)
  local mode = spr.colorMode
  local value = color_value(spr, rgba, layer)
  if mode == ColorMode.INDEXED then
    return Color { index = value }, Color { index = spr.transparentColor }, INDEX
  elseif mode == ColorMode.GRAY then
    return Color { gray = pc.grayaV(value), alpha = pc.grayaA(value) },
      Color { gray = 0, alpha = 0 }, GRAY | ALPHA
  end
  return Color { r = pc.rgbaR(value), g = pc.rgbaG(value), b = pc.rgbaB(value),
    a = pc.rgbaA(value) }, Color { r = 0, g = 0, b = 0, a = 0 }, RGB | ALPHA
end

OPS.outline = function(ctx, p)
  local spr = need_sprite(ctx)
  if not OUTLINE_PLACES[p.place] then
    fail("place must be 'outside' or 'inside', got " .. tostring(p.place))
  end
  if not OUTLINE_MATRICES[p.matrix] then
    fail("matrix must be circle, square, horizontal or vertical, got " .. tostring(p.matrix))
  end
  local layer, path = image_layer(spr, p.layer)
  if layer.isBackground then
    fail(string.format("'%s' is the background layer: it has no transparent pixels to "
      .. "outline against", path))
  end
  local _, _, targets = native_targets(spr, p)
  local area = region_area(spr, p.region)
  local color, bg, channels = outline_colors(spr, p.color, layer)
  for _, frame in ipairs(targets) do
    with_target(spr, layer, frame, area, function()
      app.command.Outline {
        ui = false, color = color, bgColor = bg, place = p.place, matrix = p.matrix,
        channels = channels,
      }
    end)
  end
  return { layer = path, cels = #targets }
end

OPS.apply_convolution = function(ctx, p)
  local spr = need_sprite(ctx)
  if type(p.matrix) ~= "string" or p.matrix == "" then
    fail("give a convolution matrix name")
  end
  local layer, path, targets = native_targets(spr, p)
  local area = region_area(spr, p.region)
  -- Indexed pixels go through their palette colours; a background stays opaque.
  local channels = RGB | GRAY | ALPHA
  if spr.colorMode == ColorMode.INDEXED then
    channels = RGB
  elseif layer.isBackground then
    channels = RGB | GRAY
  end
  for _, frame in ipairs(targets) do
    with_target(spr, layer, frame, area, function()
      app.command.ConvolutionMatrix { ui = false, fromResource = p.matrix, channels = channels }
    end)
  end
  return { layer = path, cels = #targets }
end
