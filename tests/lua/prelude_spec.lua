-- Checks for the prelude helpers. Run through the runner by test_runtime.py.

local fh = assert(io.open(app.params.params, "rb"))
local P = json.decode(fh:read("a"))
fh:close()

local failures = {}
local checks = 0

local function check(name, cond)
  checks = checks + 1
  if not cond then
    table.insert(failures, name)
  end
end

local function write_result(data)
  local out = assert(io.open(P.result_path, "wb"))
  out:write(json.encode(data))
  out:close()
end

local function same_rgba(a, b)
  for i = 1, 4 do
    if a[i] ~= b[i] then
      return false
    end
  end
  return true
end

local function run()
  dofile(P.lua_dir .. "/prelude.lua")

  local rgb = Sprite(4, 4, ColorMode.RGB)
  local v = color_value(rgb, { 10, 20, 30, 40 })
  check("rgb roundtrip", same_rgba({ pixel_rgba(rgb, v) }, { 10, 20, 30, 40 }))
  check("rgb transparent", is_transparent(rgb, color_value(rgb, { 255, 0, 0, 0 })))
  check("rgb opaque", not is_transparent(rgb, v))
  check("rgb clear", clear_value(rgb) == 0)

  local gray = Sprite(4, 4, ColorMode.GRAY)
  check("gray white", same_rgba({ pixel_rgba(gray, color_value(gray, { 255, 255, 255, 255 })) },
    { 255, 255, 255, 255 }))
  check("gray luma", same_rgba({ pixel_rgba(gray, color_value(gray, { 0, 255, 0, 128 })) },
    { 182, 182, 182, 128 }))
  check("gray transparent", is_transparent(gray, color_value(gray, { 9, 9, 9, 0 })))

  local indexed = Sprite(4, 4, ColorMode.INDEXED)
  local pal = Palette(4)
  pal:setColor(0, Color { r = 0, g = 0, b = 0, a = 0 })
  pal:setColor(1, Color { r = 255, g = 0, b = 0 })
  pal:setColor(2, Color { r = 0, g = 0, b = 255 })
  pal:setColor(3, Color { r = 250, g = 250, b = 250 })
  indexed:setPalette(pal)
  indexed.transparentColor = 0
  check("indexed exact", color_value(indexed, { 0, 0, 255, 255 }) == 2)
  check("indexed nearest", color_value(indexed, { 240, 10, 10, 255 }) == 1)
  check("indexed skips transparent index", color_value(indexed, { 0, 0, 0, 255 }) ~= 0)
  check("indexed alpha 0", color_value(indexed, { 255, 0, 0, 0 }) == 0)
  check("indexed lookup", same_rgba({ pixel_rgba(indexed, 3) }, { 250, 250, 250, 255 }))
  check("indexed transparent lookup", select(4, pixel_rgba(indexed, 0)) == 0)
  check("indexed is_transparent", is_transparent(indexed, 0) and not is_transparent(indexed, 1))
  check("indexed clear", clear_value(indexed) == 0)

  local spr = Sprite(8, 8, ColorMode.RGB)
  local layer = spr.layers[1]
  local red = color_value(spr, { 255, 0, 0, 255 })
  local cel = layer:cel(1)
  cel.image = Image(3, 3, ColorMode.RGB)
  cel.position = Point(-2, -2)
  cel.image:drawPixel(0, 0, red)
  cel = ensure_cel_bounds(spr, layer, 1, Rectangle(5, 5, 2, 2))
  check("cel grows to union", cel.bounds == Rectangle(-2, -2, 9, 9))
  check("off-canvas pixel kept", cel.image:getPixel(0, 0) == red)
  check("new area is clear", cel.image:getPixel(8, 8) == clear_value(spr))
  local same = ensure_cel_bounds(spr, layer, 1, Rectangle(0, 0, 1, 1))
  check("covered rect keeps cel", same.bounds == Rectangle(-2, -2, 9, 9))

  local empty = spr:newLayer()
  local fresh = ensure_cel_bounds(spr, empty, 1, Rectangle(1, 2, 3, 4))
  check("missing cel created", fresh.bounds == Rectangle(1, 2, 3, 4))

  local tree = Sprite(4, 4)
  tree.layers[1].name = "body"
  local outer = tree:newGroup()
  outer.name = "outer"
  local inner = tree:newGroup()
  inner.name = "inner"
  inner.parent = outer
  local deep = tree:newLayer()
  deep.name = "body"
  deep.parent = inner
  local slashed = tree:newLayer()
  slashed.name = "x/y"
  slashed.parent = outer
  local shadow = tree:newLayer()
  shadow.name = "shadow"
  shadow.parent = inner

  check("shallow name wins", find_layer(tree, "body") == tree.layers[1])
  check("nested by name", find_layer(tree, "shadow") == shadow)
  check("group path", find_layer(tree, "outer/inner/body") == deep)
  check("path with slash in name", find_layer(tree, "outer/x/y") == slashed)
  check("exact name with slash", find_layer(tree, "x/y") == slashed)
  check("missing layer", find_layer(tree, "outer/nope") == nil)
  check("empty name", find_layer(tree, "") == tree.layers[1])
  check("all layers", #all_layers(tree) == 6)
  check("all layers depth first", all_layers(tree)[3] == inner and all_layers(tree)[4] == deep)

  tree:newFrame()
  tree:newFrame()
  local frames = frame_list(tree, nil)
  check("all frames", #frames == 3 and frames[3] == 3)
  check("listed frames", #frame_list(tree, { 3, 1 }) == 2)
  check("frame out of range", not pcall(frame_list, tree, { 4 }))
  local ok, err = pcall(fail, "nope")
  check("fail raises user error", not ok and type(err) == "table" and err.user == "nope")
end

local ok, err = xpcall(run, debug.traceback)
if not ok then
  table.insert(failures, tostring(type(err) == "table" and err.user or err))
end
if #failures > 0 then
  write_result({ ok = false, error = "prelude checks failed: " .. table.concat(failures, "; ") })
else
  write_result({ ok = true, checks = checks })
end
