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
  check("rgb transparent", select(4, pixel_rgba(rgb, color_value(rgb, { 255, 0, 0, 0 }))) == 0)
  check("rgb clear", clear_value(rgb) == 0)

  local gray = Sprite(4, 4, ColorMode.GRAY)
  check("gray white", same_rgba({ pixel_rgba(gray, color_value(gray, { 255, 255, 255, 255 })) },
    { 255, 255, 255, 255 }))
  check("gray luma", same_rgba({ pixel_rgba(gray, color_value(gray, { 0, 255, 0, 128 })) },
    { 182, 182, 182, 128 }))
  check("gray transparent", select(4, pixel_rgba(gray, color_value(gray, { 9, 9, 9, 0 }))) == 0)

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
  check("indexed clear", clear_value(indexed) == 0)

  local bg = Sprite(2, 2, ColorMode.INDEXED)
  bg:setPalette(pal)
  bg.transparentColor = 0
  app.sprite = bg
  app.layer = bg.layers[1]
  app.command.BackgroundFromLayer()
  local back = bg.layers[1]
  check("background layer", back.isBackground)
  check("background index 0 is opaque", select(4, pixel_rgba(bg, 0, back)) == 255)
  check("background maps to index 0", color_value(bg, { 0, 0, 0, 255 }, back) == 0)
  check("background ignores alpha", color_value(bg, { 255, 0, 0, 0 }, back) == 1)
  bg:newEmptyFrame(2)
  app.range.layers = { back }
  app.range.frames = { bg.frames[1], bg.frames[2] }
  app.command.LinkCels()
  local owned = own_cel(bg, back, back:cel(2), image_users(back))
  check("own_cel unlinks background cel", owned.image.id ~= back:cel(1).image.id
    and owned.frameNumber == 2)

  local locked_bg = Sprite(2, 2)
  app.sprite = locked_bg
  app.layer = locked_bg.layers[1]
  app.command.BackgroundFromLayer()
  local locked_back = locked_bg.layers[1]
  locked_bg:newEmptyFrame(2)
  app.range.layers = { locked_back }
  app.range.frames = { locked_bg.frames[1], locked_bg.frames[2] }
  app.command.LinkCels()
  app.range:clear()
  locked_back.isEditable = false
  local own_ok, own_err = pcall(own_cel, locked_bg, locked_back, locked_back:cel(2),
    image_users(locked_back))
  check("own_cel on locked background: " .. tostring(own_err), own_ok)
  check("locked background cel unlinked",
    locked_back:cel(1).image.id ~= locked_back:cel(2).image.id)
  check("background lock restored", not locked_back.isEditable)
  check("range cleared after unlink", app.range.isEmpty)
  check("layer arg on normal layer", color_value(indexed, { 0, 0, 0, 0 }, indexed.layers[1]) == 0)

  local fresh_indexed = Sprite(2, 2, ColorMode.INDEXED)
  set_default_palette(fresh_indexed)
  local black = color_value(fresh_indexed, { 0, 0, 0, 255 })
  check("default palette transparent entry", fresh_indexed.transparentColor == 0
    and fresh_indexed.palettes[1]:getColor(0).alpha == 0)
  check("default palette keeps black", black ~= 0
    and same_rgba({ pixel_rgba(fresh_indexed, black) }, { 0, 0, 0, 255 }))

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
  check("get_layer finds nested", get_layer(tree, "outer/inner/body") == deep)
  local _, missing_err = pcall(get_layer, tree, "nope")
  check("get_layer names missing layer", missing_err.user == "layer 'nope' not found")
  check("inside nested group", is_inside(tree, deep, outer) and is_inside(tree, deep, inner))
  check("not inside sibling", not is_inside(tree, slashed, inner))
  check("cel layers skip groups", #cel_layers(tree) == 4)

  local anim = Sprite(4, 4)
  anim:newEmptyFrame()
  local body = anim.layers[1]
  local first = body:cel(1)
  first.position = Point(1, 2)
  first.opacity = 77
  first.zIndex = 2
  check("copy_cel copies", copy_cel(anim, body, 1, 2) == "copied")
  local second = body:cel(2)
  check("copy keeps cel props", second.position == Point(1, 2) and second.opacity == 77
    and second.zIndex == 2)
  check("copy is independent", second.image ~= first.image)
  anim:newEmptyFrame()
  check("copy_cel clears target", copy_cel(anim, body, 3, 1) == "cleared" and body:cel(1) == nil)
  local put = put_cel(anim, body, 3, Image(2, 2), Point(-1, 0), cel_props(second))
  check("put_cel applies props", put.opacity == 77 and put.zIndex == 2
    and put.position == Point(-1, 0))

  tree:newFrame()
  tree:newFrame()
  local frames = frame_list(tree, nil)
  check("all frames", #frames == 3 and frames[3] == 3)
  check("listed frames", #frame_list(tree, { 3, 1 }) == 2)
  local sorted = frame_list(tree, { 3, 1, 3 })
  check("frames sorted without duplicates", #sorted == 2 and sorted[1] == 1 and sorted[2] == 3)
  check("single frame number", frame_list(tree, 2)[1] == 2)
  check("frame out of range", not pcall(frame_list, tree, { 4 }))
  check("frame zero", not pcall(frame_list, tree, 0))
  check("fractional frame", not pcall(frame_list, tree, { 1.5 }))
  check("frame string", not pcall(frame_list, tree, "2"))
  check("empty frame list", not pcall(frame_list, tree, {}))
  check("frame map", not pcall(frame_list, tree, { a = 1 }))
  local _, frame_err = pcall(frame_list, tree, "2")
  check("frame error names value", type(frame_err) == "table" and frame_err.user:find('"2"', 1, true))
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
