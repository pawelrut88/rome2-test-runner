-- ===== rome2-bridge (everything above is CA's vanilla all_scripted.lua, unchanged) =====
-- Only one pack can own this file, so it also starts Consul Scriptum when Consul is installed (same steps as Consul's
-- own all_scripted.lua), then the bridge. Each step is protected: a failure is logged and the game goes on.

local function __bridge_log(line)
	local f = io.open("rome2_bridge_log.txt", "a")
	if f then f:write(os.date("%H:%M:%S ") .. "[all_scripted] " .. tostring(line) .. "\n"); f:close() end
end

-- Consul Scriptum, if its pack is loaded (its module ships in its pack as consul/consul.lua)
do
	package.path = package.path .. ";consul/?.lua"
	local ok, result = pcall(require, "consul")
	if not ok or type(consul) ~= "table" then
		__bridge_log("Consul not loaded (fine without Consul): " .. (tostring(result):match("^[^\n]*") or ""))
	else
		local f = io.open("consul.log", "a")
		if f then f:write("Starting consul (from rome2-bridge all_scripted.lua)\n"); f:close() end
		local success, err = pcall(consul.setup)
		__bridge_log(success and "Consul started" or ("Consul setup error: " .. tostring(err)))
	end
end

-- the bridge
do
	ROME2_BRIDGE = ROME2_BRIDGE or {}
	ROME2_BRIDGE.loader = "pack"
	local ok, err = pcall(require, "data.lua_scripts.rome2_bridge")
	if not ok then __bridge_log("bridge load error: " .. tostring(err)) end
end
