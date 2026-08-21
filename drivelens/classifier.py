from __future__ import annotations

import os
import re

from .models import Category, Classification, DeletionRisk, ItemKind


WINDOWS_ROOTS = (
    r"c:\windows",
    r"c:\programdata\microsoft",
    r"c:\$recycle.bin",
    r"c:\recovery",
    r"c:\boot",
    r"c:\efi",
)

SYSTEM_EXTENSIONS = {
    ".dll",
    ".sys",
    ".ocx",
    ".cpl",
    ".mui",
    ".cat",
    ".efi",
}

DRIVER_MARKERS = (
    r"\system32\drivers",
    r"\driverstore",
)

DOWNLOAD_MARKERS = (
    r"\downloads",
    r"\desktop",
)

USER_MARKERS = (
    r"\documents",
    r"\pictures",
    r"\videos",
    r"\music",
)

TEMP_MARKERS = (
    r"\temp",
    r"\appdata\local\temp",
    r"\cache",
    r"\code cache",
    r"\shadercache",
    r"\crashdumps",
)

APP_MARKERS = (
    r"\program files",
    r"\program files (x86)",
    r"\programdata",
    r"\appdata\local\programs",
)

DEV_MARKERS = (
    r"\node_modules",
    r"\.git",
    r"\python",
    r"\visual studio",
    r"\android\sdk",
    r"\dotnet",
    r"\rustup",
)

ARCHIVE_EXTENSIONS = {
    ".zip",
    ".7z",
    ".rar",
    ".tar",
    ".gz",
    ".iso",
}

MEDIA_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".mp4",
    ".mkv",
    ".mov",
    ".mp3",
    ".wav",
    ".flac",
}

DOCUMENT_EXTENSIONS = {
    ".doc",
    ".docx",
    ".pdf",
    ".txt",
    ".csv",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
}

SCRIPT_EXTENSIONS = {
    ".bat",
    ".cmd",
    ".ps1",
    ".vbs",
    ".js",
    ".jse",
    ".scr",
}

EXECUTABLE_EXTENSIONS = {
    ".exe",
    ".msi",
    ".com",
    ".dll",
    ".sys",
}

DOUBLE_EXTENSION = re.compile(
    r"\.(pdf|docx?|xlsx?|jpg|jpeg|png|txt)\."
    r"(exe|scr|bat|cmd|js|vbs|ps1)$",
    re.IGNORECASE,
)


def _normalise(path: str) -> str:
    raw = str(path)

    if len(raw) >= 2 and raw[1] == ":":
        absolute = raw
    else:
        absolute = os.path.abspath(raw)

    return os.path.normcase(absolute).replace("/", "\\").lower()


def _basename(path: str) -> str:
    return path.replace("/", "\\").rsplit("\\", 1)[-1]


def _extension(path: str) -> str:
    name = _basename(path)

    if "." not in name:
        return ""

    return "." + name.rsplit(".", 1)[-1].lower()


def _under(path: str, marker: str) -> bool:
    normal = _normalise(path)
    marker = _normalise(marker).rstrip("\\")

    return normal == marker or normal.startswith(marker + "\\")


