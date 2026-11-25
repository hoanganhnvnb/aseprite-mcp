-- Test helper: reports the cels of one layer (the first unless params.layer names one)
-- in every frame, after applying params.update = {{frame, opacity, z_index}, ...}.
-- A frame without a cel is reported as false.

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

local update = P.update or {}
for i = 1, #update do
  local u = update[i]
  local cel = assert(layer:cel(math.floor(u[1])), "no cel to update")
  cel.opacity = math.floor(u[2])
  cel.zIndex = math.floor(u[3])
end

local cels = {}
for i = 1, #spr.frames do
  local cel = layer:cel(i)
  if cel then
    cels[i] = {
      x = cel.position.x,
      y = cel.position.y,
      width = cel.bounds.width,
      height = cel.bounds.height,
      opacity = cel.opacity,
      z_index = cel.zIndex,
      image_id = cel.image.id,
    }
  else
    cels[i] = false
  end
end

local saved = false
if #update > 0 and P.save_tmp then
  spr:saveCopyAs(P.save_tmp)
  saved = true
end

local out = assert(io.open(P.result_path, "wb"))
out:write(json.encode({ ok = true, saved = saved, cels = cels }))
out:close()
