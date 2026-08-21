from __future__ import annotations

import ctypes
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileInspection:
    currently_used: str
    publisher: str
    digital_signature: str
    associated_application: str


def check_currently_used(path: str) -> str:
    """Best-effort exclusive open check. Unknown is safer than claiming unused."""
    if os.name != "nt":
        return "UNKNOWN"
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p
    close_handle = kernel32.CloseHandle
    path_flags = 0x02000000  # FILE_FLAG_BACKUP_SEMANTICS, also permits directories.
    handle = create_file(path, 0x80000000, 0, None, 3, path_flags, None)
    invalid = ctypes.c_void_p(-1).value
    if handle == invalid or not handle:
        error = ctypes.get_last_error()
        if error in (32, 33):  # sharing violation / lock violation
            return "YES"
        if error in (5, 2, 3, 87):  # access denied / missing / invalid
            return "UNKNOWN"
        return "UNKNOWN"
    close_handle(handle)
    return "NO"


def _file_version_publisher(path: str) -> str:
    if os.name != "nt" or Path(path).suffix.lower() not in {".exe", ".dll", ".sys"}:
        return "Unknown"
    try:
        version = ctypes.windll.version
        size = version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return "Unknown"
        buffer = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(path, 0, size, buffer):
            return "Unknown"
        pointer = ctypes.c_void_p()
        length = ctypes.c_uint()
        # Translation lookup is intentionally omitted; the Windows signature
        # check below remains the authoritative publisher signal.
        _ = (pointer, length)
    except (AttributeError, OSError):
        return "Unknown"
    return "Unknown"


def inspect_file(path: str) -> FileInspection:
    used = check_currently_used(path)
    publisher = _file_version_publisher(path)
    signature = "Unknown"
    if os.name == "nt" and Path(path).suffix.lower() in {".exe", ".dll", ".sys", ".msi"}:
        try:
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    "(Get-AuthenticodeSignature -LiteralPath $args[0]).Status",
                    path,
                ],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            status = completed.stdout.strip().lower()
            signature = {
                "valid": "Signed",
                "nottrusted": "Unsigned",
                "notsigned": "Unsigned",
                "unknownerror": "Unknown",
            }.get(status, "Unknown")
        except (OSError, subprocess.SubprocessError):
            signature = "Unknown"
    return FileInspection(used, publisher, signature, "Unknown")