def classify(
    path: str,
    kind: ItemKind,
    size: int = 0,
) -> Classification:

    normal = _normalise(path)
    lower_name = _basename(path).lower()
    extension = _extension(path)

    is_file = kind == ItemKind.FILE

    is_windows = any(
        _under(normal, marker)
        for marker in WINDOWS_ROOTS
    )

    is_driver = any(
        marker in normal
        for marker in DRIVER_MARKERS
    )

    is_temp = any(
        marker in normal
        for marker in TEMP_MARKERS
    )

    is_app = any(
        marker in normal
        for marker in APP_MARKERS
    )

    is_download = any(
        marker in normal
        for marker in DOWNLOAD_MARKERS
    )

    is_user = any(
        marker in normal
        for marker in USER_MARKERS
    )

    is_dev = any(
        marker in normal
        for marker in DEV_MARKERS
    )

    protected = is_windows or is_driver

    # ---------------------------------------------------------
    # SUSPICIOUS DOUBLE EXTENSION
    # ---------------------------------------------------------

    if DOUBLE_EXTENSION.search(lower_name):

        return Classification(
            Category.SUSPICIOUS,
            "A file with a document-like name also has an executable or script extension.",
            "UNKNOWN",
            "Unknown",
            DeletionRisk.HIGH,
            "REVIEW",
            82,
            "The filename resembles a document but ends with an executable or script extension. This is only a review signal, not malware detection.",
        )

    # ---------------------------------------------------------
    # WINDOWS / DRIVER
    # ---------------------------------------------------------

    if is_driver or (
        is_windows and extension in SYSTEM_EXTENSIONS
    ):

        return Classification(
            Category.DRIVER if is_driver else Category.WINDOWS_SYSTEM,
            "A Windows driver or low-level Windows component.",
            "YES",
            "Windows",
            DeletionRisk.CRITICAL,
            "NO",
            96 if is_driver else 93,
            "The location and extension match protected Windows or driver locations.",
            True,
        )

    if is_windows:

        return Classification(
            Category.WINDOWS_SYSTEM,
            "A file or folder inside a Windows-managed location.",
            "YES",
            "Windows",
            DeletionRisk.CRITICAL,
            "NO",
            90,
            "The path is inside a Windows-managed or recovery location.",
            True,
        )

    # ---------------------------------------------------------
    # TEMPORARY / CACHE
    # ---------------------------------------------------------

    if is_temp:

        risk = (
            DeletionRisk.LOW
            if size < 500 * 1024 * 1024
            else DeletionRisk.MEDIUM
        )

        return Classification(
            Category.TEMPORARY,
            "Temporary, cache, crash-dump, or generated application data.",
            "NO",
            "Unknown",
            risk,
            "YES" if is_file else "REVIEW",
            86,
            "The path matches a known temporary or cache directory. Applications can normally recreate many such files.",
        )

    # ---------------------------------------------------------
    # DEVELOPMENT
    # ---------------------------------------------------------

    if is_dev:

        return Classification(
            Category.DEVELOPMENT,
            "Files belonging to development tools, SDKs, source trees, or package caches.",
            "NO",
            "Development tooling",
            DeletionRisk.MEDIUM,
            "REVIEW",
            78,
            "The path matches a development-tool directory. Removing it may affect a project.",
        )

    # ---------------------------------------------------------
    # INSTALLED APPLICATION
    # ---------------------------------------------------------

    if is_app:

        return Classification(
            Category.INSTALLED_APPLICATION,
            "Files installed or managed by a desktop application.",
            "NO",
            "Installed application",
            DeletionRisk.HIGH,
            "REVIEW",
            88,
            "The path is under a conventional application installation or application-data directory. Uninstalling the application is safer than manually deleting files.",
        )

    # ---------------------------------------------------------
    # DOWNLOADED EXECUTABLE
    # ---------------------------------------------------------

    if (
        is_download
        and is_file
        and extension in (
            SCRIPT_EXTENSIONS | EXECUTABLE_EXTENSIONS
        )
    ):

        return Classification(
            Category.SUSPICIOUS,
            "An executable or script in a user download or desktop location.",
            "UNKNOWN",
            "Unknown",
            DeletionRisk.MEDIUM,
            "REVIEW",
            74,
            "The file can execute code and is located in a user download location. This is not malware detection.",
        )

    # ---------------------------------------------------------
    # DOWNLOADS
    # ---------------------------------------------------------

    if is_download:

        return Classification(
            Category.DOWNLOADED,
            "A file in a common Downloads or Desktop location.",
            "NO",
            "User-managed",
            DeletionRisk.LOW,
            "YES" if is_file else "REVIEW",
            84,
            "The path is inside Downloads or Desktop. The application cannot know whether the user still needs the file.",
        )

    # ---------------------------------------------------------
    # USER FILES
    # ---------------------------------------------------------

    if (
        is_user
        or (
            is_file
            and extension in (
                DOCUMENT_EXTENSIONS
                | MEDIA_EXTENSIONS
                | ARCHIVE_EXTENSIONS
            )
        )
    ):

        return Classification(
            Category.USER_FILE,
            "Personal documents, media, archives, or other user-created data.",
            "NO",
            "User-managed",
            DeletionRisk.MEDIUM,
            "YES" if is_file else "REVIEW",
            72 if is_user else 61,
            "The path or file type resembles user-created data. DriveLens cannot determine whether you still need it.",
        )

    # ---------------------------------------------------------
    # LARGE UNKNOWN FILE
    # ---------------------------------------------------------

    if is_file and size >= 500 * 1024 * 1024:

        return Classification(
            Category.USER_FILE,
            "Large file that may be consuming significant storage.",
            "UNKNOWN",
            "Unknown",
            DeletionRisk.MEDIUM,
            "REVIEW",
            55,
            "This file is larger than 500 MB, but its purpose could not be established safely. Review it before deleting.",
        )

    # ---------------------------------------------------------
    # UNKNOWN EXECUTABLE
    # ---------------------------------------------------------

    if is_file and extension in EXECUTABLE_EXTENSIONS:

        return Classification(
            Category.UNKNOWN,
            "An executable or system-like file whose origin could not be established.",
            "UNKNOWN",
            "Unknown",
            DeletionRisk.HIGH,
            "REVIEW",
            58,
            "The file type is significant, but its location does not establish whether it belongs to Windows, an installed application, or a download.",
        )

    # ---------------------------------------------------------
    # UNKNOWN
    # ---------------------------------------------------------

    return Classification(
        Category.UNKNOWN,
        "The purpose could not be established from local path and file metadata.",
        "UNKNOWN",
        "Unknown",
        DeletionRisk.MEDIUM,
        "REVIEW",
        35,
        "Unknown — insufficient evidence. No strong local evidence matched a safer classification.",
    )