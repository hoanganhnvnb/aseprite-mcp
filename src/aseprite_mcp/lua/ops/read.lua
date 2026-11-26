-- Read-only ops. Everything is rendered into an RGB image first, so indexed and
-- grayscale sprites come out as plain RGBA. Pixel values go back to Python as the
-- RGB image stores them: a << 24 | b << 16 | g << 8 | r.

local pc = app.pixelColor

local function rect_table(r)
  return { x = r.x, y = r.y, w = r.width, h = r.height }
end

local function rgb_image(w, h)
  return Image(ImageSpec { width = w, height = h, colorMode = ColorMode.RGB })
end

-- The layer's own pixels in `area`: no layer or cel opacity, no blend mode, shown
-- even when the layer is hidden. Background layers keep index 0 opaque.
local function draw_layer(img, spr, layer, frame, area)
  local cel = layer:cel(frame)
  if cel == nil then
    return
  end
  local pos = cel.position
  if spr.colorMode == ColorMode.RGB then
    img:drawImage(cel.image, Point(pos.x - area.x, pos.y - area.y), 255, BlendMode.SRC)
    return
  end
  local part = cel.bounds:intersect(area)
  if part.isEmpty then
    return
  end
  local src, memo = cel.image, {}
  for y = part.y, part.y + part.height - 1 do
    for x = part.x, part.x + part.width - 1 do
      local v = src:getPixel(x - pos.x, y - pos.y)
      local c = memo[v]
      if c == nil then
        c = pc.rgba(pixel_rgba(spr, v, layer))
        memo[v] = c
      end
      img:drawPixel(x - area.x, y - area.y, c)
    end
  end
end

-- `area` of one frame: the visible layers composited, or only `layer` when given.
-- Loops over frames pass `into`, an image of the area's size that is cleared and
-- reused: Lua's collector does not see image memory, so a new canvas-sized image
-- per frame piles up gigabytes before any is freed.
local function render(spr, frame, layer, area, into)
  local img = into
  if img == nil then
    img = rgb_image(area.width, area.height)
  else
    img:clear()
  end
  if layer == nil then
    img:drawSprite(spr, frame, Point(-area.x, -area.y))
  else
    draw_layer(img, spr, layer, frame, area)
  end
  return img
end

local function optional_layer(spr, name)
  if name == nil then
    return nil
  end
  local layer = get_layer(spr, name)
  local path = layer_path(layer)
  if layer.isGroup then
    fail("'" .. path .. "' is a group; name one of its layers, or leave layer out for the "
      .. "visible composite")
  end
  if layer.isTilemap then
    fail("'" .. path .. "' is a tilemap layer; only image layers can be read on their own")
  end
  return layer
end

local function area_of(spr, region)
  if region == nil then
    return spr.bounds
  end
  return canvas_rect(spr, region)
end

OPS.read_pixels = function(ctx, p)
  local spr = need_sprite(ctx)
  local layer = optional_layer(spr, p.layer)
  local frame = one_frame(spr, p.frame)
  local r = p.rect
  canvas_rect(spr, r)
  local img = render(spr, frame, layer, Rectangle(r.x, r.y, r.w, r.h))
  local pixels, n = {}, 0
  for px in img:pixels() do
    n = n + 1
    pixels[n] = px()
  end
  return { x = r.x, y = r.y, w = r.w, h = r.h, pixels = pixels }
end

OPS.get_bounds = function(ctx, p)
  local spr = need_sprite(ctx)
  local layer = optional_layer(spr, p.layer)
  local frames, buffer = {}, rgb_image(spr.width, spr.height)
  local union
  for i, n in ipairs(frame_list(spr, p.frames)) do
    local b = render(spr, n, layer, spr.bounds, buffer):shrinkBounds()
    if b.isEmpty then
      frames[i] = { frame = n }
    else
      frames[i] = { frame = n, bounds = rect_table(b) }
      union = union and union:union(b) or b
    end
  end
  return { frames = frames, bounds = union and rect_table(union) }
end

