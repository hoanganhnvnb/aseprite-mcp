-- Test helper: sets and reads pixels in one frame of the open sprite (frame 1 unless
-- params.frame says otherwise), on the first layer or on the layer named by params.layer.
-- params: set = {{x, y, r, g, b, a}, ...}, get = {{x, y}, ...}, layer = name or nil,
-- palette = {{r, g, b, a}, ...} to replace the palette before anything else,
-- background = true to turn the layer into the background layer first.
-- The result holds RGBA in `pixels`, the stored pixel values (e.g. indices) in `values`
-- and the whole canvas as rows of '#' (painted) and '.' (transparent) in `grid`.

local fh = assert(io.open(app.params.params, "rb"))
local P = json.decode(fh:read("a"))
fh:close()
dofile(P.lua_dir .. "/prelude.lua")

local spr = open_sprite(P.open_file)
local layer = spr.layers[1]
if P.layer then
  layer = find_layer(spr, P.layer)
  assert(layer, "no layer " .. P.layer)
end

local function int(v)
  return math.floor(v)
end

local frame = P.frame and int(P.frame) or 1

local palette = P.palette or {}
if #palette > 0 then
  local pal = Palette(#palette)
  for i = 1, #palette do
    local c = palette[i]
    pal:setColor(i - 1, Color { r = int(c[1]), g = int(c[2]), b = int(c[3]), a = int(c[4]) })
  end
  spr:setPalette(pal)
end

if P.background then
  app.sprite = spr
  app.layer = layer
  app.command.BackgroundFromLayer()
  layer = find_layer(spr, "Background")
end

local set = P.set or {}
for i = 1, #set do
  local s = set[i]
  local x, y = int(s[1]), int(s[2])
  local cel = ensure_cel_bounds(spr, layer, frame, { x = x, y = y, w = 1, h = 1 })
  local value = color_value(spr, { int(s[3]), int(s[4]), int(s[5]), int(s[6]) }, layer)
  cel.image:drawPixel(x - cel.position.x, y - cel.position.y, value)
end

local pixels, values = {}, {}
local get = P.get or {}
for i = 1, #get do
  local x, y = int(get[i][1]), int(get[i][2])
  local cel = layer:cel(frame)
  local rgba = { 0, 0, 0, 0 }
  values[i] = -1
  if cel and cel.bounds:contains(Rectangle(x, y, 1, 1)) then
    local value = cel.image:getPixel(x - cel.position.x, y - cel.position.y)
    rgba = { pixel_rgba(spr, value, layer) }
    values[i] = value
  end
  pixels[i] = rgba
end

local grid = {}
local cel = layer:cel(frame)
for y = 0, spr.height - 1 do
  local row = {}
  for x = 0, spr.width - 1 do
    local mark = "."
    if cel and cel.bounds:contains(Rectangle(x, y, 1, 1)) then
      local value = cel.image:getPixel(x - cel.position.x, y - cel.position.y)
      if not is_transparent(spr, value, layer) then
        mark = "#"
      end
    end
    row[#row + 1] = mark
  end
  grid[#grid + 1] = table.concat(row)
end

local saved = false
if (#set > 0 or #palette > 0 or P.background) and P.save_tmp then
  spr:saveCopyAs(P.save_tmp)
  saved = true
end

local out = assert(io.open(P.result_path, "wb"))
out:write(json.encode({ ok = true, saved = saved, pixels = pixels, values = values, grid = grid }))
out:close()
