# Builds extras\build\@@0_PAW_legio_invicta.pack from the TSV files in extras\legio_invicta = "Legio Invicta" (the user's
# super soldiers mod, improved with the stat list of the Consul add-on "Virtus"): every unit of the human player's
# faction 1000 times stronger (+99900% on 15 stats), +50% battle speed and range. Applied through the difficulty
# handicap table, so no script and no Consul are needed; it is on for the human faction whenever the pack is loaded.
#   powershell -File tools\build_legio_invicta.ps1 [-Times 1000] [-Rpfm ...] [-Schema ...]
# -Times N builds a weaker or stronger copy (+(N-1)*100 % on the same stats) as @@0_PAW_legio_invicta_x<N>.pack
# (testrun --legio N loads it).
param(
	[int]$Times = 1000,
	[string]$Rpfm = $(if ($env:RPFM_CLI) { $env:RPFM_CLI } else { "rpfm_cli.exe" }),
	# RPFM's Rome II schema (schema_rom2.ron), needed to turn the TSV files into game tables
	[string]$Schema = $(if ($env:RPFM_SCHEMA) { $env:RPFM_SCHEMA } else { Join-Path $env:APPDATA "FrodoWazEre\rpfm\config\schemas\schema_rom2.ron" })
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$src = Join-Path $root "extras\legio_invicta"
$outDir = Join-Path $root "extras\build"
New-Item -ItemType Directory -Force $outDir | Out-Null
if ($Times -lt 2) { throw "-Times must be 2 or more" }
$name = if ($Times -eq 1000) { "@@0_PAW_legio_invicta.pack" } else { "@@0_PAW_legio_invicta_x$Times.pack" }
$out = Join-Path $outDir $name
if ($Times -ne 1000) {
	# a copy of the TSV files with the strength changed (99900.0000 = 1000 times)
	$tmp = Join-Path $outDir "tsv_x$Times"
	if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
	Copy-Item -Recurse $src $tmp
	$h = Join-Path $tmp "db\campaign_difficulty_handicap_effects_tables\@PAW_legio_invicta.tsv"
	$v = (($Times - 1) * 100).ToString("0.0000", [Globalization.CultureInfo]::InvariantCulture)  # a dot, whatever the locale
	$txt = [IO.File]::ReadAllText($h)
	if ($txt -notmatch "99900\.0000") { throw "strength value not found in $h" }
	[IO.File]::WriteAllText($h, $txt.Replace("99900.0000", $v))
	$src = $tmp
}
if (Test-Path $out) { Remove-Item -Force $out }
& $Rpfm --game rome_2 pack create --pack-path $out 2>&1 | Out-Null
& $Rpfm --game rome_2 pack add --pack-path $out --tsv-to-binary $Schema -F "$src\db;db" -F "$src\text;text" 2>&1 | Out-Null
$list = & $Rpfm --game rome_2 pack list --pack-path $out 2>$null | Where-Object { $_ -notmatch '\[INFO\]' }
"pack: $out ($((Get-Item $out).Length) bytes)"
$list
