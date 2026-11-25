-- Region ops. Pixels are copied with Image:drawImage and cleared with Image:clear on
-- rectangles, so a batch only keeps the touched area in the undo history.

local function canvas_rect(spr, r)
  local area = Rectangle(r.x, r.y, r.w, r.h):intersect(spr.bounds)
  if area.isEmpty then
    fail(string.format("rect (%d, %d, %d x %d) is outside the canvas (%d x %d)",
      r.x, r.y, r.w, r.h, spr.width, spr.height))
  end
  return area
end

-- Clears the part of `area` (canvas coordinates) that lies inside the cel. A
-- background layer cannot be transparent and gets opaque black instead.
local function clear_in_cel(spr, layer, cel, area)
  local hole = area:intersect(cel.bounds)
  if not hole.isEmpty then
    local pos = cel.position
    cel.image:clear(Rectangle(hole.x - pos.x, hole.y - pos.y, hole.width, hole.height),
      color_value(spr, { 0, 0, 0, 0 }, layer))
  end
end

local function area_table(r)
  return { x = r.x, y = r.y, w = r.width, h = r.height }
end

OPS.move_region = function(ctx, p)
  local spr = need_sprite(ctx)
  local layer, path = image_layer(spr, p.layer)
  local frame = frame_list(spr, p.frame or 1)[1]
  local to_layer, to_path = layer, path
  if p.target_layer ~= nil then
    to_layer, to_path = image_layer(spr, p.target_layer)
  end
  local to_frame = frame
  if p.target_frame ~= nil then
    to_frame = frame_list(spr, p.target_frame)[1]
  end
  if not p.copy then
    require_editable(layer)
  end
  require_editable(to_layer)

  local cel = layer:cel(frame)
  if cel == nil then
    fail(string.format("'%s' has no cel in frame %d", path, frame))
  end
  local area = canvas_rect(spr, p.rect)
  -- Read the block before anything changes so overlapping moves stay correct.
  local block = new_image(spr, area.width, area.height)
  block:drawImage(cel.image, Point(cel.position.x - area.x, cel.position.y - area.y),
    255, BlendMode.SRC)

  local dest = Rectangle(area.x + p.dx, area.y + p.dy, area.width, area.height)
  local shown = dest:intersect(spr.bounds)
  local moved = shown.isEmpty and 0 or shown.width * shown.height

  if not p.copy then
    cel = own_cel(spr, layer, cel, image_users(layer))
    clear_in_cel(spr, layer, cel, area)
  end

  if moved > 0 then
    local piece = block
    if shown ~= dest then
      piece = new_image(spr, shown.width, shown.height)
      piece:drawImage(block, Point(dest.x - shown.x, dest.y - shown.y), 255, BlendMode.SRC)
    end
    local target = to_layer:cel(to_frame)
    if target ~= nil then
      target = own_cel(spr, to_layer, target, image_users(to_layer))
    end
    -- Only visible pixels need room in the cel: outside it the layer is transparent.
    local content = piece:shrinkBounds()
    if not content.isEmpty then
      target = ensure_cel_bounds(spr, to_layer, to_frame,
        Rectangle(shown.x + content.x, shown.y + content.y, content.width, content.height))
    end
    if target ~= nil then
      local mode = BlendMode.SRC
      -- A background layer stays opaque, so a block from a normal layer is blended
      -- onto it; a block from a background is opaque already and copied as is, which
      -- also keeps indexed values that equal the transparent index.
      if not layer.isBackground and (p.blend or to_layer.isBackground) then
        mode = BlendMode.NORMAL
      end
      target.image:drawImage(piece,
        Point(shown.x - target.position.x, shown.y - target.position.y), 255, mode)
    end
  end

  return {
    layer = path,
    frame = frame,
    target_layer = to_path,
    target_frame = to_frame,
    rect = area_table(area),
    moved = moved,
    clipped = area.width * area.height - moved,
  }
end

OPS.erase_region = function(ctx, p)
  local spr = need_sprite(ctx)
  local layer, path = image_layer(spr, p.layer)
  require_editable(layer)
  local frames = frame_list(spr, p.frames)
  local area = Rectangle(p.rect.x, p.rect.y, p.rect.w, p.rect.h)
  local cels, skipped = cels_to_change(spr, layer, frames)
  for _, cel in ipairs(cels) do
    clear_in_cel(spr, layer, cel, area)
  end
  return { layer = path, erased_frames = #frames - skipped, skipped_frames = skipped }
end
