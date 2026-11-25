-- Export and import ops. Exports never change the sprite: files are written into the
-- temporary folder p.dir under names the server chose, and the server moves them to
-- their final place. Layer visibility is switched for rendering and always restored.

local pc = app.pixelColor

local SHEET_TYPES = {
  horizontal = SpriteSheetType.HORIZONTAL,
  vertical = SpriteSheetType.VERTICAL,
  rows = SpriteSheetType.ROWS,
  columns = SpriteSheetType.COLUMNS,
  packed = SpriteSheetType.PACKED,
}

local DATA_FORMATS = {
  hash = SpriteSheetDataFormat.JSON_HASH,
  array = SpriteSheetDataFormat.JSON_ARRAY,
}

local function need_tag(spr, name)
  local tag = find_tag(spr, name)
  if tag ~= nil then
    return tag
  end
  local known = {}
  for _, t in ipairs(spr.tags) do
    table.insert(known, "'" .. t.name .. "'")
  end
  local hint = #known > 0 and ("; tags: " .. table.concat(known, ", ")) or "; the sprite has no tags"
  fail("tag '" .. name .. "' not found" .. hint)
end

local function tag_frames(tag)
  local out = {}
  for n = tag.fromFrame.frameNumber, tag.toFrame.frameNumber do
    table.insert(out, n)
  end
  return out
end

-- Runs fn with only `layer` showing: it and its groups are made visible, layers
-- inside it keep their own visibility, every other layer is hidden.
local function with_only(spr, layer, fn)
  local saved = {}
  for _, other in ipairs(all_layers(spr)) do
    saved[other] = other.isVisible
    if other == layer or is_inside(spr, layer, other) then
      other.isVisible = true
    elseif not is_inside(spr, other, layer) then
      other.isVisible = false
    end
  end
  local ok, err = pcall(fn)
  for other, visible in pairs(saved) do
    other.isVisible = visible
  end
  if not ok then
    error(err, 0)
  end
end

local function check_size(count, w, h, limit, what)
  if count * w * h > limit then
    fail(string.format("%s would be %d frame(s) of %dx%d px, too large (at most %d pixels "
      .. "per export, all frames counted); use a smaller scale or fewer frames",
      what, count, w, h, limit))
  end
end

-- Renders frames of the visible composite (or of one layer shown alone) over an
-- optional background colour, scaled up nearest-neighbour. emit(n, image) gets
-- each frame; the image is reused for the next one.
local function render_frames(spr, frames, p, emit)
  local layer = p.layer and get_layer(spr, p.layer)
  local w, h, scale = spr.width, spr.height, p.scale or 1
  local buffer = Image(ImageSpec { width = w, height = h, colorMode = ColorMode.RGB })
  local canvas = buffer
  if p.background then
    canvas = Image(buffer.spec)
  end
  local bg = p.background and pc.rgba(table.unpack(p.background))

  local function draw()
    for _, n in ipairs(frames) do
      buffer:clear()
      buffer:drawSprite(spr, n, Point(0, 0))
      if bg then
        canvas:clear(bg)
        canvas:drawImage(buffer, Point(0, 0), 255, BlendMode.NORMAL)
      end
      if scale > 1 then
        local big = canvas:clone()
        big:resize(w * scale, h * scale)
        emit(n, big)
        big = nil
        -- Lua does not see image memory, so free each scaled copy right away.
        collectgarbage()
      else
        emit(n, canvas)
      end
    end
  end

  if layer then
    with_only(spr, layer, draw)
  else
    draw()
  end
end

