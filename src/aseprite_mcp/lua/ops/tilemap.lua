local pc = app.pixelColor

-- Flag bits Aseprite keeps above the tile index.
local FLAGS = { { 0x80000000, "flip_x" }, { 0x40000000, "flip_y" }, { 0x20000000, "diagonal" } }

local function tilemap_layer(spr, name)
  local layer = get_layer(spr, name)
  if not layer.isTilemap then
    fail("'" .. layer_path(layer) .. "' is not a tilemap layer")
  end
  return layer
end

local function cells_over(length, origin, size)
  return math.max(0, (length - origin + size - 1) // size)
end

-- The layer's own tileset grid; the sprite grid may belong to another tilemap.
local function grid_of(spr, layer)
  local grid = layer.tileset.grid
  local tw, th = grid.tileSize.width, grid.tileSize.height
  local ox, oy = grid.origin.x, grid.origin.y
  return {
    tw = tw,
    th = th,
    ox = ox,
    oy = oy,
    cols = cells_over(spr.width, ox, tw),
    rows = cells_over(spr.height, oy, th),
  }
end

-- The cel in frame n and its first cell, or nil when there is none.
local function tile_cel(layer, n, g)
  local cel = layer:cel(n)
  if cel == nil then
    return nil
  end
  local dx, dy = cel.position.x - g.ox, cel.position.y - g.oy
  if dx % g.tw ~= 0 or dy % g.th ~= 0 then
    fail(string.format("the cel of '%s' in frame %d sits at (%d, %d), off the %dx%d grid; "
      .. "move it to a multiple of the tile size first", layer_path(layer), n,
      cel.position.x, cel.position.y, g.tw, g.th))
  end
  return cel, dx // g.tw, dy // g.th
end

local function tile_word(n)
  return n == 1 and "1 tile" or (n .. " tiles")
end

OPS.get_tilemap_info = function(ctx, p)
  local spr = need_sprite(ctx)
  local layer = tilemap_layer(spr, p.layer)
  local n = one_frame(spr, p.frame)
  local g = grid_of(spr, layer)
  local region = p.rect or { x = 0, y = 0, w = g.cols, h = g.rows }
  if region.w * region.h > p.max_cells then
    fail(string.format("the grid has %d cells; pass rect to read at most %d per call",
      region.w * region.h, p.max_cells))
  end
  local cel, c0, r0 = tile_cel(layer, n, g)
  local img = cel and cel.image
  local tiles, flags = {}, {}
  for row = region.y, region.y + region.h - 1 do
    local line = {}
    for col = region.x, region.x + region.w - 1 do
      local value = 0
      if img then
        local x, y = col - c0, row - r0
        if x >= 0 and y >= 0 and x < img.width and y < img.height then
          value = img:getPixel(x, y)
        end
      end
      table.insert(line, pc.tileI(value))
      local bits = pc.tileF(value)
      if bits ~= 0 then
        local names = {}
        for _, flag in ipairs(FLAGS) do
          if bits & flag[1] ~= 0 then
            table.insert(names, flag[2])
          end
        end
        table.insert(flags, { col = col, row = row, flags = names })
      end
    end
    table.insert(tiles, line)
  end
  return {
    layer = layer_path(layer),
    tile_size = { w = g.tw, h = g.th },
    origin = { x = g.ox, y = g.oy },
    tile_count = #layer.tileset,
    grid = { columns = g.cols, rows = g.rows },
    cel = cel and { col = c0, row = r0, columns = img.width, rows = img.height } or nil,
    region = { col = region.x, row = region.y, columns = region.w, rows = region.h },
    tiles = tiles,
    flags = flags,
  }
end

OPS.draw_tile = function(ctx, p)
  local spr = need_sprite(ctx)
  local layer = tilemap_layer(spr, p.layer)
  require_editable(layer)
  local tileset = layer.tileset
  local g = grid_of(spr, layer)
  local count = #tileset
  if p.tile_index > count then
    fail(string.format("tile index %d is out of range: the tileset has %s (pass %d to add one)",
      p.tile_index, tile_word(count), count))
  end
  for _, px in ipairs(p.pixels) do
    if px[1] < 0 or px[2] < 0 or px[1] >= g.tw or px[2] >= g.th then
      fail(string.format("pixel (%d, %d) is outside the %dx%d tile", px[1], px[2], g.tw, g.th))
    end
  end
  if p.tile_index == count then
    spr:newTile(tileset)
  end
  local img = tileset:getTile(p.tile_index):clone()
  for _, px in ipairs(p.pixels) do
    img:drawPixel(px[1], px[2], color_value(spr, { px[3], px[4], px[5], px[6] }))
  end
  tileset:tile(p.tile_index).image = img
  return {
    layer = layer_path(layer),
    tile_index = p.tile_index,
    tile_count = #tileset,
    painted = #p.pixels,
  }
end

OPS.set_tiles = function(ctx, p)
  local spr = need_sprite(ctx)
  local layer = tilemap_layer(spr, p.layer)
  require_editable(layer)
  local n = one_frame(spr, p.frame)
  local g = grid_of(spr, layer)
  local count = #layer.tileset
  local c0, r0, c1, r1 = math.huge, math.huge, -1, -1
  for _, t in ipairs(p.tiles) do
    local col, row, index = t[1], t[2], t[3]
    if col >= g.cols or row >= g.rows then
      fail(string.format("cell (%d, %d) is outside the %dx%d grid", col, row, g.cols, g.rows))
    end
    if index >= count then
      fail(string.format("tile index %d is out of range: the tileset has %s", index,
        tile_word(count)))
    end
    c0, r0 = math.min(c0, col), math.min(r0, row)
    c1, r1 = math.max(c1, col), math.max(r1, row)
  end

  local old, oc, orow = tile_cel(layer, n, g)
  local props
  if old ~= nil then
    c0, r0 = math.min(c0, oc), math.min(r0, orow)
    c1 = math.max(c1, oc + old.image.width - 1)
    r1 = math.max(r1, orow + old.image.height - 1)
    props = cel_props(old)
  end
  local img = Image(ImageSpec {
    width = c1 - c0 + 1,
    height = r1 - r0 + 1,
    colorMode = ColorMode.TILEMAP,
  })
  img:clear(0)
  if old ~= nil then
    img:drawImage(old.image, Point(oc - c0, orow - r0), 255, BlendMode.SRC)
  end
  for _, t in ipairs(p.tiles) do
    img:drawPixel(t[1] - c0, t[2] - r0, t[3])
  end
  -- A new cel instead of writing into the old one, which may be linked to other frames.
  put_cel(spr, layer, n, img, Point(g.ox + c0 * g.tw, g.oy + r0 * g.th), props)
  return {
    layer = layer_path(layer),
    frame = n,
    set = #p.tiles,
    cel = { col = c0, row = r0, columns = img.width, rows = img.height },
  }
end
