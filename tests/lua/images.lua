-- Test helper: the pixels of one layer's cel in every frame as a hex string of the
-- cel bounds and image bytes, or false where there is no cel.

local fh = assert(io.open(app.params.params, "rb"))
local P = json.decode(fh:read("a"))
fh:close()
dofile(P.lua_dir .. "/prelude.lua")

local spr = app.sprite
local layer = spr.layers[1]
if P.layer then
  layer = find_layer(spr, P.layer)
  assert(layer, "no layer " .. P.layer)
end

local images = {}
for i = 1, #spr.frames do
  local cel = layer:cel(i)
  if cel then
    local b = cel.bounds
    local hex = cel.image.bytes:gsub(".", function(c)
      return string.format("%02x", c:byte())
    end)
    images[i] = string.format("%d,%d,%d,%d:%s", b.x, b.y, b.width, b.height, hex)
  else
    images[i] = false
  end
end

local out = assert(io.open(P.result_path, "wb"))
out:write(json.encode({ ok = true, images = images }))
out:close()
