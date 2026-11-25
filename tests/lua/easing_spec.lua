-- Checks for the easing functions and rounding in the prelude. Run by test_runtime.py.

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

local function near(a, b)
  return math.abs(a - b) < 1e-9
end

local function monotonic(ease)
  local last = ease(0)
  for i = 1, 100 do
    local v = ease(i / 100)
    if v < last then
      return false
    end
    last = v
  end
  return true
end

local function run()
  dofile(P.lua_dir .. "/prelude.lua")

  local names = { "linear", "ease_in", "ease_out", "ease_in_out", "ease_out_back", "bounce" }
  for _, name in ipairs(names) do
    local ease = EASINGS[name]
    check(name .. " exists", ease ~= nil)
    if ease then
      check(name .. " starts at 0", near(ease(0), 0))
      check(name .. " ends at 1", near(ease(1), 1))
    end
  end
  check("easing names", #names == 6)

  for _, name in ipairs({ "linear", "ease_in", "ease_out", "ease_in_out" }) do
    check(name .. " never goes back", monotonic(EASINGS[name]))
  end
  check("linear midpoint", near(EASINGS.linear(0.5), 0.5))
  check("ease_in is t squared", near(EASINGS.ease_in(0.5), 0.25))
  check("ease_out mirrors ease_in", near(EASINGS.ease_out(0.5), 0.75))
  check("ease_in_out midpoint", near(EASINGS.ease_in_out(0.5), 0.5))
  check("ease_in_out slow start", EASINGS.ease_in_out(0.25) < 0.25)
  check("ease_in_out slow end", EASINGS.ease_in_out(0.75) > 0.75)

  local peak = 0
  for i = 0, 100 do
    peak = math.max(peak, EASINGS.ease_out_back(i / 100))
  end
  check("ease_out_back overshoots", peak > 1.05)
  local low, high = 0, 0
  for i = 0, 100 do
    local v = EASINGS.bounce(i / 100)
    low, high = math.min(low, v), math.max(high, v)
  end
  check("bounce stays in range", low >= 0 and high <= 1)
  check("bounce known value", near(EASINGS.bounce(0.5), 0.765625))

  check("round half up", round_half_away(2.5) == 3)
  check("round half down for negatives", round_half_away(-2.5) == -3)
  check("round below half", round_half_away(1.49) == 1 and round_half_away(-1.49) == -1)
  check("round gives integers", math.type(round_half_away(3.0)) == "integer")
end

local ok, err = xpcall(run, debug.traceback)
if not ok then
  table.insert(failures, tostring(type(err) == "table" and err.user or err))
end
local out = assert(io.open(P.result_path, "wb"))
if #failures > 0 then
  local message = "easing checks failed: " .. table.concat(failures, "; ")
  out:write(json.encode({ ok = false, error = message }))
else
  out:write(json.encode({ ok = true, checks = checks }))
end
out:close()
