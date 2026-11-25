-- Checks for the ordered dither matrices in the prelude. Run by test_runtime.py.

local fh = assert(io.open(app.params.params, "rb"))
local P = json.decode(fh:read("a"))
fh:close()

local failures = {}
local checks = 0

local function check(name, cond)
  checks = checks + 1
  if not cond then
    table.insert(failures, name)
  end
end

local function rows_equal(m, expected)
  for y, row in ipairs(expected) do
    for x, v in ipairs(row) do
      if m[y][x] ~= v then
        return false
      end
    end
  end
  return #m == #expected
end

local function run()
  dofile(P.lua_dir .. "/prelude.lua")

  check("bayer2", rows_equal(bayer(2), { { 0, 2 }, { 3, 1 } }))
  check("bayer4", rows_equal(bayer(4), {
    { 0, 8, 2, 10 },
    { 12, 4, 14, 6 },
    { 3, 11, 1, 9 },
    { 15, 7, 13, 5 },
  }))
  local b8 = bayer(8)
  check("bayer8 first row", rows_equal({ b8[1] }, { { 0, 32, 8, 40, 2, 34, 10, 42 } }))
  check("bayer8 last row", b8[8][1] == 63 and b8[8][8] == 21)

  for _, n in ipairs({ 2, 4, 8 }) do
    local seen, count = {}, 0
    for y = 1, n do
      for x = 1, n do
        local v = bayer(n)[y][x]
        if math.type(v) == "integer" and v >= 0 and v < n * n and not seen[v] then
          seen[v] = true
          count = count + 1
        end
      end
    end
    check("bayer" .. n .. " holds each value once", count == n * n)

    local low, high = 1, 0
    for y = 0, n - 1 do
      for x = 0, n - 1 do
        local t = bayer_threshold(n, x, y)
        low, high = math.min(low, t), math.max(high, t)
      end
    end
    check("bayer" .. n .. " thresholds inside (0, 1)", low == 0.5 / (n * n)
      and high == (n * n - 0.5) / (n * n))
  end

  check("threshold normalised", bayer_threshold(4, 1, 0) == 8.5 / 16)
  check("threshold wraps", bayer_threshold(4, 5, 4) == bayer_threshold(4, 1, 0))
  check("threshold wraps below zero", bayer_threshold(4, -1, -1) == 5.5 / 16)
  check("rejects sizes that are not powers of two", not pcall(bayer, 3))
end

local ok, err = xpcall(run, debug.traceback)
if not ok then
  table.insert(failures, tostring(type(err) == "table" and err.user or err))
end
local out = assert(io.open(P.result_path, "wb"))
if #failures > 0 then
  out:write(json.encode({ ok = false, error = "bayer checks failed: " .. table.concat(failures, "; ") }))
else
  out:write(json.encode({ ok = true, checks = checks }))
end
out:close()
