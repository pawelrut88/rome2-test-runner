-- In-game end of the Rome II bridge (rome2-bridge project). Two ways to start it:
--   - our pack: lua_scripts/all_scripted.lua requires data.lua_scripts.rome2_bridge at campaign start (no Consul needed)
--   - dofile from a Consul Scriptum entry (older route; the server copies this file to the game folder)
-- Running it again only replaces the functions (handlers are registered once).
-- Every second (time trigger) it:
--   - writes rome2_bridge_alive.json (heartbeat: time, tick, turn, whose turn, pending end turn, where it runs)
--   - runs rome2_bridge_cmd.lua if present (first line "--id <n>"), deletes it, writes the result to rome2_bridge_out.json
--   - applies auto-click rules from rome2_bridge_click.txt ("<context id> <button id>", context "-" = anywhere), one click per tick
-- Commands run in the global scope with ROME2_BRIDGE (alias B) for helpers; a command's return value is sent back as JSON.

ROME2_BRIDGE = ROME2_BRIDGE or {}
local B = ROME2_BRIDGE
_G.B = B
IA_BRIDGE = B -- old name (was ia_bridge.lua until 2026-11-08), kept for older command scripts
B.version = 2
B.tick = B.tick or 0
B.human_turn = B.human_turn or false
B.turn_starts = B.turn_starts or 0
B.last_id = B.last_id or nil
B.log_lines = {}

-- no require here: in the campaign script state that would load a second, unset-up copy of Consul
-- (plain lookup: rawget(_G, "consul") is nil in a Scriptum script although consul resolves).
-- Own lookups come first; Consul is only a fallback (Scriptum route: UICreated fired before we were loaded).
local function C() return consul end
B.where = B.loader or ((consul ~= nil) and "consul" or "campaign")

-- os.time() is frozen in the game (always the launch second): use the CPU clock for intervals
local function now() return os.clock() end
function B.log(s)
	local f = io.open("rome2_bridge_log.txt", "a")
	if f then f:write(os.date("%H:%M:%S ") .. tostring(s) .. "\n"); f:close() end
end

-- same lookups as Consul's _game(): the global, then the loaded EpisodicScripting module (other campaigns)
function B.game()
	if scripting and scripting.game_interface then return scripting.game_interface end
	for _, k in ipairs({ "lua_scripts.EpisodicScripting", "lua_scripts.episodicscripting", "data.lua_scripts.episodicscripting" }) do
		local m = package.loaded[k]
		if type(m) == "table" and m.game_interface then return m.game_interface end
	end
	local c = C()
	if c and c._game then local ok, g = pcall(c._game); if ok and g then return g end end
	return B._own_game  -- made at NewSession when the campaign has no script (see the events below)
end

function B.turn()
	local ok, t = pcall(function() return B.game():model():turn_number() end)
	return ok and t or -1
end

-- JSON encoder (tables with only 1..n keys become arrays; functions/userdata become strings)
local function esc(s)
	return (s:gsub('[%c"\\]', function(c)
		local m = { ['"'] = '\\"', ['\\'] = '\\\\', ['\n'] = '\\n', ['\r'] = '\\r', ['\t'] = '\\t' }
		return m[c] or string.format("\\u%04x", c:byte())
	end))
