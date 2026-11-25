local function find_slice(spr, name)
  for _, slice in ipairs(spr.slices) do
    if slice.name == name then
      return slice
    end
  end
  return nil
end

local function get_slice(spr, name)
  local slice = find_slice(spr, name)
  if slice == nil then
    fail("slice '" .. name .. "' not found")
  end
  return slice
end

local function rect_of(r)
  return { x = r.x, y = r.y, w = r.width, h = r.height }
end

local function hex(c)
  local out = string.format("#%02x%02x%02x", c.red, c.green, c.blue)
  if c.alpha ~= 255 then
    out = out .. string.format("%02x", c.alpha)
  end
  return out
end

local function slice_info(slice)
  return {
    name = slice.name,
    bounds = rect_of(slice.bounds),
    center = slice.center and rect_of(slice.center) or nil,
    pivot = slice.pivot and { x = slice.pivot.x, y = slice.pivot.y } or nil,
    color = hex(slice.color),
    data = slice.data or "",
  }
end

local function check_center(center, bounds)
  if center.x < 0 or center.y < 0 or center.x + center.width > bounds.width
      or center.y + center.height > bounds.height then
    fail(string.format("center must lie inside the slice: a %dx%d slice cannot hold %dx%d "
      .. "at (%d, %d)", bounds.width, bounds.height, center.width, center.height,
      center.x, center.y))
  end
end

local function as_rectangle(r)
  return Rectangle(r.x, r.y, r.w, r.h)
end

OPS.create_slice = function(ctx, p)
  local spr = need_sprite(ctx)
  if find_slice(spr, p.name) ~= nil then
    fail("slice '" .. p.name .. "' already exists")
  end
  local bounds = as_rectangle(p.rect)
  local center = p.center and as_rectangle(p.center)
  if center then
    check_center(center, bounds)
  end
  local slice = spr:newSlice(bounds)
  slice.name = p.name
  if center then
    slice.center = center
  end
  if p.pivot then
    slice.pivot = Point(p.pivot.x, p.pivot.y)
  end
  if p.color then
    slice.color = Color { r = p.color[1], g = p.color[2], b = p.color[3], a = p.color[4] }
  end
  return slice_info(slice)
end

OPS.update_slice = function(ctx, p)
  local spr = need_sprite(ctx)
  local slice = get_slice(spr, p.name)
  local bounds = p.rect and as_rectangle(p.rect) or slice.bounds
  local center = p.center and as_rectangle(p.center) or slice.center
  if center then
    check_center(center, bounds)
  end
  slice.bounds = bounds
  if p.center then
    slice.center = center
  end
  if p.pivot then
    slice.pivot = Point(p.pivot.x, p.pivot.y)
  end
  return slice_info(slice)
end

OPS.list_slices = function(ctx)
  local spr = need_sprite(ctx)
  local out = {}
  for i, slice in ipairs(spr.slices) do
    out[i] = slice_info(slice)
  end
  return { slices = out }
end

OPS.delete_slice = function(ctx, p)
  local spr = need_sprite(ctx)
  spr:deleteSlice(get_slice(spr, p.name))
  return { deleted = p.name, slices_left = #spr.slices }
end
