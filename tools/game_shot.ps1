# Capture only the Rome2 window to a PNG (for checking the game by sight in unattended runs). PrintWindow with
# PW_RENDERFULLCONTENT; CopyFromScreen returns black for the game's client area.
#   game_shot.ps1 -Out shot.png
param([Parameter(Mandatory = $true)][string]$Out)
Add-Type -AssemblyName System.Drawing
Add-Type -Name W -Namespace IA -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
[DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint f);
public struct RECT { public int L, T, R, B; }
'@
$h = (Get-Process Rome2).MainWindowHandle
$r = New-Object IA.W+RECT; [void][IA.W]::GetWindowRect($h, [ref]$r)
$bmp = New-Object System.Drawing.Bitmap ($r.R - $r.L), ($r.B - $r.T)
$g = [System.Drawing.Graphics]::FromImage($bmp); $dc = $g.GetHdc()
$ok = [IA.W]::PrintWindow($h, $dc, 2); $g.ReleaseHdc($dc)
# Exclusive fullscreen: PrintWindow gives an all-black image, but a screen copy works (2026-11-08, 2560x1440).
$black = $true
for ($x = 1; $x -lt 8 -and $black; $x++) { for ($y = 1; $y -lt 8; $y++) {
	$p = $bmp.GetPixel([int]($bmp.Width * $x / 8), [int]($bmp.Height * $y / 8)); if ($p.R + $p.G + $p.B -gt 30) { $black = $false; break } } }
$how = "printwindow=$ok"
if ($black) {
	$g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size); $how = "screen_copy (printwindow black)"
}
$s = New-Object System.Drawing.Bitmap $bmp, 968, ([int](968 * $bmp.Height / $bmp.Width))
$s.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png); $g.Dispose(); $bmp.Dispose(); $s.Dispose()
"$how $($r.R - $r.L)x$($r.B - $r.T)"