end
function B.json(v, depth, seen)
	depth = depth or 0; seen = seen or {}
	local t = type(v)
	if v == nil then return "null" end
	if t == "boolean" then return v and "true" or "false" end
	if t == "number" then
		-- no math.huge: the game's math library lacks it (Consul adds it; without Consul it is nil). 1/0 is inf.
		if v ~= v or v == 1 / 0 or v == -1 / 0 then return '"' .. tostring(v) .. '"' end
		if v == math.floor(v) and math.abs(v) < 1e15 then return string.format("%d", v) end
		return string.format("%.6g", v)
	end
	if t == "string" then return '"' .. esc(v) .. '"' end
	if t ~= "table" then return '"' .. esc(tostring(v)) .. '"' end
	if seen[v] or depth > 12 then return '"<table>"' end
	seen[v] = true
	local n, max = 0, 0
	for k in pairs(v) do
		n = n + 1
		if type(k) == "number" and k >= 1 and k == math.floor(k) then if k > max then max = k end else max = -1 end
	end
	local out = {}
	if n > 0 and max == n then
		for i = 1, n do out[i] = B.json(v[i], depth + 1, seen) end
		seen[v] = nil
		return "[" .. table.concat(out, ",") .. "]"
	end
	for k, x in pairs(v) do out[#out + 1] = '"' .. esc(tostring(k)) .. '":' .. B.json(x, depth + 1, seen) end
	seen[v] = nil
	return "{" .. table.concat(out, ",") .. "}"
end

local function write_atomic(name, text)
	local tmp = name .. ".tmp"
	local f = io.open(tmp, "w"); if not f then return false end
	f:write(text); f:close()
	os.remove(name)
	if os.rename(tmp, name) then return true end
	-- Windows: while the reader has the old file open it can be neither removed nor renamed over, and the reply was
	-- lost (popsupply, 2026-11-09: "no answer in 30s ... command read"). Write it in place instead; a reader that
	-- catches it half-written gets bad JSON and reads it again on its next poll.
	local g = io.open(name, "w"); if not g then return false end
	g:write(text); g:close()
	os.remove(tmp)
	return true
end

-- UI --------------------------------------------------------------------------------------------------------------
-- UIComponent: the global, else from the Lua registry (as Consul's OnUICreated does), else Consul's copy
local function uic()
	if UIComponent then return UIComponent end
	if B._UIComponent then return B._UIComponent end
	pcall(function()
		for _, v in pairs(debug.getregistry()) do
			local ok, env = pcall(debug.getfenv, v)
			if ok and type(env) == "table" and env.UIComponent ~= nil then B._UIComponent = env.UIComponent; break end
		end
	end)
	if B._UIComponent then return B._UIComponent end
	local c = C()
	if c and c.ui and c.ui._UIComponent then return c.ui._UIComponent end
	return nil
end
local function U(c) return uic()(c) end
B.U = U

-- ids of the children of component id (inside ctx); shown ones only unless all
function B.children(id, ctx, all)
	local c = B.find(id, ctx); if not c then return nil end
	local r = {}
	local n = 0; pcall(function() n = c:ChildCount() end)
	for i = 0, n - 1 do
		pcall(function()
			local k = U(c:Find(i))
			if all or k:Visible() then r[#r + 1] = tostring(k:Id()) end
		end)
	end
	return r
end
function B.root()
	if B._root then return B._root end
	local c = C()
	if c and c.ui then return c.ui._UIRoot end
	return nil
end

-- shown = the component AND every parent up to the root are visible (a closed dialog can leave its buttons' own flag on)
function B.shown(c)
	for _ = 1, 40 do
		local okv, v = pcall(function() return c:Visible() end)
		if not okv or not v then return false end
		local okp, p = pcall(function() return c:Parent() end)
		if not okp or p == nil then return true end
		local okw, pc = pcall(function() return U(p) end)
		if not okw or pc == nil then return true end
		c = pc
	end
	return true
end

-- find id, optionally inside the component ctx (ids repeat across the UI; a search from the root finds the first)
function B.find(id, ctx)
	local ok, c = pcall(function()
		local base = B.root()
		if ctx and ctx ~= "-" and ctx ~= "" then
			local cc = base:Find(ctx); if not cc then return nil end
			base = U(cc)
		end
		local x = base:Find(id); if not x then return nil end
		return U(x)
	end)
	if ok then return c end
	return nil
end

function B.info(c)
	local r = {}
	pcall(function() r.id = tostring(c:Id()) end)
	pcall(function() r.visible = c:Visible() end)
	pcall(function() r.shown = B.shown(c) end)
	pcall(function() r.interactive = c:IsInteractive() end)
	pcall(function() r.text = tostring(c:GetStateText() or "") end)
	pcall(function() r.state = tostring(c:CurrentState()) end)
	pcall(function() r.children = c:ChildCount() end)
	pcall(function() local x, y = c:Position(); r.x = x; r.y = y end)
	pcall(function() local w, h = c:Bounds(); r.w = w; r.h = h end)
	return r
end

-- click: only if shown, unless force
-- first SHOWN component with this id under ctx (or root): ids repeat, and Find returns the first, often a hidden one
function B.find_shown(id, ctx)
	local start = B.root()
	if ctx and ctx ~= "-" and ctx ~= "" then start = B.find(ctx); if not start then return nil end end
	local hit
	local function walk(c, d)
		if hit or d > 20 then return end
		local okv, vis = pcall(function() return c:Visible() end)
		if not okv or not vis then return end
		local cid; pcall(function() cid = tostring(c:Id()) end)
		if cid == id then hit = c; return end
		local n = 0; pcall(function() n = c:ChildCount() end)
		for i = 0, n - 1 do pcall(function() walk(U(c:Find(i)), d + 1) end) end
	end
	pcall(walk, start, 0)
	if hit and B.shown(hit) then return hit end
	return nil
end

function B.click(id, ctx, force)
	local c = B.find(id, ctx)
	if not c then return "not found: " .. tostring(id) end
	if not force and not B.shown(c) then c = B.find_shown(id, ctx) or c end
	if not force and not B.shown(c) then return "hidden: " .. tostring(id) end
	local ok, err = pcall(function() c:SimulateClick() end)
	B.log("click " .. tostring(id) .. " in " .. tostring(ctx or "-") .. (ok and "" or (" ERROR " .. tostring(err))))
	return ok and "clicked" or ("error: " .. tostring(err))
end

-- tree of shown components: one line per component "indent id [I] text"; opts.root, opts.maxd, opts.all (hidden too),
-- opts.interactive (only interactive lines, no indentation), opts.max (line cap)
function B.tree(opts)
	opts = opts or {}
	local maxd, cap = opts.maxd or 16, opts.max or 3000
	local lines = {}
	local start = B.root()
	if opts.root then start = B.find(opts.root, opts.ctx); if not start then return "not found: " .. opts.root end end
	local function walk(c, d)
		if #lines >= cap or d > maxd then return end
		local okv, vis = pcall(function() return c:Visible() end)
		if not opts.all and (not okv or not vis) then return end
		local id = ""; pcall(function() id = tostring(c:Id()) end)
		local txt = ""; pcall(function() txt = tostring(c:GetStateText() or "") end)
		local inter = false; pcall(function() inter = c:IsInteractive() end)
		txt = txt:gsub("[\r\n\t]", " ")
		if not opts.interactive then
			lines[#lines + 1] = string.rep(" ", d) .. id .. (inter and " [I]" or "") .. (vis and "" or " [hidden]") .. (txt ~= "" and (" | " .. txt) or "")
		elseif inter then
			lines[#lines + 1] = id .. (txt ~= "" and (" | " .. txt) or "")
		end
		local n = 0; pcall(function() n = c:ChildCount() end)
		for i = 0, n - 1 do pcall(function() walk(U(c:Find(i)), d + 1) end) end
	end
	pcall(walk, start, 0)
	if #lines >= cap then lines[#lines + 1] = "... (cut at " .. cap .. " lines)" end
	return table.concat(lines, "\n")
end

-- game -------------------------------------------------------------------------------------------------------------
function B.end_turn(force)
	-- sent during an AI turn it would end the player's next turn too (retries): refuse
	if not B.human_turn and not force then return "not the player's turn (current: " .. tostring(B.current_faction) .. ")" end
	B.want_end = true; B.end_time = now(); B.human_turn = false
	if not B.current_since or B.current_since < B.end_time - 20 then B.current_since = B.end_time end
	local ok, err = pcall(function() B.game():end_turn(true) end)
	B.log("end_turn " .. B.turn() .. (ok and "" or (" ERROR " .. tostring(err))))
	return ok and "end turn sent" or ("error: " .. tostring(err))
end

local function items(list)
	local r = {}
	pcall(function() for i = 0, list:num_items() - 1 do r[#r + 1] = list:item_at(i) end end)
	return r
end
B.items = items

-- short faction table: name, human, treasury, regions, armies (land forces), units, food
function B.factions(only)
	local out = {}
	local world = B.game():model():world()
	for _, f in ipairs(items(world:faction_list())) do
		local name = f:name()
		if not only or name == only then
			local r = { name = name }
			pcall(function() r.human = f:is_human() end)
			pcall(function() r.treasury = f:treasury() end)
			pcall(function() r.regions = f:region_list():num_items() end)
			pcall(function() r.food = f:total_food() end)
			pcall(function() r.food_shortage = f:has_food_shortage() end)
			pcall(function()
				local forces, units = 0, 0
				for _, m in ipairs(items(f:military_force_list())) do
					forces = forces + 1; units = units + m:unit_list():num_items()
				end
				r.forces = forces; r.units = units
			end)
			if r.regions and r.regions > 0 or r.human or only then out[#out + 1] = r end
		end
	end
	return out
end

-- top-level panels that are shown (children of root, and of their first level), with their interactive buttons:
-- what is on screen when a turn does not move
function B.panels()
	local out = {}
	local root = B.root()
	local n = 0; pcall(function() n = root:ChildCount() end)
	for i = 0, n - 1 do
		pcall(function()
			local c = U(root:Find(i))
			if c:Visible() then
				local id = tostring(c:Id())
				local buttons = {}
				local function walk(x, d)
					if d > 8 or #buttons > 20 then return end
					if not x:Visible() then return end
					local xid = tostring(x:Id())
					if xid:find("button") or xid:find("accept") or xid:find("cancel") or xid:find("decline") or xid:find("ok") then buttons[#buttons + 1] = xid end
					for j = 0, x:ChildCount() - 1 do pcall(function() walk(U(x:Find(j)), d + 1) end) end
				end
				walk(c, 0)
				out[#out + 1] = { id = id, buttons = buttons }
			end
		end)
	end
	return out
end

-- tick -------------------------------------------------------------------------------------------------------------
local function heartbeat()
	local s = { t = now(), tick = B.tick, turn = B.turn(), human_turn = B.human_turn, want_end = B.want_end or false,
		turn_starts = B.turn_starts, where = B.where, dropped = B.dropped, last_id = B.last_id, version = B.version, current = B.current_faction, human_key = B.human_key, defeated = B.defeated,
		current_for_s = B.current_since and math.floor(now() - B.current_since) or nil }
	pcall(function() s.mode = consul.env.mode end)
	s.has_game = B.game() ~= nil
	s.has_root = B.root() ~= nil
	s.screen = s.has_game and "campaign" or "menu"
	write_atomic("rome2_bridge_alive.json", B.json(s))
end

local function run_command()
	local f = io.open("rome2_bridge_cmd.lua", "r"); if not f then return end
	local code = f:read("*a"); f:close()
	os.remove("rome2_bridge_cmd.lua")
	local id = code:match("^%-%-id (%S+)") or "?"
	B.last_id = id
	local res = { id = id }
	local chunk, err = loadstring(code, "=mcp")
	if not chunk then
		res.ok = false; res.error = "compile: " .. tostring(err)
	else
		-- while the command runs this file names it: if the game closes during it, Python can say so (consul-work
		-- 2026-11-11: "game exited while waiting", no dump, no way to tell whether the command killed it)
		local m = io.open("rome2_bridge_running.txt", "w"); if m then m:write(id); m:close() end
		local packed = { pcall(chunk) }
		os.remove("rome2_bridge_running.txt")
		res.ok = packed[1]
		if packed[1] then
			if #packed <= 2 then res.result = packed[2] else table.remove(packed, 1); res.result = packed end
		else
			res.error = tostring(packed[2])
		end
	end
	local okj, text = pcall(B.json, res)
	if not okj then text = B.json({ id = id, ok = false, error = "json: " .. tostring(text) }) end
	write_atomic("rome2_bridge_out.json", text)
end

local function click_rules()
	local f = io.open("rome2_bridge_click.txt", "r"); if not f then return false end
	local rules = {}
	for line in f:lines() do rules[#rules + 1] = line end
	f:close()
	for _, line in ipairs(rules) do
		local ctxid, btn = line:match("^%s*(%S+)%s+(%S+)")
		if ctxid and btn and ctxid:sub(1, 1) ~= "#" then
			-- ids repeat and Find returns the first, often a hidden one: look for a shown one
			local c = B.find_shown(btn, ctxid)
			if c and (ctxid == "-" or B.shown(B.find(ctxid) or c)) then
				pcall(function() c:SimulateClick() end)
				B.log("auto-click " .. btn .. " in " .. ctxid)
				return true
			end
		end
	end
	return false
end

B.on_timer = function(ctx)
	B.tt_seen = (B.tt_seen or 0) + 1
	if B.tt_seen <= 3 then B.log("TimeTrigger " .. tostring(ctx.string)) end
	-- every arm uses a new trigger name; only the newest one ticks and re-arms. An older trigger that was still pending
	-- (armed during loading, then re-armed at turn start) fires once and stops, so there is only ever one chain.
	-- (A time check doesn't work: during AI turns the game delivers ticks in bursts. Seen 2026-11-07.)
	if ctx.string == "tick_increment_counter" and not B.game() then
		-- main menu: CA's front-end timer_manager ticks this every 100 ms (Timers is not reachable from here, seen
		-- 2026-11-08); every 10th one is our 1 s tick
		B.fe_n = (B.fe_n or 0) + 1
		if B.fe_n % 10 ~= 0 then return end
		B.fe_armed = true
	else
		if type(ctx.string) ~= "string" or ctx.string:sub(1, 17) ~= "rome2_bridge_tick" then return end
		if ctx.string ~= B.tname then B.dropped = (B.dropped or 0) + 1; return end
	end
	B.tick = B.tick + 1
	B.last_tick = now()
	-- the first 3 ticks, then every 300th (about once a minute) so the log shows when the timer stopped, if it ever does
	if B.tick <= 3 or B.tick % 300 == 0 then B.log("tick " .. B.tick .. " (" .. ctx.string .. ")") end
	local okr, er = pcall(run_command); if not okr then B.log("run_command error: " .. tostring(er)) end
	local clicked = false
	local okc, c = pcall(click_rules); clicked = okc and c
	-- an end_turn sent while a dialog is open (e.g. a dilemma at turn start) is dropped: retry every 15 s until an AI turn starts
	if B.want_end and not clicked and now() - (B.end_time or 0) >= 15 then B.log("turn did not end, retry"); B.end_turn() end
	local okh, eh = pcall(heartbeat); if not okh then B.log("heartbeat error: " .. tostring(eh)) end
	if not B.fe_armed then pcall(function() B.game():add_time_trigger(B.tname, 1) end) end
end

B.on_turn = function(ctx)
	local okh, human = pcall(function() return ctx:faction():is_human() end)
	pcall(function() B.current_faction = ctx:faction():name() end)
	B.current_since = now()
	if not okh then return end
	if human then pcall(function() B.human_key = ctx:faction():name() end); B.human_turn = true; B.want_end = false; B.turn_starts = B.turn_starts + 1; B.log("human turn start " .. B.turn())
	else B.human_turn = false; B.want_end = false end
end

-- (re)arm the timer: after a load the old trigger is gone, and a trigger set during loading may never fire. Called on
-- load, UICreated, first tick and every faction turn start (a watchdog during AI turns); skipped while the timer ticks
-- or was armed in the last 3 s. Each arm takes a new name (see on_timer), so a late old trigger can't double the rate.
B.arm = function(why)
	local t = now()
	if B.last_tick and t - B.last_tick < 3 then return end
	if B.armed_at and t - B.armed_at < 3 then return end
	local g = B.game()
	if not g then
		-- main menu (front end): no game interface, but the front end's Timers object; its timers arrive as TimeTrigger
		-- events too (seen 2026-11-08). A repeating timer needs no re-arm.
		local T = rawget(_G, "Timers")
		if B.fe_armed or T == nil then return end
		B.gen = (B.gen or 0) + 1
		local name = "rome2_bridge_tick_" .. B.gen
		local ok, err = pcall(function() T.register_repeating(name, 1000) end)
		if ok then B.armed_at = t; B.tname = name; B.fe_armed = true end
		B.log("arm " .. name .. " (" .. tostring(why) .. ", main menu)" .. (ok and "" or (" failed: " .. tostring(err))))
		return
	end
	B.gen = (B.gen or 0) + 1
	local name = "rome2_bridge_tick_" .. B.gen
	local ok = pcall(function() g:add_time_trigger(name, 1) end)
	if ok then B.armed_at = t; B.tname = name end
	B.log("arm " .. name .. " (" .. tostring(why) .. ")" .. (ok and "" or " failed"))
end

-- started mid-turn on the player's map: assume it's the player's turn until an AI turn starts
local function guess_human()
	pcall(function()
		for _, f in ipairs(items(B.game():model():world():faction_list())) do
			if f:is_human() then
				B.human_key = f:name()
				if B.turn_starts == 0 then B.human_turn = true; B.current_faction = f:name() end
				break
			end
		end
	end)
end

-- game over: the player's faction was destroyed (no regions and no forces, or is_dead). The game then shows its
-- Defeat screen and stops running scripts (no more ticks: seen 2026-11-08, DeI GC Rome destroyed at turn 19), so
-- this runs on the events around it and writes the heartbeat at once; the runner reads "defeated" from it.
B.check_defeat = function(why)
	if B.defeated or not B.human_key then return end
	local dead = false
	pcall(function()
		for _, f in ipairs(items(B.game():model():world():faction_list())) do
			if f:name() == B.human_key then
				local d = false
				pcall(function() d = f:is_dead() end)
				local regions, forces = 1, 1
				pcall(function() regions = f:region_list():num_items() end)
				pcall(function() forces = f:military_force_list():num_items() end)
				dead = d or (regions == 0 and forces == 0)
				break
			end
		end
	end)
	if dead then
		B.defeated = B.turn()
		B.log("DEFEAT: " .. B.human_key .. " destroyed, turn " .. tostring(B.defeated) .. " (" .. tostring(why) .. ")")
		pcall(heartbeat)
	end
end

if not B.registered then
	B.registered = true
	table.insert(events.TimeTrigger, function(ctx) ROME2_BRIDGE.on_timer(ctx) end)
	table.insert(events.FactionTurnStart, function(ctx) ROME2_BRIDGE.on_turn(ctx); ROME2_BRIDGE.arm("turn start") end)
	table.insert(events.UICreated, function(ctx)
		pcall(function() ROME2_BRIDGE._root = U(ctx.component) end)
		ROME2_BRIDGE.log("UICreated, root " .. tostring(ROME2_BRIDGE._root ~= nil))
		ROME2_BRIDGE.arm("UICreated")
	end)
	if events.FirstTickAfterWorldCreated then
		table.insert(events.FirstTickAfterWorldCreated, function() ROME2_BRIDGE.guess_human(); ROME2_BRIDGE.arm("first tick") end)
	end
	-- a campaign without campaigns/<key>/scripting.lua never loads EpisodicScripting, so nobody makes the game
	-- interface and the bridge can't tick (IA 2026-11-12, key main_ia2). EpisodicScripting makes it at NewSession with
	-- GAME(context); do the same, but only when no campaign script has loaded it.
	if type(events.NewSession) == "table" then
		if type(events.UIDestroyed) == "table" then
			table.insert(events.UIDestroyed, function() ROME2_BRIDGE._own_game = nil end)  -- campaign left
		end
		table.insert(events.NewSession, function(ctx)
			ROME2_BRIDGE._own_game = nil
			local loaded = false
			for _, k in ipairs({ "lua_scripts.EpisodicScripting", "lua_scripts.episodicscripting", "data.lua_scripts.episodicscripting" }) do
				if package.loaded[k] then loaded = true end
			end
			if loaded or (scripting and scripting.game_interface) then return end
			-- GAME is no global here (IA 2026-11-12: "attempt to call global 'GAME'"); the engine keeps the class in the
			-- Lua registry: debug.getregistry().GAME is the userdata's metatable; its __index / __metatable table holds
			-- the methods, among them new (seen in a Rome II campaign 2026-11-12)
			local ok, g = pcall(function()
				local G = rawget(_G, "GAME")
				if G then return G(ctx) end
				local mt = debug.getregistry().GAME
				local methods = (type(mt.__index) == "table" and mt.__index.new and mt.__index) or mt.__metatable
				return methods.new(ctx)
			end)
			if ok and g then ROME2_BRIDGE._own_game = g end
			pcall(ROME2_BRIDGE.log, "NewSession without campaign script: own game interface " .. (ok and g and "made" or ("failed: " .. tostring(g))))
		end)
	end
	-- watchdog: should the timer ever stop, UI activity (the player's mouse, panels, messages) re-arms it; arm() does
	-- nothing while the timer ticks. (Tested 2026-11-08 with the timer stopped on purpose: mouse moves and Esc posted
	-- to the window don't fire these events; real mouse use was not tested.)
	for _, name in ipairs({ "ComponentMouseOn", "ComponentLClickUp", "ShortcutTriggered", "PanelOpenedCampaign",
		"PanelClosedCampaign", "CameraMoverFinished", "CameraMoverCancelled", "HudRefresh", "IncomingMessage",
		"EventMessageOpenedCampaign", "LoadingScreenDismissed" }) do
		if type(events[name]) == "table" then
			table.insert(events[name], function()
				local ok, err = pcall(ROME2_BRIDGE.arm, name)
				if not ok then pcall(ROME2_BRIDGE.log, "arm on " .. name .. " failed: " .. tostring(err)) end
			end)
			ROME2_BRIDGE.watch = (ROME2_BRIDGE.watch or 0) + 1
		end
	end
	-- game over check (see check_defeat). Panels opened during AI turns are logged, to learn the Defeat screen's name
	for _, name in ipairs({ "RegionChangedFaction", "GarrisonOccupiedEvent", "SettlementOccupied", "FactionTurnStart",
		"FactionTurnEnd", "VictoryConditionFailed", "PanelOpenedCampaign" }) do
		if type(events[name]) == "table" then
			table.insert(events[name], function(ctx)
				if name == "PanelOpenedCampaign" then
					pcall(function() if not ROME2_BRIDGE.human_turn then
						ROME2_BRIDGE.log("panel opened: " .. tostring(ctx.string)) end end)
				end
				local ok, err = pcall(ROME2_BRIDGE.check_defeat, name)
				if not ok then pcall(ROME2_BRIDGE.log, "check_defeat on " .. name .. " failed: " .. tostring(err)) end
			end)
		end
	end
end
B.guess_human = guess_human
guess_human()
B.arm("load")
B.log("bridge started (" .. B.where .. "), turn " .. B.turn() .. ", game " .. tostring(B.game() ~= nil))
do local okh, eh = pcall(heartbeat); if not okh then B.log("heartbeat error: " .. tostring(eh)) end end
pcall(function() consul.console.write("rome2_bridge started") end)
return "rome2_bridge started"
