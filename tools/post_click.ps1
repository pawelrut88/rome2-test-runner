# Click inside the Rome 2 window by posting mouse messages to it (injected mouse input is unreliable in this game).
# Coordinates are client pixels (windowed 1920x1080 at 0,0).   post_click.ps1 -X 35 -Y 575 [-Wait 2]
param([int]$X, [int]$Y, [double]$Wait = 1, [string]$Process = "Rome2", [string]$Title = "Total War: ROME 2")
if (-not ('PC' -as [type])) { Add-Type @'
using System; using System.Runtime.InteropServices; using System.Threading;
public class PC { [DllImport("user32.dll")] static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  public static void Click(IntPtr h, int x, int y) { IntPtr lp = (IntPtr)((y << 16) | (x & 0xFFFF));
    PostMessage(h, 0x200, IntPtr.Zero, lp); Thread.Sleep(250); PostMessage(h, 0x200, IntPtr.Zero, lp); Thread.Sleep(250);
    PostMessage(h, 0x201, (IntPtr)1, lp); Thread.Sleep(150); PostMessage(h, 0x202, IntPtr.Zero, lp); } }
'@ }
$p = Get-Process $Process -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 -and ($Title -eq '*' -or $_.MainWindowTitle -eq $Title) } | Select-Object -First 1
if (-not $p) { throw "no $Process main window" }
# the real cursor must hover too: campaign list entries ignore posted clicks otherwise. Client -> screen: +8, +31 (windowed at 0,0)
[PC]::SetCursorPos($X + 8, $Y + 31) | Out-Null; Start-Sleep -Milliseconds 400
[PC]::Click($p.MainWindowHandle, $X, $Y)
Start-Sleep -Seconds $Wait
