-- run_lua: a caller-supplied script, loaded from the params as a string.

local OUTPUT_LIMIT = 65536
local RESULT_LIMIT = 1024 * 1024
local ERROR_LIMIT = 4096
local ERROR_OUTPUT_TAIL = 2048

local function is_continuation(s, i)
  local b = s:byte(i)
  return b ~= nil and b >= 0x80 and b < 0xC0
end

-- Cuts never split a UTF-8 sequence, or the result file would not decode.
local function utf8_head(s, n)
  while n > 0 and is_continuation(s, n + 1) do
    n = n - 1
  end
  return s:sub(1, n)
end

local function utf8_tail(s, n)
  local start = math.max(1, #s - n + 1)
  while is_continuation(s, start) do
    start = start + 1
  end
  return s:sub(start)
end

-- Script text may hold any bytes. Invalid UTF-8 becomes U+FFFD and NUL becomes
-- "\0", which json.encode would otherwise end the string at.
local function clean_text(s)
  if s:find("%z") then
    s = s:gsub("%z", "\\0")
  end
  if utf8.len(s) then
    return s
  end
  local parts, i = {}, 1
  while i <= #s do
    local _, bad = utf8.len(s, i)
    if not bad then
      parts[#parts + 1] = s:sub(i)
      break
    end
    parts[#parts + 1] = s:sub(i, bad - 1) .. "\u{FFFD}"
    i = bad + 1
  end
  return table.concat(parts)
end

local function clip_middle(s, limit)
  if #s <= limit then
    return s
  end
  local half = limit // 2
  return utf8_head(s, half) .. "\n... (" .. (#s - limit) .. " bytes cut) ...\n"
    .. utf8_tail(s, half)
end

local function output_buffer()
  local parts, size, truncated = {}, 0, false
  local buffer = {}

  function buffer.print(...)
    if truncated then
      return
    end
    local n = select("#", ...)
    local pieces = {}
    for i = 1, n do
      pieces[i] = tostring((select(i, ...)))
    end
    local line = clean_text(table.concat(pieces, "\t") .. "\n")
    if size + #line > OUTPUT_LIMIT then
      line = utf8_head(line, OUTPUT_LIMIT - size)
      truncated = true
    end
    parts[#parts + 1] = line
    size = size + #line
  end

  function buffer.text()
    return table.concat(parts), truncated
  end

  return buffer
end

local function is_array(t)
  local n = 0
  for k in pairs(t) do
    if math.type(k) ~= "integer" or k < 1 then
      return false
    end
    n = n + 1
  end
  return n == #t
end

-- Anything json.encode would choke on (functions, userdata, NaN, sparse or mixed
-- tables, bad bytes) becomes text or a string-keyed table, so a return value never
-- fails late.
local function to_json(value, seen)
  local kind = type(value)
  if kind == "nil" or kind == "boolean" then
    return value
  end
  if kind == "string" then
    return clean_text(value)
  end
  if kind == "number" then
    if value ~= value or value == math.huge or value == -math.huge then
      return tostring(value)
    end
    return value
  end
  if kind ~= "table" then
    return clean_text(tostring(value))
  end
  if seen[value] then
    fail("the return value refers to itself")
  end
  seen[value] = true
  local out = {}
  if is_array(value) then
    for i = 1, #value do
      out[i] = to_json(value[i], seen)
    end
  else
    for k, v in pairs(value) do
      out[clean_text(tostring(k))] = to_json(v, seen)
    end
  end
  seen[value] = nil
  return out
end

local function describe_error(err)
  if type(err) == "string" then
    return err
  end
  local mt = getmetatable(err)
  if type(mt) == "table" and mt.__tostring ~= nil then
    local ok, text = pcall(tostring, err)
    if ok and type(text) == "string" then
      return text
    end
  end
  if type(err) == "table" and err.user ~= nil then
    return tostring(err.user)
  end
  local ok, encoded = pcall(function()
    return json.encode(to_json(err, {}))
  end)
  return "script raised a " .. type(err) .. " error value: " .. (ok and encoded or tostring(err))
end

local function traceback(e)
  local text = describe_error(e)
  if type(e) ~= "string" then
    return text
  end
  -- Keep the script's own frames; the rest is this file and main.lua.
  local trace = debug.traceback(text, 2)
  local cut = trace:find("\n%s*%[C%]: in function 'xpcall'")
  return cut and trace:sub(1, cut - 1) or trace
end

OPS.run_lua = function(ctx, p)
  local out = output_buffer()
  local env = setmetatable({ print = out.print, sprite = ctx.spr }, { __index = _ENV })
  local chunk, err = load(p.script, "=run_lua", "t", env)
  if not chunk then
    fail("syntax error: " .. clip_middle(clean_text(err), ERROR_LIMIT))
  end

  local ok, value = xpcall(chunk, traceback)
  local output, truncated = out.text()
  if not ok then
    local message = clip_middle(clean_text(value), ERROR_LIMIT)
    if output ~= "" then
      message = message .. "\nOutput before the error:\n" .. utf8_tail(output, ERROR_OUTPUT_TAIL)
    end
    fail(message)
  end

  local result = to_json(value, {})
  if result ~= nil then
    -- Wrapped, since a bare string or number is not a JSON document for json.encode.
    local size = #json.encode({ result }) - 2
    if size > RESULT_LIMIT then
      fail(string.format("the return value is too large (%d bytes of JSON, limit %d)",
        size, RESULT_LIMIT))
    end
  end
  return { output = output, truncated = truncated, result = result }
end
