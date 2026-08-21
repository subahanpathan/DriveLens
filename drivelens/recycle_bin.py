from __future__ import annotations

import os


def move_to_recycle_bin(path: str) -> None:
    """Move one path to the OS Recycle Bin; never permanently delete it."""
    if os.name != "nt":
        raise OSError("Recycle Bin deletion is only available on Windows.")
    from send2trash import send2trash

    send2trash(path)