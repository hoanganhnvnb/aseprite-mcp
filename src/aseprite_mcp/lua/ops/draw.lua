-- Drawing ops. Shapes are collected as horizontal spans clipped to the canvas, merged
-- per row so every pixel is written once, then painted into a copy of the cel image.

-- Spans are stored as l * SPAN_SHIFT + r so a row sorts with plain numbers.
local SPAN_SHIFT = 1 << 20

local function draw_layer(spr, name)
  if name == nil or name == "" then
    for _, layer in ipairs(all_layers(spr)) do
      if not layer.isGroup and not layer.isTilemap then
        return layer, layer_path(layer)
      end
    end
    fail("the sprite has no normal layer to draw on")
  end
  local layer = get_layer(spr, name)
  local path = layer_path(layer)
  if layer.isGroup then
    fail("'" .. path .. "' is a group; draw on one of its layers")
  end
  if layer.isTilemap then
    fail("'" .. path .. "' is a tilemap layer; drawing tools paint normal layers only")
  end
  return layer, path
end

-- Resolves layer, frame and create_cel; shared by every drawing op.
local function draw_target(spr, p)
  local layer, path = draw_layer(spr, p.layer)
  local frame = frame_list(spr, p.frame or 1)[1]
  if layer:cel(frame) == nil and p.create_cel == false then
    fail(string.format("'%s' has no cel in frame %d; pass create_cel=true to add one",
      path, frame))
  end
  return { spr = spr, layer = layer, path = path, frame = frame }
end

-- The target's cel grown to cover rect, never shared with other frames, and a copy of
-- its image to paint into. Assign the copy back with `cel.image = img`.
local function writable(t, rect)
  local cel = t.layer:cel(t.frame)
  if cel ~= nil then
    own_cel(t.spr, t.layer, cel, image_users(t.layer))
  end
  cel = ensure_cel_bounds(t.spr, t.layer, t.frame, rect)
  return cel, cel.image:clone()
end

local function new_spans(spr)
  return { w = spr.width, h = spr.height, rows = {} }
end

