# pt_accept.ps1 -- automated "does Packet Tracer accept this .pkt?" harness.
#
# Packet Tracer 9.0.0 shows a small window titled
#     "Incompatible File -- Cisco Packet Tracer"
# when it refuses a file. If the file loads, the main window title becomes
#     "Cisco Packet Tracer - C:\...\your.pkt"
# so we just enumerate window titles and grep for "Incompatible File".
#
# Usage (from pkt_create/):
#     powershell -NoProfile -ExecutionPolicy Bypass -File tools\pt_accept.ps1 -File .\8lab.pkt
#
# Exit code: 0 = ACCEPTED, 1 = REJECTED, 2 = PT not found.
# The script kills any running Packet Tracer first, and kills it afterwards.

param(
    [Parameter(Mandatory = $true)][string]$File,
    [int]$Wait = 55
)

$File = (Resolve-Path -LiteralPath $File).Path

$pt = @(
    'C:\Program Files\Cisco Packet Tracer 9.0.0\bin\PacketTracer.exe',
    'C:\Program Files\Cisco Packet Tracer 8.2.2\bin\PacketTracer.exe',
    'C:\Program Files (x86)\Cisco Packet Tracer 8.2.2\bin\PacketTracer.exe'
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

if (-not $pt) { Write-Output 'PacketTracer.exe not found'; exit 2 }

Get-Process -Name PacketTracer -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 3

Start-Process -FilePath $pt -ArgumentList ('"' + $File + '"')
Start-Sleep -Seconds $Wait

Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class WinEnum {
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  public delegate bool EnumWindowsProc(IntPtr h, IntPtr l);
  public static string All() {
    var sb = new StringBuilder();
    EnumWindows((h, l) => {
      if (IsWindowVisible(h)) {
        var t = new StringBuilder(512);
        GetWindowText(h, t, 512);
        if (t.Length > 0) sb.AppendLine(t.ToString());
      }
      return true;
    }, IntPtr.Zero);
    return sb.ToString();
  }
}
"@

$titles = [WinEnum]::All()
Write-Output '=== VISIBLE WINDOW TITLES ==='
Write-Output $titles

Get-Process -Name PacketTracer -ErrorAction SilentlyContinue | Stop-Process -Force

if ($titles -match 'Incompatible File') {
    Write-Output 'VERDICT: REJECTED'
    exit 1
}

if ($titles -match [regex]::Escape((Split-Path -Leaf $File))) {
    Write-Output 'VERDICT: ACCEPTED (file name appears in the main window title)'
} else {
    Write-Output 'VERDICT: ACCEPTED (no "Incompatible File" window)'
}
exit 0
