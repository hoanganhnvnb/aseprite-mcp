-- Test helper: locks the layers named in params.lock, then reports the paths of all
-- locked layers.

local fh = assert(io.open(app.params.params, "rb"))
local P = json.decode(fh:read("a"))
fh:close()
dofile(P.lua_dir .. "/prelude.lua")

local spr = open_sprite(P.open_file)
local lock = P.lock or {}
for i = 1, #lock do
  local layer = assert(find_layer(spr, lock[i]), "no layer " .. lock[i])
  layer.isEditable = false
end

local locked = {}
for _, layer in ipairs(all_layers(spr)) do
  if not layer.isEditable then
    table.insert(locked, layer_path(layer))
  end
end

local saved = false
if #lock > 0 and P.save_tmp then
  spr:saveCopyAs(P.save_tmp)
  saved = true
end

local out = assert(io.open(P.result_path, "wb"))
out:write(json.encode({ ok = true, saved = saved, locked = locked }))
out:close()
