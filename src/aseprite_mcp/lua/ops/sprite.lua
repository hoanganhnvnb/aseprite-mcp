local MODE_NAMES = {
  [ColorMode.RGB] = "rgb",
  [ColorMode.GRAY] = "grayscale",
  [ColorMode.INDEXED] = "indexed",
}

local BLEND_NAMES = {
  [BlendMode.NORMAL] = "normal",
  [BlendMode.MULTIPLY] = "multiply",
  [BlendMode.SCREEN] = "screen",
  [BlendMode.OVERLAY] = "overlay",
  [BlendMode.DARKEN] = "darken",
  [BlendMode.LIGHTEN] = "lighten",
  [BlendMode.COLOR_DODGE] = "color_dodge",
  [BlendMode.COLOR_BURN] = "color_burn",
  [BlendMode.HARD_LIGHT] = "hard_light",
  [BlendMode.SOFT_LIGHT] = "soft_light",
  [BlendMode.DIFFERENCE] = "difference",
  [BlendMode.EXCLUSION] = "exclusion",
  [BlendMode.HSL_HUE] = "hue",
  [BlendMode.HSL_SATURATION] = "saturation",
  [BlendMode.HSL_COLOR] = "color",
  [BlendMode.HSL_LUMINOSITY] = "luminosity",
  [BlendMode.ADDITION] = "addition",
  [BlendMode.SUBTRACT] = "subtract",
  [BlendMode.DIVIDE] = "divide",
}

local DIRECTION_NAMES = {
  [AniDir.FORWARD] = "forward",
  [AniDir.REVERSE] = "reverse",
  [AniDir.PING_PONG] = "ping_pong",
  [AniDir.PING_PONG_REVERSE] = "ping_pong_reverse",
}

local function layer_type(layer)
  if layer.isGroup then
    return "group"
  elseif layer.isTilemap then
    return "tilemap"
  end
  return "normal"
end

local function layer_tree(layers, prefix)
  local out = {}
  for _, layer in ipairs(layers) do
    local path = prefix and (prefix .. "/" .. layer.name) or layer.name
    table.insert(out, {
      name = layer.name,
      path = path,
      type = layer_type(layer),
      visible = layer.isVisible,
      is_background = layer.isBackground,
      opacity = layer.opacity,
      blend_mode = BLEND_NAMES[layer.blendMode] or "normal",
      children = layer.isGroup and layer_tree(layer.layers, path) or {},
    })
  end
  return out
end

OPS.sprite_info = function(ctx)
  local spr = need_sprite(ctx)
  local frames = {}
  for i, frame in ipairs(spr.frames) do
    frames[i] = { index = i, duration_ms = math.floor(frame.duration * 1000 + 0.5) }
  end
  local tags = {}
  for i, tag in ipairs(spr.tags) do
    tags[i] = {
      name = tag.name,
      from_frame = tag.fromFrame.frameNumber,
      to_frame = tag.toFrame.frameNumber,
      direction = DIRECTION_NAMES[tag.aniDir] or "forward",
      repeats = tag.repeats,
    }
  end
  return {
    width = spr.width,
    height = spr.height,
    color_mode = MODE_NAMES[spr.colorMode] or "unknown",
    frames = frames,
    layers = layer_tree(spr.layers, nil),
    tags = tags,
    slice_count = #spr.slices,
    palette_size = #spr.palettes[1],
  }
end

-- Version probe for the doctor command; "fail" and "crash" exercise both error
-- paths and "echo" comes back as decoded, to check parameter passing.
OPS._ping = function(_, p)
  if p.fail then
    fail(p.fail)
  end
  if p.crash then
    local missing = nil
    return missing.field
  end
  return { api = app.apiVersion, version = tostring(app.version), echo = p.echo }
end
