-- faction_report.lua (rome2-bridge; was ia_armies2.lua until 2026-11-08). READ-ONLY: changes nothing in the game.
-- Writes, into the game folder:
--   report_factions.txt   faction, treasury, forces, units, regions
--   report_garrisons.txt  faction, garrison region (or empty), has general, unit keys of every military force
--   report_food.txt       faction leader (male, name, age), food shortage / total food / regions, culture/subculture
--   report_chars.txt      every character: faction, type, male, name, has force, is leader, age
--   report_pos.txt        region settlement positions; force positions of dei_* factions and emp_pompey
-- Same columns as the old ia_*.txt files. Run it any of these ways (campaign map):
--   - Consul Scriptum: put faction_report.lua in the game folder, add a line "faction_report.lua" to consul.scriptum,
--     then click its entry in the Scriptum list
--   - Consul's console (file in the game folder):  /r dofile("faction_report.lua")
--   - rome2-bridge: python -m rome2bridge lua -f scripts\faction_report.lua   (no Consul needed)
-- Works with or without Consul.

if consul == nil then pcall(require, "consul") end -- Scriptum scripts have consul already; without Consul this fails quietly

local function get_game()
	if ROME2_BRIDGE and ROME2_BRIDGE.game then local g = ROME2_BRIDGE.game(); if g then return g end end
	if consul ~= nil and consul._game then local ok, g = pcall(consul._game); if ok and g then return g end end
	if scripting and scripting.game_interface then return scripting.game_interface end
	return nil
end
local game = get_game()
if not game then return "faction_report: no game interface (run it on the campaign map)" end

local out = io.open("report_factions.txt", "w")
local g = io.open("report_garrisons.txt", "w")
local fd = io.open("report_food.txt", "w")
local world = game:model():world()
local fl = world:faction_list()
for i = 0, fl:num_items() - 1 do
	local f = fl:item_at(i)
	local ok, err = pcall(function()
		local n, u = 0, 0
		local ml = f:military_force_list()
		for j = 0, ml:num_items() - 1 do
			local m = ml:item_at(j)
			local ul = m:unit_list()
			n = n + 1; u = u + ul:num_items()
			local where, us = "", {}
			pcall(function() if m:has_garrison_residence() then where = m:garrison_residence():region():name() end end)
			for k = 0, ul:num_items() - 1 do us[#us + 1] = ul:item_at(k):unit_key() end
			g:write(f:name() .. "\t" .. where .. "\t" .. tostring(m:has_general()) .. "\t" .. table.concat(us, ",") .. "\n")
		end
		out:write(f:name() .. "\t" .. tostring(f:treasury()) .. "\t" .. n .. "\t" .. u .. "\t" .. f:region_list():num_items() .. "\n")
		pcall(function() local l = f:faction_leader(); fd:write("leader\t" .. f:name() .. "\t" .. tostring(l:is_male()) .. "\t" .. tostring(l:get_forename()) .. "\t" .. tostring(l:age()) .. "\n") end)
		fd:write(f:name() .. "\t" .. tostring(f:has_food_shortage()) .. "\t" .. tostring(f:total_food()) .. "\t" .. f:region_list():num_items() .. "\n")
	end)
	pcall(function() fd:write("culture\t" .. f:name() .. "\t" .. tostring(f:culture()) .. "\t" .. tostring(f:subculture()) .. "\n") end)
	if not ok then out:write(f:name() .. "\terror " .. tostring(err) .. "\n") end
end
local c = io.open("report_chars.txt", "w")
for i = 0, fl:num_items() - 1 do
	local f = fl:item_at(i)
	pcall(function()
		local leader = ""
		pcall(function() leader = f:faction_leader():get_forename() end)
		local cl = f:character_list()
		for j = 0, cl:num_items() - 1 do
			local ch = cl:item_at(j)
			pcall(function()
				local ty = "other"
				for _, n in ipairs({"general", "colonel", "dignitary", "spy", "champion", "admiral"}) do if ch:character_type(n) then ty = n; break end end
				c:write(f:name() .. "\t" .. ty .. "\t" .. tostring(ch:is_male()) .. "\t" .. tostring(ch:get_forename()) .. "\t" .. tostring(ch:has_military_force()) .. "\t" .. tostring(ch:get_forename() == leader) .. "\t" .. tostring(ch:age()) .. "\n")
			end)
		end
	end)
end
c:close()
local p = io.open("report_pos.txt", "w")
pcall(function()
	local rl = world:region_manager():region_list()
	for i = 0, rl:num_items() - 1 do
		local r = rl:item_at(i)
		pcall(function() p:write("region\t" .. r:name() .. "\t" .. r:settlement():logical_position_x() .. "\t" .. r:settlement():logical_position_y() .. "\n") end)
	end
end)
for i = 0, fl:num_items() - 1 do
	local f = fl:item_at(i)
	if string.find(f:name(), "^dei_") or f:name() == "emp_pompey" then
		pcall(function()
			local ml = f:military_force_list()
			for j = 0, ml:num_items() - 1 do
				local m = ml:item_at(j)
				local ok = pcall(function() local ch = m:general_character(); p:write("force\t" .. f:name() .. "\t" .. ch:logical_position_x() .. "\t" .. ch:logical_position_y() .. "\t" .. m:unit_list():num_items() .. "\n") end)
				if not ok then pcall(function() p:write("force\t" .. f:name() .. "\t0\t0\t" .. m:unit_list():num_items() .. "\n") end) end
			end
		end)
	end
end
p:close()
out:close()
g:close()
fd:close()
local msg = "faction_report: report_factions/garrisons/food/chars/pos.txt written (" .. fl:num_items() .. " factions)"
pcall(function() consul.console.write(msg) end)
return msg
