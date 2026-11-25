-- Entry point: aseprite --batch --script-param params=<json file> --script main.lua
-- Every value arrives through the params JSON file; nothing is spliced into Lua source.

local P
local result_written = false

local function write_result(data)
  local fh = assert(io.open(P.result_path, "wb"))
  fh:write(json.encode(data))
  fh:close()
  result_written = true
end

local function read_file(path)
  local fh, err = io.open(path, "rb")
  if not fh then
    error(err, 0)
  end
  local text = fh:read("a")
  fh:close()
  return text
end

-- json.decode returns userdata proxies with float numbers; they cannot be nested
-- in tables handed back to json.encode, so copy them into plain Lua values.
local function plain(value)
  local kind = type(value)
  if kind == "number" then
    -- math.tointeger truncates fractions in this Lua build, so check integrality first.
    if math.type(value) == "float" and value == math.floor(value)
        and value >= math.mininteger and value <= math.maxinteger then
      return math.floor(value)
    end
    return value
  end
  if kind ~= "userdata" then
    return value
  end
  local out, has_keys = {}, false
  for k, v in pairs(value) do
    out[k] = plain(v)
    has_keys = true
  end
  if not has_keys then
    -- pairs() yields nothing for arrays
    for i = 1, #value do
      out[i] = plain(value[i])
    end
  end
  return out
end

-- Named chunks make errors read "ops/sprite.lua:12: ..." regardless of install path.
local function load_chunk(rel)
  local chunk, err = load(read_file(P.lua_dir .. "/" .. rel), "@" .. rel, "t", _ENV)
  if not chunk then
    error(err)
  end
  chunk()
end

local COLOR_MODES = {
  rgb = ColorMode.RGB,
  grayscale = ColorMode.GRAY,
  gray = ColorMode.GRAY,
  indexed = ColorMode.INDEXED,
}

local function create_sprite(spec)
  local mode = COLOR_MODES[spec.color_mode or "rgb"]
  if mode == nil then
    fail("unknown color mode '" .. tostring(spec.color_mode) .. "' (use rgb, grayscale or indexed)")
  end
  local w, h = spec.width, spec.height
  if math.type(w) ~= "integer" or math.type(h) ~= "integer" or w < 1 or h < 1 then
    fail("sprite width and height must be positive integers")
  end
  local frames = spec.frames or 1
  if math.type(frames) ~= "integer" or frames < 1 then
    fail("frame count must be a positive integer")
  end
  local spr = Sprite(ImageSpec { width = w, height = h, colorMode = mode })
  set_default_palette(spr)
  for _ = 2, frames do
    spr:newEmptyFrame()
  end
  for i, name in ipairs(spec.layers or {}) do
    local layer = spr.layers[i] or spr:newLayer()
    layer.name = name
  end
  if spec.background then
    local layer = spr.layers[1]
    for _, frame in ipairs(spr.frames) do
      local cel = layer:cel(frame) or spr:newCel(layer, frame)
      cel.image:clear(color_value(spr, spec.background, layer))
    end
  end
  return spr
end

local function error_text(err)
  if type(err) == "table" and err.user ~= nil then
    return tostring(err.user)
  end
  return tostring(err)
end

-- The frames below the op are this file's plumbing; keep only the op's own stack.
local function op_traceback(err)
  if type(err) == "table" and err.user ~= nil then
    return err
  end
  local text = debug.traceback(tostring(err), 2)
  local cut = text:find("\n\t%[C%]: in function 'xpcall'")
  return cut and text:sub(1, cut - 1) or text
end

local function run_ops(ctx, ops)
  local results = {}
  for i, op in ipairs(ops) do
    local fn = OPS[op.name]
    if fn == nil then
      error({ op_index = i, message = "unknown op '" .. tostring(op.name) .. "'" })
    end
    -- A mutating op that turns out to change nothing sets ctx.changed = false, so a
    -- run made only of such ops leaves the file untouched.
    ctx.changed = nil
    local ok, res = xpcall(fn, op_traceback, ctx, op.params or {})
    op.unchanged = ctx.changed == false
    if not ok then
      local message = error_text(res)
      if #ops > 1 then
        message = string.format("op %d (%s): %s", i, op.label or op.name, message)
      end
      error({ op_index = i, message = message })
    end
    results[i] = res == nil and {} or res
  end
  return results
end

local function main()
  P = plain(json.decode(read_file(app.params.params)))
  load_chunk("prelude.lua")
  for _, name in ipairs(P.op_files or {}) do
    load_chunk("ops/" .. name)
  end

  local spr
  if P.create then
    spr = create_sprite(P.create)
  elseif P.open_file then
    spr = open_sprite(P.open_file)
  end
  local ctx = { spr = spr, params = P }
  local ops = P.ops or {}

  local results
  local ok, err = pcall(function()
    if spr then
      app.transaction("aseprite-mcp", function()
        results = run_ops(ctx, ops)
      end)
    else
      results = run_ops(ctx, ops)
    end
  end)
  if not ok then
    if type(err) == "table" and err.op_index then
      write_result({ ok = false, error = err.message, op_index = err.op_index })
      return
    end
    error(err, 0)
  end

  local saved = false
  if P.save_tmp and spr then
    local mutated = P.create ~= nil
    for _, op in ipairs(ops) do
      mutated = mutated or (op.mutates == true and not op.unchanged)
    end
    if mutated then
      check_save_format(spr, P.target)
      spr:saveCopyAs(P.save_tmp)
      saved = true
    end
  end
  write_result({ ok = true, results = results, saved = saved })
end

local ok, err = xpcall(main, function(e)
  if type(e) == "table" and e.user ~= nil then
    return e
  end
  return debug.traceback(tostring(e), 2)
end)
if not ok and P and P.result_path and not result_written then
  write_result({ ok = false, error = error_text(err) })
elseif not ok then
  error(error_text(err), 0)
end
