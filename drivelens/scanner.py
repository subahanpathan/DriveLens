from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from .classifier import classify
from .models import Classification, ItemKind
from .store import ScanStore


@dataclass
class _DirectoryFrame:
    path: str
    iterator: os.ScandirIterator
    size: int = 0
    file_count: int = 0
    folder_count: int = 0


def _timestamp(value: float) -> str:
    try:
        return datetime.fromtimestamp(value).isoformat(sep=" ", timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return "Unknown"


def _is_reparse_point(entry: os.DirEntry) -> bool:
    try:
        attributes = entry.stat(follow_symlinks=False).st_file_attributes
        return bool(attributes & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
    except (AttributeError, OSError):
        return entry.is_symlink()


class ScanWorker(QObject):
    progress = Signal(dict)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, database_path: str, root: str = "C:\\"):
        super().__init__()
        self.database_path = database_path
        self.root = root
        self.cancel_requested = False
        self._last_update = 0.0
        self._scan_order = 0
        self._files = 0
        self._folders = 0
        self._size = 0
        self._inaccessible = 0
        self._current_path = self.root

    def cancel(self) -> None:
        self.cancel_requested = True

    @Slot()
    def run(self) -> None:
        store = ScanStore(self.database_path)
        try:
            store.clear()
            if not os.path.isdir(self.root):
                raise RuntimeError(f"Drive path was not found: {self.root}")
            self._scan_directory(store, self.root, is_root=True)
            store.commit()
            self._emit_progress(store, force=True)
            self.finished.emit("cancelled" if self.cancel_requested else "complete")
        except Exception as error:
            try:
                store.commit()
            except sqlite3.Error:
                pass
            self.failed.emit(str(error))
        finally:
            store.close()

    def _scan_directory(self, store: ScanStore, path: str, is_root: bool = False) -> None:
        if self.cancel_requested:
            return
        if not is_root and _is_reparse_path(path):
            return
        classification = classify(path, ItemKind.FOLDER)
        self._insert(store, path, ItemKind.FOLDER, 0, 0, 0, classification, None)
        try:
            iterator = os.scandir(path)
        except OSError as error:
            self._record_inaccessible(store, path, error)
            return

        stack = [_DirectoryFrame(path, iterator)]
        while stack and not self.cancel_requested:
            frame = stack[-1]
            try:
                entry = next(frame.iterator)
            except StopIteration:
                frame.iterator.close()
                store.connection.execute(
                    "UPDATE items SET size=?, file_count=?, folder_count=? WHERE path=?",
                    (frame.size, frame.file_count, frame.folder_count, frame.path)
                )
                stack.pop()
                if stack:
                    stack[-1].size += frame.size
                    stack[-1].file_count += frame.file_count
                    stack[-1].folder_count += frame.folder_count + 1
                self._emit_progress(store)
                continue
            except OSError as error:
                self._record_inaccessible(store, frame.path, error)
                frame.iterator.close()
                stack.pop()
                continue

            item_path = entry.path
            self._current_path = item_path
            try:
                if entry.is_dir(follow_symlinks=False):
                    classification = classify(item_path, ItemKind.FOLDER)
                    self._insert(store, item_path, ItemKind.FOLDER, 0, 0, 0, classification, entry)
                    self._folders += 1
                    if not _is_reparse_point(entry):
                        try:
                            stack.append(_DirectoryFrame(item_path, os.scandir(item_path)))
                        except OSError as error:
                            self._record_inaccessible(store, item_path, error)
                    self._emit_progress(store)
                else:
                    stat = entry.stat(follow_symlinks=False)
                    size = int(getattr(stat, "st_size", 0) or 0)
                    classification = classify(item_path, ItemKind.FILE, size)
                    self._insert(store, item_path, ItemKind.FILE, size, 0, 0, classification, entry)
                    frame.size += size
                    frame.file_count += 1
                    self._files += 1
                    self._size += size
                    self._emit_progress(store)
            except (OSError, ValueError) as error:
                self._record_inaccessible(store, item_path, error)

        while stack:
            stack[-1].iterator.close()
            stack.pop()

    def _insert(
        self,
        store: ScanStore,
        path: str,
        kind: ItemKind,
        size: int,
        file_count: int,
        folder_count: int,
        classification: Classification,
        entry: os.DirEntry | None,
    ) -> None:
        self._scan_order += 1
        created = ""
        modified = ""
        if entry is not None:
            try:
                stat = entry.stat(follow_symlinks=False)
                created = _timestamp(getattr(stat, "st_ctime", 0))
                modified = _timestamp(getattr(stat, "st_mtime", 0))
            except OSError:
                pass
        store.insert_item(
            (
                path,
                os.path.dirname(path),
                Path(path).name or path,
                kind.value,
                size,
                file_count,
                folder_count,
                created,
                modified,
                classification.category,
                classification.purpose,
                classification.windows_required,
                "UNKNOWN",
                classification.associated_application,
                "Unknown",
                "Unknown",
                classification.deletion_risk,
                classification.can_delete,
                classification.confidence,
                classification.reason,
                int(classification.is_protected),
                self._scan_order,
            )
        )

    def _record_inaccessible(self, store: ScanStore, path: str, error: BaseException) -> None:
        self._inaccessible += 1
        store.add_inaccessible(path, f"{type(error).__name__}: {error}")
        self._emit_progress(store)

    def _emit_progress(self, store: ScanStore, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_update < 0.20:
            return
        self._last_update = now
        store.commit()
        self.progress.emit(
            {
                "files": self._files,
                "folders": self._folders,
                "total_size": self._size,
                "inaccessible": self._inaccessible,
                "current_path": self._current_path,
                "cancelled": self.cancel_requested,
            }
        )


def _is_reparse_path(path: str) -> bool:
    try:
        attributes = os.stat(path, follow_symlinks=False).st_file_attributes
        return bool(attributes & 0x400)
    except (AttributeError, OSError):
        return os.path.islink(path)