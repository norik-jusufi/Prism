"""PRISM tab memory monitor: per-process memory on Windows via the Win32 API
(ctypes only, no extra packages). Elsewhere it falls back to /proc or nothing."""

from __future__ import annotations

import ctypes
import os
import sys

WIN = sys.platform == "win32"

if WIN:
    from ctypes import wintypes

    class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):  # noqa: N801
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t)]

    class PROCESSENTRY32W(ctypes.Structure):  # noqa: N801
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    _k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    _k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    TH32CS_SNAPPROCESS = 0x2


def process_memory(pid: int) -> dict | None:
    """{'workingSet': bytes, 'private': bytes} for one process, or None."""
    if not pid:
        return None
    if WIN:
        h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return None
        try:
            c = PROCESS_MEMORY_COUNTERS_EX()
            c.cb = ctypes.sizeof(c)
            if not _k32.K32GetProcessMemoryInfo(h, ctypes.byref(c), c.cb):
                return None
            return {"workingSet": c.WorkingSetSize, "private": c.PrivateUsage}
        finally:
            _k32.CloseHandle(h)
    try:  # Linux
        with open(f"/proc/{pid}/status", encoding="ascii") as f:
            vals = dict(line.split(":", 1) for line in f if ":" in line)
        rss = int(vals["VmRSS"].split()[0]) * 1024
        return {"workingSet": rss, "private": rss}
    except (OSError, KeyError, ValueError):
        return None


def child_processes(parent: int | None = None) -> list[dict]:
    """Every process started by PRISM (GPU, network, renderers, utilities)."""
    parent = parent or os.getpid()
    if not WIN:
        return []
    snap = _k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    found: list[dict] = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = _k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.th32ParentProcessID == parent:
                found.append({"pid": entry.th32ProcessID, "exe": entry.szExeFile})
            ok = _k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        _k32.CloseHandle(snap)
    return found
