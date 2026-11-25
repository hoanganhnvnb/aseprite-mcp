-- "" is the sprite itself (top level); anything else must name a group.
local function get_parent(spr, name)
  if name == "" then
    return spr
  end
  local group = find_layer(spr, name)
  if group == nil then
    fail("parent group '" .. name .. "' not found")
  end
  if not group.isGroup then
    fail("'" .. name .. "' is not a group")
  end
  return group
end

local function parent_label(spr, parent)
  return parent == spr and "the top level" or ("'" .. layer_path(parent) .. "'")
end

local function count_with_children(layer)
  local n = 1
  if layer.isGroup then
    for _, child in ipairs(layer.layers) do
      n = n + count_with_children(child)
    end
  end
  return n
end

OPS.add_layer = function(ctx, p)
  local spr = need_sprite(ctx)
  local parent = get_parent(spr, p.parent or "")
  local layer
  if p.kind == "group" then
    layer = spr:newGroup()
  elseif p.kind == "tilemap" then
    -- The Lua API has no tilemap layer constructor; the command does it headless too.
    app.sprite = spr
    app.command.NewLayer { tilemap = true, gridBounds = Rectangle(0, 0, p.tile_size, p.tile_size) }
    layer = app.layer
    if layer == nil or not layer.isTilemap then
      fail("Aseprite did not create the tilemap layer")
    end
  else
    layer = spr:newLayer()
  end
  layer.name = p.name
  layer.parent = parent
  layer.stackIndex = #parent.layers
  return { layer = layer_path(layer), type = p.kind }
end

OPS.update_layer = function(ctx, p)
  local spr = need_sprite(ctx)
  local layer = get_layer(spr, p.layer)
  local name = "'" .. p.layer .. "'"

  local blend
  if p.blend_mode ~= nil then
    blend = BLEND_MODES[p.blend_mode]
    if blend == nil then
      fail("unknown blend mode '" .. tostring(p.blend_mode) .. "'")
    end
  end
  if p.opacity ~= nil or blend ~= nil then
    -- Aseprite ignores these on groups and keeps the background opaque and normal.
    if layer.isGroup then
      fail("group " .. name .. " has no opacity or blend mode")
    end
    if layer.isBackground then
      fail(name .. " is the background layer; its opacity and blend mode are fixed")
    end
  end

  local dest = layer.parent
  if p.parent ~= nil then
    dest = get_parent(spr, p.parent)
    if dest == layer or (dest ~= spr and is_inside(spr, dest, layer)) then
      fail("cannot move " .. name .. " into itself or one of its own groups")
    end
  end
  local moves = dest ~= layer.parent or p.stack_index ~= nil
  if moves and layer.isBackground then
    fail(name .. " is the background layer and cannot be moved")
  end
  if p.stack_index ~= nil then
    local count = #dest.layers
    if dest ~= layer.parent then
      count = count + 1
    end
    if p.stack_index < 1 or p.stack_index > count then
      fail(string.format("stack_index %d is out of range: %s holds %d layers",
        p.stack_index, parent_label(spr, dest), count))
    end
    if dest == spr and p.stack_index == 1 and spr.layers[1].isBackground
        and spr.layers[1] ~= layer then
      fail("stack_index 1 at the top level belongs to the background layer")
    end
  end

  if dest ~= layer.parent then
    layer.parent = dest
  end
  if p.stack_index ~= nil then
    layer.stackIndex = p.stack_index
  end
  if p.new_name ~= nil then
    layer.name = p.new_name
  end
  if p.visible ~= nil then
    layer.isVisible = p.visible
  end
  if p.locked ~= nil then
    layer.isEditable = not p.locked
  end
  if p.opacity ~= nil then
    layer.opacity = p.opacity
  end
  if blend ~= nil then
    layer.blendMode = blend
  end
  return { layer = layer_path(layer), stack_index = layer.stackIndex }
end

OPS.delete_layer = function(ctx, p)
  local spr = need_sprite(ctx)
  local layer = get_layer(spr, p.layer)
  local path = layer_path(layer)
  require_editable(layer)
  if layer.isGroup then
    for _, child in ipairs(all_layers(spr)) do
      if is_inside(spr, child, layer) then
        require_editable(child)
      end
    end
  end
  if #all_layers(spr) - count_with_children(layer) < 1 then
    fail("cannot delete '" .. path .. "': the sprite needs at least one layer")
  end
  spr:deleteLayer(layer)
  return { deleted = path, layers_left = #all_layers(spr) }
end

OPS.duplicate_layer = function(ctx, p)
  local spr = need_sprite(ctx)
  local layer = get_layer(spr, p.layer)
  -- The command deep-copies groups and puts the copy right above the source.
  app.sprite = spr
  app.layer = layer
  app.command.DuplicateLayer()
  local copy = app.layer
  if copy == nil or copy == layer then
    fail("Aseprite could not duplicate '" .. layer_path(layer) .. "'")
  end
  copy.name = p.new_name or (layer.name .. " copy")
  return { layer = layer_path(copy), stack_index = copy.stackIndex }
end

local function kind_of(layer)
  if layer.isGroup then
    return "group"
  elseif layer.isTilemap then
    return "tilemap layer"
  end
  return "layer"
end

OPS.merge_layer_down = function(ctx, p)
  local spr = need_sprite(ctx)
  local layer = get_layer(spr, p.layer)
  local path = layer_path(layer)
  if layer.isGroup or layer.isTilemap then
    fail("cannot merge the " .. kind_of(layer) .. " '" .. path .. "'; only image layers merge")
  end
  if layer.stackIndex == 1 then
    fail("'" .. path .. "' has no layer below it in " .. parent_label(spr, layer.parent))
  end
  local below = layer.parent.layers[layer.stackIndex - 1]
  if below.isGroup or below.isTilemap then
    fail("the layer below '" .. path .. "' is the " .. kind_of(below) .. " '"
      .. layer_path(below) .. "'; only image layers merge")
  end
  require_editable(layer)
  require_editable(below)
  app.sprite = spr
  app.layer = layer
  app.command.MergeDownLayer()
  return { layer = layer_path(below) }
end

-- Sprite:flatten() blends hidden layers in too, so they are deleted first.
OPS.flatten_sprite = function(ctx)
  local spr = need_sprite(ctx)
  local hidden, shown = {}, 0
  local function walk(layers)
    for _, layer in ipairs(layers) do
      if not layer.isVisible then
        table.insert(hidden, layer)
      elseif layer.isGroup then
        walk(layer.layers)
      else
        shown = shown + 1
      end
    end
  end
  walk(spr.layers)
  if shown == 0 then
    fail("nothing to flatten: no visible layer holds pixels")
  end
  local dropped = {}
  for i, layer in ipairs(hidden) do
    dropped[i] = layer_path(layer)
    spr:deleteLayer(layer)
  end
  spr:flatten()
  return { layer = spr.layers[1].name, dropped_hidden = dropped }
end
