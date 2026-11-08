# Builds the bridge pack: lua_scripts/all_scripted.lua (CA's vanilla file, extracted fresh from the game, + our tail)
# and lua_scripts/rome2_bridge.lua. Does not copy anything into the game folder.
#   powershell -File tools\build_pack.ps1 [-GameDir ...] [-Rpfm ...] [-Out ...]
param(
	# the game folder (ROME2_GAME_DIR, else Steam's default) and RPFM's command-line tool (RPFM_CLI, else on PATH)
	[string]$GameDir = $(if ($env:ROME2_GAME_DIR) { $env:ROME2_GAME_DIR } else { "C:\Program Files (x86)\Steam\steamapps\common\Total War Rome II" }),
	[string]$Rpfm = $(if ($env:RPFM_CLI) { $env:RPFM_CLI } else { "rpfm_cli.exe" }),
	[string]$Out = ""
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $Out) { $Out = Join-Path $root "pack\build\@rome2_bridge.pack" }
$build = Join-Path $root "pack\build"
$stage = Join-Path $build "stage"
$vanilla = Join-Path $build "vanilla"
foreach ($d in $stage, $vanilla) { if (Test-Path $d) { Remove-Item -Recurse -Force $d } }
New-Item -ItemType Directory -Force (Join-Path $stage "lua_scripts"), $vanilla | Out-Null

# 1. vanilla all_scripted.lua: data_rome2.pack, else data.pack
$src = $null
foreach ($p in "data_rome2.pack", "data.pack") {
	$pp = Join-Path $GameDir "data\$p"
	if (-not (Test-Path $pp)) { continue }
	& $Rpfm --game rome_2 pack extract --pack-path $pp --file-path "lua_scripts/all_scripted.lua;$vanilla" 2>&1 | Out-Null
	$f = Join-Path $vanilla "lua_scripts\all_scripted.lua"
	if (Test-Path $f) { $src = $p; break }
}
if (-not $src) { throw "vanilla lua_scripts/all_scripted.lua not found in $GameDir\data" }
$vbytes = [IO.File]::ReadAllBytes((Join-Path $vanilla "lua_scripts\all_scripted.lua"))
$vtext = [Text.Encoding]::ASCII.GetString($vbytes)
if ($vtext -notmatch 'export_triggers' -or $vtext -match 'rome2-bridge|consul') { throw "unexpected vanilla all_scripted.lua from $src" }

# 2. all_scripted.lua = vanilla bytes + blank line + our tail
$tail = [IO.File]::ReadAllBytes((Join-Path $root "pack\lua_scripts\bridge_tail.lua"))
$sep = [Text.Encoding]::ASCII.GetBytes("`r`n`r`n")
[IO.File]::WriteAllBytes((Join-Path $stage "lua_scripts\all_scripted.lua"), [byte[]]($vbytes + $sep + $tail))
Copy-Item (Join-Path $root "bridge\rome2_bridge.lua") (Join-Path $stage "lua_scripts\rome2_bridge.lua")

# 3. pack
if (Test-Path $Out) { Remove-Item -Force $Out }
& $Rpfm --game rome_2 pack create --pack-path $Out 2>&1 | Out-Null
& $Rpfm --game rome_2 pack add --pack-path $Out -F "$stage;" 2>&1 | Out-Null
$list = & $Rpfm --game rome_2 pack list --pack-path $Out 2>$null | Where-Object { $_ -notmatch '\[INFO\]' }
"vanilla from: $src ($($vbytes.Length) bytes, sha256 $((Get-FileHash (Join-Path $vanilla 'lua_scripts\all_scripted.lua')).Hash.Substring(0,12)))"
"pack: $Out ($((Get-Item $Out).Length) bytes)"
$list