local function add_span(s, y, l, r)
  if y < 0 or y >= s.h then
    return
  end
  if l < 0 then
    l = 0
  end
  if r >= s.w then
    r = s.w - 1
  end
  if l > r then
    return
  end
  local row = s.rows[y]
  if row == nil then
    row = {}
    s.rows[y] = row
  end
  row[#row + 1] = l * SPAN_SHIFT + r
end

local function add_box(s, x, y, w, h)
  local top, bottom = math.max(y, 0), math.min(y + h - 1, s.h - 1)
  for row = top, bottom do
    add_span(s, row, x, x + w - 1)
  end
end

-- Rows in ascending order as { y = y, spans = { l1, r1, l2, r2, ... } } with
-- overlapping and touching spans joined, plus the pixel count and the bounds.
local function merged(s)
  local ys = {}
  for y in pairs(s.rows) do
    ys[#ys + 1] = y
  end
  table.sort(ys)
  local out, count = {}, 0
  local left, right = math.huge, -1
  for _, y in ipairs(ys) do
    local row = s.rows[y]
    table.sort(row)
    local list = {}
    local cl, cr = row[1] // SPAN_SHIFT, row[1] % SPAN_SHIFT
    for i = 2, #row do
      local l, r = row[i] // SPAN_SHIFT, row[i] % SPAN_SHIFT
      if l <= cr + 1 then
        if r > cr then
          cr = r
        end
      else
        list[#list + 1] = cl
        list[#list + 1] = cr
        cl, cr = l, r
      end
    end
    list[#list + 1] = cl
    list[#list + 1] = cr
    for i = 1, #list, 2 do
      count = count + list[i + 1] - list[i] + 1
    end
    left = math.min(left, list[1])
    right = math.max(right, list[#list])
    out[#out + 1] = { y = y, spans = list }
  end
  if count == 0 then
    return out, 0, nil
  end
  local bounds = Rectangle(left, out[1].y, right - left + 1, out[#out].y - out[1].y + 1)
  return out, count, bounds
end

-- Straight-alpha "over" of a fixed colour onto stored pixel values, cached per value.
local function blender(spr, layer, color)
  local sr, sg, sb, sa = color[1], color[2], color[3], color[4]
  local cache = {}
  return function(v)
    local out = cache[v]
    if out == nil then
      local dr, dg, db, da = pixel_rgba(spr, v, layer)
      local keep = da * (255 - sa)
      local a = sa * 255 + keep
      local half = a // 2
      out = color_value(spr, {
        (sr * sa * 255 + dr * keep + half) // a,
        (sg * sa * 255 + dg * keep + half) // a,
        (sb * sa * 255 + db * keep + half) // a,
        (a + 127) // 255,
      }, layer)
      cache[v] = out
    end
    return out
  end
end

-- Paints the spans with color (an {r, g, b, a} list) and returns the pixel count.
local function paint_spans(t, s, color, blend)
  local rows, count, bounds = merged(s)
  if count == 0 or (blend and color[4] == 0) then
    return 0
  end
  local spr, layer = t.spr, t.layer
  local cel, img = writable(t, bounds)
  local ox, oy = cel.position.x, cel.position.y
  if blend and color[4] < 255 then
    local over = blender(spr, layer, color)
    for _, row in ipairs(rows) do
      local y, list = row.y - oy, row.spans
      for i = 1, #list, 2 do
        for x = list[i] - ox, list[i + 1] - ox do
          img:drawPixel(x, y, over(img:getPixel(x, y)))
        end
      end
    end
  else
    local value = color_value(spr, color, layer)
    for _, row in ipairs(rows) do
      local y, list = row.y - oy, row.spans
      for i = 1, #list, 2 do
        img:clear(Rectangle(list[i] - ox, y, list[i + 1] - list[i] + 1, 1), value)
      end
    end
  end
  cel.image = img
  return count
end

-- Square brush offsets: odd sizes are centred, even sizes reach one pixel further
-- towards +x/+y.
local function brush(thickness)
  local lo = -((thickness - 1) // 2)
  return lo, lo + thickness - 1
end

-- Step i along the major axis sits at minor offset round(i * dminor / dmajor) with
-- halves rounded away from the start: the pixels Bresenham's error term picks, but
-- computed per step so a long segment can begin at the first step near the canvas.
-- For one segment, the brush covers a single interval per row, kept as row min/max.
local function add_segment(s, x0, y0, x1, y1, lo, hi)
  local dx, dy = x1 - x0, y1 - y0
  local n = math.max(math.abs(dx), math.abs(dy))
  if n == 0 then
    add_box(s, x0 + lo, y0 + lo, hi - lo + 1, hi - lo + 1)
    return
  end
  local x_major = math.abs(dx) >= math.abs(dy)
  local m0, d, size = x0, dx, s.w
  local n0, e = y0, dy
  if not x_major then
    m0, d, size, n0, e = y0, dy, s.h, x0, dx
  end
  local sm = d < 0 and -1 or 1
  local sn = e < 0 and -1 or 1
  local ae = math.abs(e)
  -- steps whose brush can touch the canvas along the major axis
  local first, last = -hi, size - 1 - lo
  if sm > 0 then
    first, last = first - m0, last - m0
  else
    first, last = m0 - last, m0 - first
  end
  first, last = math.max(first, 0), math.min(last, n)
  local low, high = {}, {}
  local function cover(row, l, r)
    if low[row] == nil or l < low[row] then
      low[row] = l
    end
    if high[row] == nil or r > high[row] then
      high[row] = r
    end
  end
  for i = first, last do
    local major = m0 + sm * i
    local minor = n0 + sn * ((2 * i * ae + n) // (2 * n))
    if x_major then
      for row = minor + lo, minor + hi do
        cover(row, major + lo, major + hi)
      end
    else
      for row = major + lo, major + hi do
        cover(row, minor + lo, minor + hi)
      end
    end
  end
  for row, l in pairs(low) do
    add_span(s, row, l, high[row])
  end
end

local function add_polyline(s, points, thickness, closed)
  local lo, hi = brush(thickness)
  for i = 1, #points - 1 do
    local a, b = points[i], points[i + 1]
    add_segment(s, a[1], a[2], b[1], b[2], lo, hi)
  end
  if closed and #points > 2 then
    local a, b = points[#points], points[1]
    add_segment(s, a[1], a[2], b[1], b[2], lo, hi)
  end
end

-- Half width of every row of the ellipse (index = distance from the centre row),
-- from the midpoint algorithm with all terms scaled by 4 to stay in integers.
local function half_widths(rx, ry)
  local xr = {}
  for i = 0, ry do
    xr[i] = 0
  end
  if ry == 0 then
    xr[0] = rx
    return xr
  end
  local rx2, ry2 = rx * rx, ry * ry
  local x, y = 0, ry
  local px, py = 0, 2 * rx2 * ry
  local p = 4 * ry2 - 4 * rx2 * ry + rx2
  while px < py do
    if x > xr[y] then
      xr[y] = x
    end
    x = x + 1
    px = px + 2 * ry2
    if p < 0 then
      p = p + 4 * (ry2 + px)
    else
      y = y - 1
      py = py - 2 * rx2
      p = p + 4 * (ry2 + px - py)
    end
  end
  p = ry2 * (2 * x + 1) * (2 * x + 1) + 4 * rx2 * (y - 1) * (y - 1) - 4 * rx2 * ry2
  while y >= 0 do
    if x > xr[y] then
      xr[y] = x
    end
    y = y - 1
    py = py - 2 * rx2
    if p > 0 then
      p = p + 4 * (rx2 - py)
    else
      x = x + 1
      px = px + 2 * ry2
      p = p + 4 * (rx2 - py + px)
    end
  end
  -- Very flat ellipses stop short of rx on the centre row.
  xr[0] = rx
  return xr
end

local function add_ellipse(s, cx, cy, rx, ry, fill)
  local xr = half_widths(rx, ry)
  for dy = 0, ry do
    local w = xr[dy]
    local rows = dy == 0 and { cy } or { cy - dy, cy + dy }
    -- A pixel is inside the outline when its four neighbours are in the shape too.
    local inner = -1
    if not fill then
      inner = math.min(w - 1, xr[math.abs(dy - 1)] or -1, xr[dy + 1] or -1)
    end
    for _, y in ipairs(rows) do
      if inner < 0 then
        add_span(s, y, cx - w, cx + w)
      else
        add_span(s, y, cx - w, cx - inner - 1)
        add_span(s, y, cx + inner + 1, cx + w)
      end
    end
  end
end

-- Even-odd scanline fill. Points are pixel centres; a row takes the pixels between
-- pairs of edge crossings, edges counting as half-open in y so shared vertices are
-- not counted twice. The outline is added by the caller.
local function add_polygon_fill(s, points)
  local edges = {}
  local top, bottom = math.huge, -math.huge
  for i = 1, #points do
    local a, b = points[i], points[i % #points + 1]
    if a[2] ~= b[2] then
      if a[2] > b[2] then
        a, b = b, a
      end
      edges[#edges + 1] = { a[1], a[2], b[1] - a[1], b[2] - a[2], b[2] }
      top, bottom = math.min(top, a[2]), math.max(bottom, b[2])
    end
  end
  top, bottom = math.max(top, 0), math.min(bottom, s.h - 1)
  local function before(p, q)
    return p[1] * q[2] < q[1] * p[2]
  end
  for y = top, bottom do
    local xs = {}
    for _, e in ipairs(edges) do
      if y >= e[2] and y < e[5] then
        -- crossing at x = e[1] + (y - e[2]) * e[3] / e[4], kept as a fraction
        xs[#xs + 1] = { e[1] * e[4] + (y - e[2]) * e[3], e[4] }
      end
    end
    table.sort(xs, before)
    for i = 1, #xs - 1, 2 do
      local a, b = xs[i], xs[i + 1]
      add_span(s, y, -((-a[1]) // a[2]), b[1] // b[2])
    end
  end
end

local function shape_result(t, painted)
  return { layer = t.path, frame = t.frame, painted = painted }
end

OPS.draw_pixels = function(ctx, p)
  local spr = need_sprite(ctx)
  local t = draw_target(spr, p)
  local w, h = spr.width, spr.height
  local inside, skipped = {}, 0
  local left, top, right, bottom = w, h, -1, -1
  for _, px in ipairs(p.pixels) do
    local x, y = px[1], px[2]
    if x >= 0 and y >= 0 and x < w and y < h then
      inside[#inside + 1] = px
      left, right = math.min(left, x), math.max(right, x)
      top, bottom = math.min(top, y), math.max(bottom, y)
    else
      skipped = skipped + 1
    end
  end
  local result = shape_result(t, #inside)
  result.skipped_outside = skipped
  if #inside == 0 then
    return result
  end
  local cel, img = writable(t, Rectangle(left, top, right - left + 1, bottom - top + 1))
  local ox, oy = cel.position.x, cel.position.y
  local values = {}
  for _, px in ipairs(inside) do
    local key = ((px[3] * 256 + px[4]) * 256 + px[5]) * 256 + px[6]
    local value = values[key]
    if value == nil then
      value = color_value(spr, { px[3], px[4], px[5], px[6] }, t.layer)
      values[key] = value
    end
    img:drawPixel(px[1] - ox, px[2] - oy, value)
  end
  cel.image = img
  return result
end

OPS.draw_line = function(ctx, p)
  local spr = need_sprite(ctx)
  local t = draw_target(spr, p)
  local s = new_spans(spr)
  add_polyline(s, p.points, p.thickness or 1, p.closed)
  return shape_result(t, paint_spans(t, s, p.color, p.blend))
end

OPS.draw_rect = function(ctx, p)
  local spr = need_sprite(ctx)
  local t = draw_target(spr, p)
  local s = new_spans(spr)
  local r, k = p.rect, p.thickness or 1
  if p.fill or 2 * k >= r.w or 2 * k >= r.h then
    add_box(s, r.x, r.y, r.w, r.h)
  else
    add_box(s, r.x, r.y, r.w, k)
    add_box(s, r.x, r.y + r.h - k, r.w, k)
    add_box(s, r.x, r.y + k, k, r.h - 2 * k)
    add_box(s, r.x + r.w - k, r.y + k, k, r.h - 2 * k)
  end
  return shape_result(t, paint_spans(t, s, p.color, p.blend))
end

OPS.draw_ellipse = function(ctx, p)
  local spr = need_sprite(ctx)
  local t = draw_target(spr, p)
  local s = new_spans(spr)
  add_ellipse(s, p.cx, p.cy, p.rx, p.ry, p.fill)
  return shape_result(t, paint_spans(t, s, p.color, p.blend))
end

OPS.draw_polygon = function(ctx, p)
  local spr = need_sprite(ctx)
  local t = draw_target(spr, p)
  local s = new_spans(spr)
  if p.fill then
    add_polygon_fill(s, p.points)
  end
  add_polyline(s, p.points, 1, true)
  return shape_result(t, paint_spans(t, s, p.color, p.blend))
end

-- Returns matches(x, y) for canvas pixels: true when the layer's pixel there is within
-- tolerance of the seed's colour. Outside the cel the layer is transparent.
local function matcher(t, cel, sx, sy, tolerance)
  local spr, layer = t.spr, t.layer
  local img, cx, cy, cw, ch
  if cel ~= nil then
    img, cx, cy = cel.image, cel.position.x, cel.position.y
    cw, ch = img.width, img.height
  end
  local function decode(v)
    local r, g, b, a = pixel_rgba(spr, v, layer)
    if a == 0 then
      return 0, 0, 0, 0
    end
    return r, g, b, a
  end
  local function inside(x, y)
    return img ~= nil and x >= cx and y >= cy and x < cx + cw and y < cy + ch
  end
  local r0, g0, b0, a0 = 0, 0, 0, 0
  if inside(sx, sy) then
    r0, g0, b0, a0 = decode(img:getPixel(sx - cx, sy - cy))
  end
  local function close(r, g, b, a)
    return math.abs(r - r0) <= tolerance and math.abs(g - g0) <= tolerance
      and math.abs(b - b0) <= tolerance and math.abs(a - a0) <= tolerance
  end
  local empty_matches = close(0, 0, 0, 0)
  local cache = {}
  return function(x, y)
    if not inside(x, y) then
      return empty_matches
    end
    local v = img:getPixel(x - cx, y - cy)
    local hit = cache[v]
    if hit == nil then
      hit = close(decode(v))
      cache[v] = hit
    end
    return hit
  end
end

-- Scanline flood fill with an explicit stack. Each filled run is the maximal run of
-- matching pixels in its row, so a run start found in `done` means the run is filled.
local function flood(s, matches, sx, sy)
  local w, h = s.w, s.h
  local done = {}
  local function filled(y, x)
    local row = done[y]
    if row ~= nil then
      for i = 1, #row, 2 do
        if x >= row[i] and x <= row[i + 1] then
          return true
        end
      end
    end
    return false
  end
  local stack, top = { sx, sy }, 2
  while top > 0 do
    local x, y = stack[top - 1], stack[top]
    top = top - 2
    if not filled(y, x) then
      local l, r = x, x
      while l > 0 and matches(l - 1, y) do
        l = l - 1
      end
      while r < w - 1 and matches(r + 1, y) do
        r = r + 1
      end
      local row = done[y]
      if row == nil then
        row = {}
        done[y] = row
      end
      row[#row + 1] = l
      row[#row + 1] = r
      add_span(s, y, l, r)
      for ny = y - 1, y + 1, 2 do
        if ny >= 0 and ny < h then
          local nx = l
          while nx <= r do
            if matches(nx, ny) then
              if not filled(ny, nx) then
                stack[top + 1], stack[top + 2] = nx, ny
                top = top + 2
              end
              repeat
                nx = nx + 1
              until nx > r or not matches(nx, ny)
            else
              nx = nx + 1
            end
          end
        end
      end
    end
  end
end

local function every_match(s, matches)
  for y = 0, s.h - 1 do
    local x = 0
    while x < s.w do
      if matches(x, y) then
        local l = x
        while x + 1 < s.w and matches(x + 1, y) do
          x = x + 1
        end
        add_span(s, y, l, x)
      end
      x = x + 1
    end
  end
end

OPS.fill_area = function(ctx, p)
  local spr = need_sprite(ctx)
  local t = draw_target(spr, p)
  if p.x < 0 or p.y < 0 or p.x >= spr.width or p.y >= spr.height then
    fail(string.format("seed %d,%d is outside the canvas (%dx%d)",
      p.x, p.y, spr.width, spr.height))
  end
  local matches = matcher(t, t.layer:cel(t.frame), p.x, p.y, p.tolerance or 0)
  local s = new_spans(spr)
  if p.contiguous == false then
    every_match(s, matches)
  else
    flood(s, matches, p.x, p.y)
  end
  return shape_result(t, paint_spans(t, s, p.color, false))
end
