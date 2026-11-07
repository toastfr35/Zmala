"""Preflight both Linux free space and WSL's physical VHD backing volume."""
import os
from pathlib import Path
import shutil
import subprocess


def available(folder):
    free = shutil.disk_usage(folder).free
    distro = os.environ.get('WSL_DISTRO_NAME')
    kernel = Path('/proc/sys/kernel/osrelease')
    if kernel.is_file() and 'microsoft' in kernel.read_text().lower():
        if not distro or not shutil.which('powershell.exe'):
            raise ValueError('Cannot verify the Windows volume backing this WSL build')
        # Literal PowerShell quoting, never interpolate an unescaped distro name.
        literal = "'"+distro.replace("'", "''")+"'"
        script = ("$ErrorActionPreference='Stop'; $entry=Get-ChildItem "
                  "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Lxss | "
                  "ForEach-Object {Get-ItemProperty $_.PSPath} | "
                  "Where-Object {$_.DistributionName -eq "+literal+"}; "
                  "if (@($entry).Count -ne 1) {throw 'Ambiguous build distro'}; "
                  "$drive=[IO.Path]::GetPathRoot($entry.BasePath).Substring(0,1); "
                  "(Get-PSDrive -Name $drive).Free")
        raw = subprocess.check_output(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                      timeout=30, text=True).strip()
        if not raw.isdecimal():
            raise ValueError('Cannot verify physical WSL backing-volume capacity')
        free = min(free, int(raw))
    return free
