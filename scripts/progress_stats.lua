-- progress_stats.lua (rome2-bridge). READ-ONLY: changes nothing in the game.
-- Returns {turn = <game turn>, factions = {{name, human, treasury, regions, region_keys, forces, armies, navies,
-- units, food, food_shortage}, ...}} for every faction that has a region or a military force (or is human). Used by the Test
-- Runner on the map-screenshot turns (turn<N>_stats.json) for the Progress window. Every value is read in a pcall:
-- a method missing in some game version gives nil, never an error.
local game = ROME2_BRIDGE and ROME2_BRIDGE.game and ROME2_BRIDGE.game()
if not game then return {error = "no game interface (campaign map only)"} end
local world = game:model():world()
local function items(list)
	local r = {}
	pcall(function() for i = 0, list:num_items() - 1 do r[#r + 1] = list:item_at(i) end end)
	return r
end
local out = {factions = {}}
pcall(function() out.turn = game:model():turn_number() end)
for _, f in ipairs(items(world:faction_list())) do
	local r = {}
	pcall(function() r.name = f:name() end)
	pcall(function() r.human = f:is_human() end)
	pcall(function() r.treasury = f:treasury() end)
	pcall(function() r.regions = f:region_list():num_items() end)
	-- region keys, for the Progress window's drawn map (who owns what)
	local keys = {}
	for _, reg in ipairs(items(f:region_list())) do pcall(function() keys[#keys + 1] = reg:name() end) end
	if #keys > 0 then r.region_keys = keys end
	pcall(function() r.food = f:total_food() end)
	pcall(function() r.food_shortage = f:has_food_shortage() end)
	local forces, armies, navies, units = 0, 0, 0, 0
	for _, m in ipairs(items(f:military_force_list())) do
		forces = forces + 1
		pcall(function() units = units + m:unit_list():num_items() end)
		-- a real army or fleet is led by a general; a city's garrison force is not (its commander is no "general").
		-- has_garrison_residence() is no test: it is true for every army standing in a city (DeI starts them all in
		-- one), checked in game 2026-11-08 (DeI and vanilla GC, Rome: 2 armies + 1 fleet vanilla, 2 armies DeI).
		local real = nil
		pcall(function() real = m:general_character():character_type("general") end)
		if real == nil then  -- the call failed: fall back to the old test
			pcall(function() real = not m:has_garrison_residence() end)
		end
		if real then
			local navy = false
			pcall(function() navy = m:is_navy() end)
			if navy then navies = navies + 1 else armies = armies + 1 end
		end
	end
	r.forces, r.armies, r.navies, r.units = forces, armies, navies, units
	if r.name and ((r.regions or 0) > 0 or forces > 0 or r.human) then out.factions[#out.factions + 1] = r end
end
return out
