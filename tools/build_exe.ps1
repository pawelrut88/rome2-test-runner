# Builds dist\Rome2TestRunner.exe (one file, the desktop window "Rome II Test Runner") with PyInstaller in a private venv (build\venv), so the
# system Python stays untouched. Bundles: tools\*.ps1 + crashsig.py, scripts\faction_report.lua,
# pack\build\@rome2_bridge.pack (build it first: tools\build_pack.ps1), rome2bridge\factions\*.json.
#   powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1
param([string]$Dist = "dist")   # another folder when dist\Rome2TestRunner.exe is open (locked)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Venv = Join-Path $Root "build\venv"
if (-not (Test-Path "$Venv\Scripts\python.exe")) {
	python -m venv $Venv
	& "$Venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
	& "$Venv\Scripts\python.exe" -m pip install --quiet pyinstaller
}
if (-not (Test-Path "pack\build\@rome2_bridge.pack")) { throw "pack\build\@rome2_bridge.pack missing: run tools\build_pack.ps1 first" }
if (-not (Test-Path "extras\build\@@0_PAW_legio_invicta.pack")) { throw "extras\build\@@0_PAW_legio_invicta.pack missing: run tools\build_legio_invicta.ps1 first" }
if (-not (Test-Path "extras\build\@@0_PAW_legio_invicta_x100.pack")) { throw "extras\build\@@0_PAW_legio_invicta_x100.pack missing: run tools\build_legio_invicta.ps1 -Times 100 first" }
$data = @(
	"tools\post_key.ps1;tools", "tools\post_click.ps1;tools", "tools\game_shot.ps1;tools", "tools\skip_intro.ps1;tools",
	"tools\crashsig.py;tools", "scripts\faction_report.lua;scripts", "scripts\progress_stats.lua;scripts", "pack\build\@rome2_bridge.pack;pack\build",
	"extras\build\@@0_PAW_legio_invicta.pack;extras\build", "extras\build\@@0_PAW_legio_invicta_x100.pack;extras\build",
	"rome2bridge\factions;rome2bridge\factions", "rome2bridge\maps;rome2bridge\maps"
)
# version from rome2bridge\__init__.py -> the exe's file properties (Details tab)
$ver = (Select-String -Path "rome2bridge\__init__.py" -Pattern '__version__ = "([\d.]+)"').Matches[0].Groups[1].Value
$v4 = (@($ver.Split(".")) + @("0", "0", "0"))[0..3] -join ", "
New-Item -ItemType Directory -Force build | Out-Null
$vf = Join-Path $Root "build\version_info.txt"
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($v4), prodvers=($v4), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('ProductName', 'Rome II Test Runner'),
      StringStruct('FileDescription', 'Rome II Test Runner'),
      StringStruct('FileVersion', '$ver'),
      StringStruct('ProductVersion', '$ver'),
      StringStruct('OriginalFilename', 'Rome2TestRunner.exe'),
      StringStruct('InternalName', 'Rome2TestRunner')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@ | Set-Content -Encoding utf8 $vf
$pyi = @("-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed", "--name", "Rome2TestRunner",
	"--distpath", $Dist, "--workpath", "build\pyi", "--specpath", "build", "--paths", $Root, "--version-file", $vf)
foreach ($d in $data) { $src, $dst = $d.Split(";"); $pyi += @("--add-data", "$(Join-Path $Root $src);$dst") }
$pyi += (Join-Path $Root "tools\rome2_test_runner.py")
& "$Venv\Scripts\python.exe" @pyi
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
Get-Item (Join-Path $Dist "Rome2TestRunner.exe") | Select-Object FullName, Length, LastWriteTime
