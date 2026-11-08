# Send a key straight to the Rome 2 window (no focus needed).   post_key.ps1 [-Vk 0x1B] [-Wait 2]
param([int]$Vk = 0x1B, [double]$Wait = 1)
if (-not ('PK' -as [type])) { Add-Type @'
using System; using System.Runtime.InteropServices; using System.Threading;
public class PK { [DllImport("user32.dll")] static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  public static void Key(IntPtr h, int vk) { PostMessage(h, 0x100, (IntPtr)vk, (IntPtr)1); Thread.Sleep(60); PostMessage(h, 0x101, (IntPtr)vk, (IntPtr)unchecked((int)0xC0000001)); } }
'@ }
$p = Get-Process Rome2 | Where-Object { $_.MainWindowTitle -eq 'Total War: ROME 2' } | Select-Object -First 1
if (-not $p) { throw 'no Rome2 main window' }
[PK]::Key($p.MainWindowHandle, $Vk)
Start-Sleep -Seconds $Wait
