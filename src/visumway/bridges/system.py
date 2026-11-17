"""System bridge: cheap, dependency-free facts about the running machine."""
from __future__ import annotations

import csv
import io
import os

from ..proc import run


def list_processes() -> list:
    """[{pid, name}] for running processes, using whatever the OS offers."""
    out = []
    if os.path.isdir("/proc/self"):
        for entry in os.listdir("/proc"):
            if entry.isdigit():
                try:
                    with open("/proc/%s/comm" % entry, encoding="utf-8", errors="replace") as f:
                        out.append({"pid": int(entry), "name": f.read().strip()})
                except OSError:
                    continue
        return out
    if os.name == "nt":
        for row in csv.reader(io.StringIO(run(["tasklist", "/fo", "csv", "/nh"]))):
            if len(row) >= 2 and row[1].isdigit():
                out.append({"pid": int(row[1]), "name": row[0]})
        if not out:
            command = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
                       "Get-Process | ForEach-Object { '{0} {1}' -f $_.Id, $_.ProcessName }")
            for line in run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]).splitlines():
                pid, _, name = line.partition(" ")
                if pid.isdigit() and name:
                    out.append({"pid": int(pid), "name": name})
        return out
    for line in run(["ps", "-axo", "pid=,comm="]).splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            out.append({"pid": int(parts[0]), "name": os.path.basename(parts[1])})
    return out
