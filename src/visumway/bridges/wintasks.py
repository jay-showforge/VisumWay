"""Task Scheduler definitions for the current interactive Windows account."""
from __future__ import annotations

import csv
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path, PureWindowsPath
from xml.sax.saxutils import escape

from ..proc import run_full

_TASK = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"


def registration_matches(name: str, home: Path, args: list) -> "bool | None":
    """Match a task's existing action to this one home. None means no task XML was found."""
    result = run_full(["schtasks", "/Query", "/TN", name, "/XML"], timeout=15)
    if result["rc"] != 0:
        return None
    try:
        root = ET.fromstring(result["stdout"])
        actions = root.find(_TASK + "Actions")
        if actions is None or len(actions) != 1 or actions[0].tag != _TASK + "Exec":
            return False
        command = actions[0].findtext(_TASK + "Command", "").strip('"')
        if PureWindowsPath(command).name.lower() not in ("python.exe", "pythonw.exe"):
            return False
        actual = actions[0].findtext(_TASK + "Arguments", "")
        expected = subprocess.list2cmdline(["-m", "visumway", "--home", str(home)] + args)
        legacy = '-m visumway --home "%s" %s' % (home, subprocess.list2cmdline(args))
        return actual in (expected, legacy)
    except (ValueError, ET.ParseError):
        return False


def user_sid() -> "str | None":
    result = run_full(["whoami", "/user", "/fo", "csv", "/nh"])
    row = next(csv.reader(result["stdout"].splitlines()), [])
    if result["rc"] == 0 and len(row) == 2 and row[1].startswith("S-1-"):
        return row[1]
    return None


def definition(python: str, argv: list, sid: str, subscription: "str | None" = None) -> str:
    if subscription is None:
        trigger = "<LogonTrigger><UserId>%s</UserId></LogonTrigger>" % escape(sid)
        policy = "IgnoreNew"
        # Some Windows installations do not retry an action started on demand.
        # A repeating OS trigger can recover a stopped runtime without launching
        # a second process when the scheduler already has an active instance.
        start = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(timespec="seconds")
        trigger += ('<TimeTrigger><Repetition><Interval>PT1M</Interval></Repetition>'
                    '<StartBoundary>%s</StartBoundary></TimeTrigger>' % start)
        runtime = ("<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>"
                   "<RestartOnFailure><Interval>PT1M</Interval><Count>3</Count></RestartOnFailure>")
    else:
        trigger = "<EventTrigger><Subscription>%s</Subscription></EventTrigger>" % escape(subscription)
        policy = "Queue"
        runtime = "<ExecutionTimeLimit>PT2M</ExecutionTimeLimit>"
    return """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>{trigger}</Triggers>
  <Principals><Principal id="VisumWay">
    <UserId>{sid}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel>
  </Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>{policy}</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    {runtime}
  </Settings>
  <Actions Context="VisumWay"><Exec><Command>{python}</Command><Arguments>{args}</Arguments></Exec></Actions>
</Task>
""".format(trigger=trigger, sid=escape(sid), policy=policy, runtime=runtime,
           python=escape(python), args=escape(subprocess.list2cmdline(argv)))
