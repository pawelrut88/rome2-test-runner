# Builds the bridge pack: lua_scripts/all_scripted.lua (CA's vanilla file, extracted fresh from the game, + our tail)
# and lua_scripts/rome2_bridge.lua. Does not copy anything into the game folder.
#   powershell -File tools\build_pack.ps1 [-Game rome_2|attila|thrones_of_britannia] [-GameDir ...] [-Rpfm ...] [-Out ...]
# Attila and Thrones of Britannia (2026-11-12) load the same lua_scripts/all_scripted.lua; their packs go to
# pack\build\<game>\@rome2_bridge.pack.
param(
	[ValidateSet("rome_2", "attila", "thrones_of_britannia")][string]$Game = "rome_2",
	# the game folder (Rome II: ROME2_GAME_DIR; else found in Steam's libraries) and RPFM's command-line tool
	# (RPFM_CLI, else on PATH)
	[string]$GameDir = "",
	[string]$Rpfm = $(if ($env:RPFM_CLI) { $env:RPFM_CLI } else { "rpfm_cli.exe" }),
	[string]$Out = ""
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $GameDir) {
	if ($Game -eq "rome_2" -and $env:ROME2_GAME_DIR) { $GameDir = $env:ROME2_GAME_DIR }
	else {
		$key = @{ "rome_2" = "rome2"; "attila" = "attila"; "thrones_of_britannia" = "tob" }[$Game]
		$GameDir = (& python -c "import sys; sys.path.insert(0, sys.argv[1]); from rome2bridge.config import find_game_dir; print(find_game_dir(sys.argv[2]) or '')" $root $key)
	}
	if (-not $GameDir) { throw "game folder not found: give -GameDir" }
}
$build = Join-Path $root "pack\build"
if ($Game -ne "rome_2") { $build = Join-Path $build $Game }
if (-not $Out) { $Out = Join-Path $build "@rome2_bridge.pack" }
$stage = Join-Path $build "stage"
$vanilla = Join-Path $build "vanilla"
foreach ($d in $stage, $vanilla) { if (Test-Path $d) { Remove-Item -Recurse -Force $d } }
New-Item -ItemType Directory -Force (Join-Path $stage "lua_scripts"), $vanilla | Out-Null

# 1. vanilla all_scripted.lua: data_rome2.pack, else data.pack
$src = $null
foreach ($p in "data_rome2.pack", "data.pack") {
	$pp = Join-Path $GameDir "data\$p"
	if (-not (Test-Path $pp)) { continue }
	& $Rpfm --game $Game pack extract --pack-path $pp --file-path "lua_scripts/all_scripted.lua;$vanilla" 2>&1 | Out-Null
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
& $Rpfm --game $Game pack create --pack-path $Out 2>&1 | Out-Null
& $Rpfm --game $Game pack add --pack-path $Out -F "$stage;" 2>&1 | Out-Null
$list = & $Rpfm --game $Game pack list --pack-path $Out 2>$null | Where-Object { $_ -notmatch '\[INFO\]' }
"vanilla from: $src ($($vbytes.Length) bytes, sha256 $((Get-FileHash (Join-Path $vanilla 'lua_scripts\all_scripted.lua')).Hash.Substring(0,12)))"
"pack: $Out ($((Get-Item $Out).Length) bytes)"
$list