OPS.export_frames = function(ctx, p)
  local spr = need_sprite(ctx)
  local frames
  if p.tag then
    frames = tag_frames(need_tag(spr, p.tag))
  else
    frames = frame_list(spr, p.frames)
  end
  local scale = p.scale or 1
  local w, h = spr.width * scale, spr.height * scale
  local files = {}

  if p.animated then
    check_size(#frames, w, h, p.max_pixels, "the animation")
    local out = Sprite(w, h, ColorMode.RGB)
    local ok, err = pcall(function()
      local target = out.layers[1]
      for i, n in ipairs(frames) do
        if i > 1 then
          out:newEmptyFrame()
        end
        out.frames[i].duration = spr.frames[n].duration
      end
      local i = 0
      render_frames(spr, frames, p, function(_, image)
        i = i + 1
        put_cel(out, target, i, image:clone(), Point(0, 0))
      end)
      local name = "animation." .. p.ext
      out:saveCopyAs(app.fs.joinPath(p.dir, name))
      files[1] = name
    end)
    out:close()
    app.sprite = spr
    if not ok then
      error(err, 0)
    end
  else
    check_size(#frames, w, h, p.max_pixels, "the export")
    render_frames(spr, frames, p, function(n, image)
      local name = n .. "." .. p.ext
      image:saveAs(app.fs.joinPath(p.dir, name))
      table.insert(files, name)
    end)
  end
  return { frames = frames, files = files, width = w, height = h }
end

OPS.export_sheet = function(ctx, p)
  local spr = need_sprite(ctx)
  local count = #spr.frames
  if p.tag then
    count = #tag_frames(need_tag(spr, p.tag))
  end
  local scale = p.scale or 1
  check_size(count, spr.width * scale, spr.height * scale, p.max_pixels, "the sheet")

  -- Exported from an unsaved copy: the exporter stores its settings with the document,
  -- and for a document with a file name they end up as an .ini in the user's
  -- Aseprite config folder. The copy is also where scaling happens, which the
  -- exporter has no option for.
  local source = Sprite(spr)
  if scale > 1 then
    source:resize(spr.width * scale, spr.height * scale)
  end
  local args = {
    ui = false,
    askOverwrite = false,
    openGenerated = false,
    type = SHEET_TYPES[p.sheet_type],
    textureFilename = p.texture,
    shapePadding = p.padding or 0,
    tag = p.tag,
    listTags = true,
  }
  if p.data then
    args.dataFilename = p.data
    args.dataFormat = DATA_FORMATS[p.data_format]
  end
  app.sprite = source
  local ok, err = pcall(app.command.ExportSpriteSheet, args)
  source:close()
  app.sprite = spr
  if not ok then
    error(err, 0)
  end
  if not app.fs.isFile(p.texture) or (p.data and not app.fs.isFile(p.data)) then
    fail("Aseprite did not write the sprite sheet")
  end
  return { frame_count = count }
end

OPS.export_layers = function(ctx, p)
  local spr = need_sprite(ctx)
  local frame = one_frame(spr, p.frame)
  local buffer = Image(ImageSpec { width = spr.width, height = spr.height, colorMode = ColorMode.RGB })
  local layers, hidden = {}, {}
  for _, layer in ipairs(cel_layers(spr)) do
    local path = layer_path(layer)
    if not p.include_hidden and not layer_shown(spr, layer) then
      table.insert(hidden, path)
    else
      with_only(spr, layer, function()
        buffer:clear()
        buffer:drawSprite(spr, frame, Point(0, 0))
      end)
      local name = (#layers + 1) .. ".png"
      buffer:saveAs(app.fs.joinPath(p.dir, name))
      table.insert(layers, { layer = path, file = name })
    end
  end
  return { frame = frame, layers = layers, hidden = hidden }
end

-- p.image is a PNG the server converted to RGBA; p.opaque counts its non-transparent
-- pixels. Its pixels
-- are drawn over the cel (transparent ones leave what is there); indexed sprites get
-- the nearest palette entries, grayscale ones the luma. Pixels go through byte
-- strings: per-pixel Image calls take minutes on large images.
OPS.import_image = function(ctx, p)
  local spr = need_sprite(ctx)
  local layer, path = image_layer(spr, p.layer)
  require_editable(layer)
  local frame = one_frame(spr, p.frame)
  local src = Image { fromFile = p.image }
  if src == nil or src.colorMode ~= ColorMode.RGB then
    fail("could not load the converted image")
  end
  local x, y = p.x or 0, p.y or 0
  local area = Rectangle(x, y, src.width, src.height):intersect(spr.bounds)
  if area.isEmpty then
    fail(string.format("the %dx%d image at (%d, %d) is outside the canvas (%d x %d)",
      src.width, src.height, x, y, spr.width, spr.height))
  end
  local mode = spr.colorMode

  local part = Image(src, Rectangle(area.x - x, area.y - y, area.width, area.height))
  local bytes, byte, char = part.bytes, string.byte, string.char
  local placed = 0
  for i = 4, #bytes, 4 do
    if byte(bytes, i) ~= 0 then
      placed = placed + 1
    end
  end
  local result = {
    layer = path, frame = frame, x = x, y = y, width = src.width, height = src.height,
    placed = placed, clipped = p.opaque - placed,
  }
  if placed == 0 then
    ctx.changed = false
    return result
  end

  local cel = layer:cel(frame)
  if cel ~= nil then
    own_cel(spr, layer, cel, image_users(layer))
  end
  cel = ensure_cel_bounds(spr, layer, frame, area)
  local at = Point(area.x - cel.position.x, area.y - cel.position.y)
  if mode == ColorMode.RGB then
    cel.image:drawImage(part, at, 255, BlendMode.NORMAL)
    return result
  end

  local map = color_mapper(spr, layer, p.max_palette_work)
  local patch, old
  if mode == ColorMode.INDEXED then
    -- Indices cannot blend, and on a background layer the transparent index is an
    -- opaque colour drawImage would skip; so the patch starts as a copy of the cel and
    -- replaces it whole.
    patch = Image(cel.image, Rectangle(at.x, at.y, area.width, area.height))
    old = patch.bytes
  else
    patch = Image(ImageSpec { width = area.width, height = area.height, colorMode = mode })
  end
  local w, rows = area.width, {}
  for row = 0, area.height - 1 do
    local out = {}
    for col = 0, w - 1 do
      local i = (row * w + col) * 4 + 1
      local r, g, b, a = byte(bytes, i, i + 3)
      if mode == ColorMode.INDEXED then
        out[col + 1] = a == 0 and old:sub(row * w + col + 1, row * w + col + 1)
          or char(map(r, g, b, a))
      elseif a == 0 then
        out[col + 1] = "\0\0"
      else
        local v = map(r, g, b, a)
        out[col + 1] = char(v & 255, v >> 8 & 255)
      end
    end
    rows[row + 1] = table.concat(out)
  end
  patch.bytes = table.concat(rows)
  local blend = mode == ColorMode.INDEXED and BlendMode.SRC or BlendMode.NORMAL
  cel.image:drawImage(patch, at, 255, blend)
  return result
end