OPS.compare_frames = function(ctx, p)
  local spr = need_sprite(ctx)
  local layer = optional_layer(spr, p.layer)
  local a, b = one_frame(spr, p.frame_a), one_frame(spr, p.frame_b)
  local area = area_of(spr, p.region)
  local ia, ib = render(spr, a, layer, area), render(spr, b, layer, area)
  local out = { frame_a = a, frame_b = b, area = rect_table(area), different_pixels = 0 }
  local bytes_a, bytes_b = ia.bytes, ib.bytes
  if bytes_a == bytes_b then
    return out
  end
  -- Whole rows are compared as strings first; only rows that differ are walked.
  local stride, byte = area.width * 4, string.byte
  local count, x0, y0, x1, y1 = 0, math.huge, math.huge, -1, -1
  for y = 0, area.height - 1 do
    local s = y * stride + 1
    if bytes_a:sub(s, s + stride - 1) ~= bytes_b:sub(s, s + stride - 1) then
      for x = 0, area.width - 1 do
        local i = s + x * 4
        local r1, g1, b1, a1 = byte(bytes_a, i, i + 3)
        local r2, g2, b2, a2 = byte(bytes_b, i, i + 3)
        -- Two fully transparent pixels are the same whatever their RGB.
        if (a1 ~= 0 or a2 ~= 0) and (r1 ~= r2 or g1 ~= g2 or b1 ~= b2 or a1 ~= a2) then
          count = count + 1
          x0, y0 = math.min(x0, x), math.min(y0, y)
          x1, y1 = math.max(x1, x), math.max(y1, y)
        end
      end
    end
  end
  out.different_pixels = count
  if count > 0 then
    out.bounds = { x = area.x + x0, y = area.y + y0, w = x1 - x0 + 1, h = y1 - y0 + 1 }
  end
  return out
end

-- Ties in the colour ranking go by red, green, blue, then alpha.
local function rgba_order(v)
  return pc.rgbaR(v) << 24 | pc.rgbaG(v) << 16 | pc.rgbaB(v) << 8 | pc.rgbaA(v)
end

local function ranks_before(a, b)
  if a[2] ~= b[2] then
    return a[2] > b[2]
  end
  return rgba_order(a[1]) < rgba_order(b[1])
end

OPS.get_color_stats = function(ctx, p)
  local spr = need_sprite(ctx)
  local frame = one_frame(spr, p.frame)
  local top = p.top or 16
  local img = render(spr, frame, nil, spr.bounds)
  local counts, transparent, unique = {}, 0, 0
  -- Unpacking the RGBA bytes is faster than the pixel iterator and gives the same values.
  local bytes, unpack = img.bytes, string.unpack
  for i = 1, #bytes, 4 do
    local v = unpack("<I4", bytes, i)
    if v >> 24 == 0 then
      transparent = transparent + 1
    else
      local count = counts[v]
      if count == nil then
        unique = unique + 1
        -- One table entry per colour: a photo-like canvas would take gigabytes.
        if unique > p.max_unique then
          fail(string.format("frame %d has more than %d different colours, too many to "
            .. "count; extract_palette summarises such images", frame, p.max_unique))
        end
        count = 0
      end
      counts[v] = count + 1
    end
  end
  -- Keep only the best `top` entries, so a noisy image never sorts every colour.
  local best = {}
  for v, count in pairs(counts) do
    local entry = { v, count }
    if #best < top or ranks_before(entry, best[#best]) then
      local i = #best < top and #best + 1 or #best
      best[i] = entry
      while i > 1 and ranks_before(best[i], best[i - 1]) do
        best[i], best[i - 1] = best[i - 1], best[i]
        i = i - 1
      end
    end
  end
  return {
    frame = frame,
    pixels = img.width * img.height,
    transparent = transparent,
    unique = unique,
    colors = best,
  }
end

local NEIGHBOURS = {
  { -1, -1 }, { 0, -1 }, { 1, -1 },
  { -1, 0 }, { 1, 0 },
  { -1, 1 }, { 0, 1 }, { 1, 1 },
}
local SMALLEST_BODY = 4
local MAX_LISTED = 50

