"""The painting on the Windows lock screen too (optional, setting "lockScreen").

Uses Windows' own API (Windows.System.UserProfile.LockScreen) through PowerShell, so no
extra packages are needed. Before the first change, the current lock-screen picture is
saved, and restore() puts it back ("Restore my wallpaper" or switching the option off).

Note: with "Windows spotlight" as lock-screen background, Windows switches to "Picture";
restore() then puts back the last spotlight picture, but Spotlight itself has to be
switched on again in Settings → Personalisation → Lock screen.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import cache

_NO_WINDOW = 0x08000000

_PRELUDE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.System.UserProfile.LockScreen, Windows.System.UserProfile, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStreamWithContentType, Windows.Storage.Streams, ContentType = WindowsRuntime]
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
$asTaskAction = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' } | Select-Object -First 1
function Await($op, [Type]$type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(); $t.Result }
function AwaitAction($op) { $t = $asTaskAction.Invoke($null, @($op)); $t.Wait() }
"""

_SET = _PRELUDE + r"""
$f = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($env:MP_PATH)) ([Windows.Storage.StorageFile])
AwaitAction ([Windows.System.UserProfile.LockScreen]::SetImageFileAsync($f))
"""

_SAVE_CURRENT = _PRELUDE + r"""
$s = [Windows.System.UserProfile.LockScreen]::GetImageStream()
if ($s -eq $null) { exit 3 }
$in = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($s)
$out = [System.IO.File]::Create($env:MP_PATH); $in.CopyTo($out); $out.Close(); $in.Close()
"""


def _dir() -> Path:
    return cache.cache_dir().parent / "lockscreen"


def _ps(script: str, path: str) -> None:
    if sys.platform != "win32":
        raise OSError("The lock screen can only be set on Windows")
    # The path goes in through an environment variable, never pasted into the script
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-Command", script],
                       capture_output=True, text=True, timeout=60, creationflags=_NO_WINDOW,
                       env={**os.environ, "MP_PATH": path})
    if r.returncode:
        raise OSError((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip()
                      else f"PowerShell exit {r.returncode}")


def backup_path() -> Path:
    return _dir() / "previous.jpg"


def has_backup() -> bool:
    return backup_path().exists()


def _capture_previous() -> None:
    """Save the user's own lock-screen picture once, before Masterpiece first changes it."""
    if has_backup() or cache.kv().get("lockscreen:ours", 1e12):
        return
    _dir().mkdir(parents=True, exist_ok=True)
    try:
        _ps(_SAVE_CURRENT, str(backup_path()))
    except OSError:
        backup_path().unlink(missing_ok=True)       # nothing to save (e.g. never set)


def set_image(src: Path) -> Path:
    """Put `src` on the lock screen. A copy is kept (Windows reads the file)."""
    _capture_previous()
    d = _dir()
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"lock-{int(time.time())}{src.suffix.lower() or '.jpg'}"
    shutil.copyfile(src, dest)
    _ps(_SET, str(dest))
    cache.kv().set("lockscreen:ours", str(dest))
    for old in d.glob("lock-*"):                    # keep only the current one
        if old != dest:
            old.unlink(missing_ok=True)
    return dest


def is_ours() -> bool:
    return bool(cache.kv().get("lockscreen:ours", 1e12))


def restore() -> bool:
    """Put the user's own lock-screen picture back. True if something was restored."""
    if not is_ours():
        return False
    restored = False
    if has_backup():
        _ps(_SET, str(backup_path()))
        restored = True
    cache.kv().set("lockscreen:ours", "")
    for old in _dir().glob("lock-*"):
        old.unlink(missing_ok=True)
    return restored
