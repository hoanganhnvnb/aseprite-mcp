-- Flip and rotate in canvas space: each cel image is flipped or turned and the cel is
-- moved so every pixel lands where the canvas-wide transform puts it. Content beyond
-- the canvas edge travels along; nothing is cropped.

-- The named layer, or every image layer when name is nil. Everything is checked
-- before any change so a refused call leaves the sprite as it was.
local function target_layers(spr, name)
  if name ~= nil then
    local layer = image_layer(spr, name)
    require_editable(layer)
    return { layer }
  end
  local layers = cel_layers(spr)
  for _, layer in ipairs(layers) do
    if layer.isTilemap then
      fail(string.format("'%s' is a tilemap layer and cannot be flipped or rotated; "
        .. "name the layers to change one by one", layer_path(layer)))
    end
    require_editable(layer)
  end
  return layers
end

OPS.flip = function(ctx, p)
  local spr = need_sprite(ctx)
  local horizontal = p.axis == "horizontal"
  if not horizontal and p.axis ~= "vertical" then
    fail("axis must be 'horizontal' or 'vertical', got " .. tostring(p.axis))
  end
  local layers = target_layers(spr, p.layer)
  local frames = frame_list(spr, p.frames)
  local count = 0
  for _, layer in ipairs(layers) do
    for _, cel in ipairs((cels_to_change(spr, layer, frames))) do
      local b = cel.bounds
      if horizontal then
        cel.image:flip(FlipType.HORIZONTAL)
        cel.position = Point(spr.width - b.x - b.width, b.y)
      else
        cel.image:flip(FlipType.VERTICAL)
        cel.position = Point(b.x, spr.height - b.y - b.height)
      end
      count = count + 1
    end
  end
  return { axis = p.axis, layers = #layers, frames = #frames, cels = count }
end

-- The image turned clockwise by 90 or 270 degrees, plus the offset of its top-left
-- corner. The Image API cannot turn an image, so a throwaway sprite holding just this
-- image is turned with the Rotate command; its pixel values are copied untouched.
-- The Rotate command takes -90 for a quarter turn anticlockwise and ignores 270.
local COMMAND_ANGLE = { [90] = 90, [180] = 180, [270] = -90 }

local function turned(spr, image, angle)
  local tmp = Sprite(ImageSpec {
    width = image.width,
    height = image.height,
    colorMode = image.colorMode,
    transparentColor = image.spec.transparentColor,
  })
  local ok, out, offset = pcall(function()
    app.sprite = tmp
    tmp.layers[1]:cel(1).image = image
    app.command.Rotate { angle = COMMAND_ANGLE[angle], target = "canvas" }
    local cel = tmp.layers[1]:cel(1)
    if cel == nil then
      return new_image(spr, image.height, image.width), Point(0, 0)
    end
    return cel.image:clone(), cel.position
  end)
  tmp:close()
  app.sprite = spr
  if not ok then
    error(out, 0)
  end
  return out, offset
end

local function rotate_cel(spr, cel, angle)
  local b = cel.bounds
  local w, h = spr.width, spr.height
  if angle == 180 then
    cel.image:flip(FlipType.HORIZONTAL)
    cel.image:flip(FlipType.VERTICAL)
    cel.position = Point(w - b.x - b.width, h - b.y - b.height)
    return
  end
  -- A quarter turn about the canvas centre. When w - h is odd the centre falls between
  -- pixels: 90 rounds the half pixel towards the top-left and 270 is its exact inverse.
  local ox, oy = (w - h) // 2, (h - w) // 2
  local x, y
  if angle == 90 then
    x, y = ox + h - b.y - b.height, oy + b.x
  else
    x, y = b.y - oy, oy + w - b.x - b.width
  end
  local image, offset = turned(spr, cel.image, angle)
  cel.image = image
  cel.position = Point(x + offset.x, y + offset.y)
end

local function rotate_sprite(spr, p)
  local frames = frame_list(spr, p.frames)
  if #frames ~= #spr.frames then
    fail(string.format("rotating the whole sprite turns all %d frames; pass frames=\"all\" "
      .. "or name a layer to turn only some frames", #spr.frames))
  end
  local layers = target_layers(spr, nil)
  local count = 0
  for _, layer in ipairs(layers) do
    for _ in pairs(image_users(layer)) do
      count = count + 1
    end
  end
  local w, h = spr.width, spr.height
  if p.angle ~= 180 then
    w, h = h, w
  end
  app.sprite = spr
  app.command.Rotate { angle = COMMAND_ANGLE[p.angle], target = "canvas" }
  if spr.width ~= w or spr.height ~= h then
    fail(string.format("Aseprite did not turn the canvas (%d x %d)", spr.width, spr.height))
  end
  return {
    angle = p.angle,
    layers = #layers,
    frames = #frames,
    cels = count,
    width = spr.width,
    height = spr.height,
  }
end

OPS.rotate = function(ctx, p)
  local spr = need_sprite(ctx)
  if p.angle ~= 90 and p.angle ~= 180 and p.angle ~= 270 then
    fail("angle must be 90, 180 or 270, got " .. tostring(p.angle))
  end
  if p.layer == nil then
    return rotate_sprite(spr, p)
  end
  local layer = target_layers(spr, p.layer)[1]
  if layer.isBackground and p.angle ~= 180 and spr.width ~= spr.height then
    fail(string.format("'%s' is the background layer and fills the canvas; on a %d x %d "
      .. "canvas it can only turn by 180 (or rotate the whole sprite)",
      layer_path(layer), spr.width, spr.height))
  end
  local frames = frame_list(spr, p.frames)
  local cels = cels_to_change(spr, layer, frames)
  for _, cel in ipairs(cels) do
    rotate_cel(spr, cel, p.angle)
  end
  return {
    angle = p.angle,
    layers = 1,
    frames = #frames,
    cels = #cels,
    width = spr.width,
    height = spr.height,
  }
end