OPS.find_stray_pixels = function(ctx, p)
  local spr = need_sprite(ctx)
  local layer = optional_layer(spr, p.layer)
  local frame = one_frame(spr, p.frame)
  local img = render(spr, frame, layer, spr.bounds)
  local w, h = img.width, img.height
  -- Alpha is read straight from the RGBA bytes: far cheaper than getPixel per pixel.
  local bytes, byte = img.bytes, string.byte

  local function solid(x, y)
    return x >= 0 and y >= 0 and x < w and y < h and byte(bytes, (y * w + x) * 4 + 4) ~= 0
  end

  -- The 8-connected group around (x, y), or nil as soon as it reaches SMALLEST_BODY.
  local function small_group(x, y)
    local group, seen, i = { { x, y } }, { [y * w + x] = true }, 1
    while i <= #group do
      local gx, gy = group[i][1], group[i][2]
      for _, d in ipairs(NEIGHBOURS) do
        local nx, ny = gx + d[1], gy + d[2]
        local key = ny * w + nx
        if not seen[key] and solid(nx, ny) then
          seen[key] = true
          group[#group + 1] = { nx, ny }
          if #group >= SMALLEST_BODY then
            return nil
          end
        end
      end
      i = i + 1
    end
    return group
  end

  -- Solid neighbours of (x, y), counting stops at 3: a pixel in a group of at most
  -- three has at most two.
  local function neighbours(x, y)
    local n = 0
    for i = 1, 8 do
      local d = NEIGHBOURS[i]
      if solid(x + d[1], y + d[2]) then
        n = n + 1
        if n >= SMALLEST_BODY - 1 then
          return n
        end
      end
    end
    return n
  end

  -- Each group is reported once, from its first pixel in reading order.
  local function starts_group(group, x, y)
    for i = 2, #group do
      local q = group[i]
      if q[2] < y or (q[2] == y and q[1] < x) then
        return false
      end
    end
    return true
  end

  local lone, clusters, lone_count, cluster_count = {}, {}, 0, 0

  local function add_lone(x, y)
    lone_count = lone_count + 1
    if lone_count <= MAX_LISTED then
      lone[lone_count] = { x = x, y = y, color = img:getPixel(x, y) }
    end
  end

  local function add_cluster(group)
    cluster_count = cluster_count + 1
    if cluster_count > MAX_LISTED then
      return
    end
    table.sort(group, function(a, b)
      return a[2] < b[2] or (a[2] == b[2] and a[1] < b[1])
    end)
    local x0, y0, x1, y1 = w, h, -1, -1
    for _, q in ipairs(group) do
      x0, y0 = math.min(x0, q[1]), math.min(y0, q[2])
      x1, y1 = math.max(x1, q[1]), math.max(y1, q[2])
    end
    clusters[cluster_count] = {
      x = x0, y = y0, w = x1 - x0 + 1, h = y1 - y0 + 1, size = #group, pixels = group,
    }
  end

  for y = 0, h - 1 do
    for x = 0, w - 1 do
      -- A solid neighbour on the left or above means the group was met already, which
      -- rules out most pixels of a shape after one or two reads.
      if byte(bytes, (y * w + x) * 4 + 4) ~= 0
          and not solid(x - 1, y) and not solid(x - 1, y - 1)
          and not solid(x, y - 1) and not solid(x + 1, y - 1) then
        local n = neighbours(x, y)
        if n == 0 then
          add_lone(x, y)
        elseif n < SMALLEST_BODY - 1 then
          local group = small_group(x, y)
          if group ~= nil and starts_group(group, x, y) then
            add_cluster(group)
          end
        end
      end
    end
  end
  return {
    frame = frame,
    lone_pixels = lone,
    lone_pixel_count = lone_count,
    small_clusters = clusters,
    small_cluster_count = cluster_count,
  }
end

OPS.render_frames = function(ctx, p)
  local spr = need_sprite(ctx)
  local layer = optional_layer(spr, p.layer)
  local frames = frame_list(spr, p.frames)
  if #frames > p.max_frames then
    fail(string.format("%d frames requested; view_sprite shows at most %d at once, "
      .. "pass a range such as \"1-%d\"", #frames, p.max_frames, p.max_frames))
  end
  local area = area_of(spr, p.region)
  local wanted, rendered, count = {}, {}, 0
  for _, n in ipairs(frames) do
    for k = math.max(1, n - (p.onion_skin or 0)), n do
      if not wanted[k] then
        wanted[k] = true
        count = count + 1
      end
    end
  end
  if count * area.width * area.height > p.max_pixels then
    fail(string.format("rendering %s of %dx%d px is too much for one view; "
      .. "pass a region or fewer frames", plural(count, "frame"), area.width, area.height))
  end
  local buffer = rgb_image(area.width, area.height)
  for n = 1, #spr.frames do
    if wanted[n] then
      render(spr, n, layer, area, buffer):saveAs(app.fs.joinPath(p.dir, n .. ".png"))
      table.insert(rendered, n)
    end
  end
  return {
    frames = frames,
    rendered = rendered,
    area = rect_table(area),
    frame_count = #spr.frames,
  }
end
