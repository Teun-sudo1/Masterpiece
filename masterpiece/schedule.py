"""'Masterpiece rotation': a Windows scheduled task that runs `masterpiece next`.

- Runs as the current user, only while logged on, without a console window (pythonw).
- Triggers: at logon (+30 s) and every N minutes; missed runs catch up when the PC wakes.
- Remove it with the Stop button in the app, or:  schtasks /Delete /TN Masterpiece /F
"""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

TASK = "Masterpiece"
INTERVALS = {10: "Every 10 minutes", 30: "Every 30 minutes", 60: "Every hour",
             180: "Every 3 hours", 1440: "Once a day"}
_NO_WINDOW = 0x08000000   # CREATE_NO_WINDOW


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *args], capture_output=True, text=True,
                          creationflags=_NO_WINDOW if sys.platform == "win32" else 0)


def _duration(minutes: int) -> str:
    return "P1D" if minutes >= 1440 else f"PT{max(1, minutes)}M"


def task_xml(minutes: int) -> str:
    user = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".lstrip("\\")
    start = (dt.datetime.now() + dt.timedelta(minutes=1)).replace(microsecond=0).isoformat()
    from .desktop import launcher
    program, arguments, workdir = launcher("next")
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Masterpiece: show the next public-domain painting as wallpaper.</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{escape(user)}</UserId>
      <Delay>PT30S</Delay>
    </LogonTrigger>
    <TimeTrigger>
      <Enabled>true</Enabled>
      <StartBoundary>{start}</StartBoundary>
      <Repetition>
        <Interval>{_duration(minutes)}</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(program)}</Command>
      <Arguments>{escape(arguments)}</Arguments>
      <WorkingDirectory>{escape(str(workdir))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def enable(minutes: int, name: str = TASK) -> None:
    if sys.platform != "win32":
        raise OSError("Scheduling is only supported on Windows")
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-16") as f:
        f.write(task_xml(minutes))
        path = f.name
    try:
        r = _run("/Create", "/F", "/TN", name, "/XML", path)
        if r.returncode:
            raise OSError((r.stderr or r.stdout).strip() or "schtasks failed")
    finally:
        os.unlink(path)


def relink(minutes: int, name: str = TASK) -> bool:
    """After an update or a move: point an existing rotation at this copy of Masterpiece
    (same interval, paused stays paused). Returns True if there was one."""
    st = status(name)
    if not st.get("active"):
        return False
    enable(minutes, name)
    if st.get("paused"):
        pause(name)
    return True


def disable(name: str = TASK) -> None:
    if sys.platform == "win32" and status(name)["active"]:
        _run("/Delete", "/F", "/TN", name)


def pause(name: str = TASK) -> None:
    """Keep the rotation set up, but stop changing paintings for now."""
    if sys.platform == "win32":
        _run("/Change", "/TN", name, "/DISABLE")


def resume(name: str = TASK) -> None:
    if sys.platform == "win32":
        _run("/Change", "/TN", name, "/ENABLE")


def status(name: str = TASK) -> dict:
    if sys.platform != "win32":
        return {"active": False}
    r = _run("/Query", "/TN", name, "/FO", "LIST", "/V")
    if r.returncode:
        return {"active": False}
    info = {}
    for line in r.stdout.splitlines():
        k, sep, v = line.partition(":")
        if sep:
            info[k.strip()] = v.strip()
    paused = any(v.lower() == "disabled" for k, v in info.items() if "state" in k.lower())
    return {"active": True, "paused": paused,
            "nextRun": "" if paused else info.get("Next Run Time", ""), "lastRun": info.get("Last Run Time", "")}
