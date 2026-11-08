# Capture only the Rome2 window to a PNG (for checking the game by sight in unattended runs). PrintWindow with
# PW_RENDERFULLCONTENT; CopyFromScreen returns black for the game's client area.
#   game_shot.ps1 -Out shot.png                                   968 px wide, scaled from the window (default)
#   game_shot.ps1 -Out shot.png -Full                             the window's own size
#   game_shot.ps1 -Out part.png -Left 100 -Top 50 -Width 400 -Height 300
#       a part of the window at full size; Left/Top in window pixels (the window's top-left corner, title bar
#       included, is 0,0), the same pixels as a -Full picture
# Prints how it was taken, the window size and the saved size, e.g. "printwindow=True window 1936x1119 saved 968x559".
# (Loop variables are $i/$j: PowerShell names ignore case, so $x/$y would be the same variables as -X/-Y.)
param([Parameter(Mandatory = $true)][string]$Out, [switch]$Full,
	[int]$Left = -1, [int]$Top = -1, [int]$Width = 0, [int]$Height = 0, [string]$Process = "Rome2")
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing
Add-Type -Name W -Namespace IA -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
[DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint f);
public struct RECT { public int L, T, R, B; }
'@
$crop = ($Left -ge 0 -or $Top -ge 0 -or $Width -gt 0 -or $Height -gt 0)
if ($crop -and ($Left -lt 0 -or $Top -lt 0 -or $Width -le 0 -or $Height -le 0)) {
	throw "a crop needs all four: -Left -Top (0 or more) -Width -Height (more than 0)"
}
$h = (Get-Process $Process | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1).MainWindowHandle
if (-not $h) { throw "no window of process $Process" }
$r = New-Object IA.W+RECT; [void][IA.W]::GetWindowRect($h, [ref]$r)
$ww = $r.R - $r.L; $wh = $r.B - $r.T
$bmp = New-Object System.Drawing.Bitmap $ww, $wh
$g = [System.Drawing.Graphics]::FromImage($bmp); $dc = $g.GetHdc()
$ok = [IA.W]::PrintWindow($h, $dc, 2); $g.ReleaseHdc($dc)
# Exclusive fullscreen: PrintWindow gives an all-black image, but a screen copy works (2026-11-08, 2560x1440).
$black = $true
for ($i = 1; $i -lt 8 -and $black; $i++) { for ($j = 1; $j -lt 8; $j++) {
	$p = $bmp.GetPixel([int]($ww * $i / 8), [int]($wh * $j / 8)); if ($p.R + $p.G + $p.B -gt 30) { $black = $false; break } } }
$how = "printwindow=$ok"
if ($black) {
	$g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size); $how = "screen_copy (printwindow black)"
}
$g.Dispose()
if ($crop) {
	if ($Left + $Width -gt $ww -or $Top + $Height -gt $wh) {
		$bmp.Dispose(); throw "crop $Left,$Top ${Width}x$Height is outside the window (${ww}x$wh)"
	}
	$s = $bmp.Clone((New-Object System.Drawing.Rectangle $Left, $Top, $Width, $Height), $bmp.PixelFormat)
	$how += " crop $Left,$Top"
} elseif ($Full) {
	$s = $bmp.Clone((New-Object System.Drawing.Rectangle 0, 0, $ww, $wh), $bmp.PixelFormat)
} else {
	$s = New-Object System.Drawing.Bitmap $bmp, 968, ([int](968 * $wh / $ww))
}
$s.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
"$how window ${ww}x$wh saved $($s.Width)x$($s.Height)"
$bmp.Dispose(); $s.Dispose()
