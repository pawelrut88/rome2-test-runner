# Skip a campaign intro: while the bridge reports cinematic_bars shown, post Esc (one Esc skips one part of the intro).
# Needs a running bridge. Never sends Esc when no intro is shown (Esc on the map would open the game menu).
#   skip_intro.ps1 [-GameDir ...] [-Max 6] [-Delay 5]
param([string]$GameDir = $(if ($env:ROME2_GAME_DIR) { $env:ROME2_GAME_DIR } else { "C:\Program Files (x86)\Steam\steamapps\common\Total War Rome II" }),
	[int]$Max = 6, [int]$Delay = 5)
$cmd = Join-Path $GameDir "rome2_bridge_cmd.lua"; $out = Join-Path $GameDir "rome2_bridge_out.json"
function Ask-Bars {
	$id = "skip" + [Environment]::TickCount
	$tmp = "$cmd.tmp"
	[IO.File]::WriteAllText($tmp, "--id $id`nreturn B.find_shown(`"cinematic_bars`") ~= nil`n")
	Move-Item -Force $tmp $cmd
	for ($i = 0; $i -lt 40; $i++) {
		Start-Sleep -Milliseconds 250
		try { $r = Get-Content $out -Raw -ErrorAction Stop | ConvertFrom-Json } catch { continue }
		if ("$($r.id)" -eq $id) { return [bool]$r.result }
	}
	throw "no answer from the bridge"
}
# Esc pressed right away skips only one camera shot; after ~5 s of intro it skips the whole intro (user, 2026-11-07)
$n = 0
while ($n -lt $Max -and (Ask-Bars)) {
	Start-Sleep -Seconds $Delay
	& (Join-Path $PSScriptRoot "post_key.ps1") -Vk 0x1B -Wait 3
	$n++
}
"Esc sent $n time(s); intro shown now: $(Ask-Bars)"
