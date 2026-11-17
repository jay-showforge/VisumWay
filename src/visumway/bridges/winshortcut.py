"""Unpackaged Windows toast shortcut installer (user-scoped, no dependencies).

Windows desktop toasts using an AUMID require a Start Menu .lnk whose
System.AppUserModel.ID property matches the notifier ID.  A bare registry
DisplayName entry is insufficient. The property is set with documented shell
COM interfaces via Windows PowerShell 5.1 and its built-in C# compiler.

The installer is exercised on Windows. Only VisumWay-owned links are replaced
or removed.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from .. import proc
from ..paths import Home

AUMID = "VisumWay.Agent"
SHORTCUT_NAME = "VisumWay Agent.lnk"

# Add-Type C# uses ShellLink + IPropertyStore + IPersistFile. There is no
# external package and no global registration or administrator requirement.
SCRIPT = r'''$ErrorActionPreference = 'Stop'
$src = @'
using System;
using System.Text;
using System.Runtime.InteropServices;
[StructLayout(LayoutKind.Sequential)] public struct PropertyKey {
    public Guid fmtid;
    public uint pid;
    public PropertyKey(Guid id, uint p) { fmtid = id; pid = p; }
}
[StructLayout(LayoutKind.Explicit)] public struct PropVariant {
    [FieldOffset(0)] public ushort vt;
    [FieldOffset(8)] public IntPtr pwszVal;
}
[ComImport, Guid("00021401-0000-0000-C000-000000000046")]
public class ShellLinkCom { }
[ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IShellLinkW {
    void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder name, int max, IntPtr data, uint flags);
    void GetIDList(out IntPtr pidl);
    void SetIDList(IntPtr pidl);
    void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder desc, int max);
    void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string desc);
    void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder dir, int max);
    void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string dir);
    void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder args, int max);
    void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string args);
    void GetHotkey(out short hotkey);
    void SetHotkey(short hotkey);
    void GetShowCmd(out int showcmd);
    void SetShowCmd(int showcmd);
    void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder icon, int max, out int index);
    void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string icon, int index);
    void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string rel, uint flags);
    void Resolve(IntPtr hwnd, uint flags);
    void SetPath([MarshalAs(UnmanagedType.LPWStr)] string path);
}
[ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IPropertyStore {
    void GetCount(out uint count);
    void GetAt(uint index, out PropertyKey key);
    void GetValue(ref PropertyKey key, out PropVariant value);
    void SetValue(ref PropertyKey key, ref PropVariant value);
    void Commit();
}
[ComImport, Guid("0000010b-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IPersistFile {
    void GetClassID(out Guid id);
    [PreserveSig] int IsDirty();
    void Load([MarshalAs(UnmanagedType.LPWStr)] string file, uint mode);
    void Save([MarshalAs(UnmanagedType.LPWStr)] string file, [MarshalAs(UnmanagedType.Bool)] bool remember);
    void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string file);
    void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string file);
}
public static class AppShortcut {
    public static void Create(string path, string target, string args, string aumid) {
        var link = new ShellLinkCom();
        try {
            ((IShellLinkW)link).SetPath(target);
            ((IShellLinkW)link).SetArguments(args);
            var store = (IPropertyStore)link;
            var key = new PropertyKey(new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 5);
            var value = new PropVariant { vt = 31, pwszVal = Marshal.StringToCoTaskMemUni(aumid) };
            try {
                store.SetValue(ref key, ref value);
                store.Commit();
                ((IPersistFile)link).Save(path, true);
            } finally { Marshal.FreeCoTaskMem(value.pwszVal); }
        } finally { Marshal.FinalReleaseComObject(link); }
    }
}
'@
Add-Type -TypeDefinition $src -Language CSharp
[AppShortcut]::Create($env:VISUMWAY_SHORTCUT, $env:VISUMWAY_TARGET,
                      $env:VISUMWAY_TARGET_ARGS, $env:VISUMWAY_AUMID)
'''


def shortcut_path(appdata: "str | None" = None) -> Path:
    appdata = appdata or os.environ.get("APPDATA")
    if not appdata:
        # Only run registration on Windows, where APPDATA should exist.
        raise RuntimeError("APPDATA is missing; user Start Menu unavailable")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / SHORTCUT_NAME


def install(home: Home, aumid: str = AUMID, runner=proc.run_full) -> dict:
    path = shortcut_path()
    if path.exists() and not _owns_shortcut(home, path):
        return {"ok": False, "error": "a Start Menu shortcut already exists outside this installation"}
    path.parent.mkdir(parents=True, exist_ok=True)
    script = home.state / "windows-toast-shortcut.ps1"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(SCRIPT, encoding="utf-8")
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    target = str(pythonw if pythonw.exists() else python)
    args = '-m visumway --home "%s" status' % str(home.root).replace('"', '')
    try:
        with tempfile.TemporaryDirectory(prefix=".visumway-", dir=path.parent) as directory:
            staged = Path(directory) / path.name
            env = dict(os.environ, VISUMWAY_SHORTCUT=str(staged), VISUMWAY_TARGET=target,
                       VISUMWAY_TARGET_ARGS=args, VISUMWAY_AUMID=aumid)
            result = runner(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-File", str(script)], timeout=60, env=env)
            if result.get("rc") != 0 or not staged.is_file():
                return {"ok": False, "error": result.get("stderr", "")[:300] or "Start Menu shortcut not created"}
            staged.replace(path)
    finally:
        script.unlink(missing_ok=True)
    marker = home.state / "windows-shortcut.json"
    marker.write_text(json.dumps({"path": str(path), "aumid": aumid}), encoding="utf-8")
    return {"ok": True, "path": str(path)}


def _owns_shortcut(home: Home, path: Path) -> bool:
    try:
        marker = json.loads((home.state / "windows-shortcut.json").read_text(encoding="utf-8"))
        return isinstance(marker, dict) and marker.get("aumid") == AUMID and marker.get("path") == str(path)
    except (FileNotFoundError, ValueError):
        return False


def registered(home: Home) -> bool:
    try:
        path = shortcut_path()
        return path.is_file() and _owns_shortcut(home, path)
    except (OSError, RuntimeError):
        return False


def remove(home: Home) -> list:
    marker = home.state / "windows-shortcut.json"
    try:
        p = shortcut_path()
        if not _owns_shortcut(home, p):
            return []
        p.unlink(missing_ok=True)
        marker.unlink(missing_ok=True)
        return ["removed VisumWay-owned Start Menu shortcut"]
    except (OSError, RuntimeError) as error:
        return ["FAILED: could not remove Windows notification shortcut: %s" % error]
