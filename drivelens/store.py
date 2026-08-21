from __future__ import annotations

import csv
import os
import sqlite3
from pathlib import Path
from typing import Iterable


MAX_VISIBLE_ROWS = 20_000


class ScanStore:
    """Temporary disk-backed store so a large drive is not held in Python memory."""

    def __init__(self, database_path: str):
        self.database_path = database_path
        self.connection = sqlite3.connect(database_path, check_same_thread=False)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                parent_path TEXT NOT NULL,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                size INTEGER NOT NULL DEFAULT 0,
                file_count INTEGER NOT NULL DEFAULT 0,
                folder_count INTEGER NOT NULL DEFAULT 0,
                created TEXT NOT NULL DEFAULT '',
                modified TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL,
                purpose TEXT NOT NULL,
                windows_required TEXT NOT NULL,
                currently_used TEXT NOT NULL DEFAULT 'UNKNOWN',
                associated_application TEXT NOT NULL,
                publisher TEXT NOT NULL,
                digital_signature TEXT NOT NULL DEFAULT 'Unknown',
                deletion_risk TEXT NOT NULL,
                can_delete TEXT NOT NULL,
                confidence INTEGER NOT NULL,
                reason TEXT NOT NULL,
                is_protected INTEGER NOT NULL DEFAULT 0,
                scan_order INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_items_category ON items(category);
            CREATE INDEX IF NOT EXISTS idx_items_parent ON items(parent_path);
            CREATE INDEX IF NOT EXISTS idx_items_size ON items(size DESC);
            CREATE INDEX IF NOT EXISTS idx_items_name ON items(name);
            CREATE TABLE IF NOT EXISTS inaccessible (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL,
                error TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def clear(self) -> None:
        self.connection.execute("DELETE FROM items")
        self.connection.execute("DELETE FROM inaccessible")
        self.connection.commit()

    def insert_item(self, values: tuple) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO items
            (path, parent_path, name, kind, size, file_count, folder_count, created, modified, category, purpose,
             windows_required, currently_used, associated_application, publisher,
             digital_signature, deletion_risk, can_delete, confidence, reason,
             is_protected, scan_order)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )

    def update_folder_size(self, path: str, size: int) -> None:
        self.connection.execute("UPDATE items SET size = ? WHERE path = ?", (size, path))

    def add_inaccessible(self, path: str, error: str) -> None:
        self.connection.execute(
            "INSERT INTO inaccessible(path, error) VALUES (?, ?)",
            (path, error[:500]),
        )

    def commit(self) -> None:
        self.connection.commit()

    def count(self, where_sql: str = "", params: tuple = ()) -> int:
        query = "SELECT COUNT(*) FROM items" + where_sql
        return int(self.connection.execute(query, params).fetchone()[0])

    def summary(self) -> dict[str, int]:
        rows = self.connection.execute(
            "SELECT category, COUNT(*), COALESCE(SUM(size),0) FROM items GROUP BY category"
        ).fetchall()
        result: dict[str, int] = {"files": 0, "folders": 0, "total_size": 0}
        for category, count, size in rows:
            result[category] = count
            result[f"{category}:size"] = int(size)
        result["files"] = int(
            self.connection.execute("SELECT COUNT(*) FROM items WHERE kind = 'File'").fetchone()[0]
        )
        result["folders"] = int(
            self.connection.execute("SELECT COUNT(*) FROM items WHERE kind = 'Folder'").fetchone()[0]
        )
        result["total_size"] = int(
            self.connection.execute("SELECT COALESCE(SUM(size),0) FROM items WHERE kind = 'File'").fetchone()[0]
        )
        result["inaccessible"] = int(
            self.connection.execute("SELECT COUNT(*) FROM inaccessible").fetchone()[0]
        )
        return result

    def fetch_rows(
        self,
        where_sql: str = "",
        params: tuple = (),
        limit: int = MAX_VISIBLE_ROWS,
        order_by: str = "scan_order",
    ) -> list[tuple]:
        query = (
            "SELECT id, name, kind, path, size, category, deletion_risk, can_delete, "
            "confidence FROM items " + where_sql + f" ORDER BY {order_by} LIMIT ?"
        )
        return self.connection.execute(query, (*params, limit)).fetchall()

    def fetch_item(self, item_id: int) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM items WHERE id = ?", (item_id,)
        ).fetchone()
        if row is None:
            return None
        columns = [column[1] for column in self.connection.execute("PRAGMA table_info(items)")]
        return dict(zip(columns, row))

    def export_csv(self, output_path: str, scan_status: str) -> None:
        rows = self.connection.execute(
            "SELECT name, kind, path, size, created, modified, category, purpose, "
            "windows_required, currently_used, associated_application, publisher, "
            "digital_signature, deletion_risk, can_delete, confidence, reason "
            "FROM items ORDER BY scan_order"
        )
        with open(output_path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["DriveLens scan status", scan_status])
            writer.writerow(
                [
                    "Name", "Kind", "Path", "Size (bytes)", "Created", "Modified",
                    "Classification", "Purpose", "Windows Required", "Currently Used",
                    "Associated Application", "Publisher", "Digital Signature",
                    "Deletion Risk", "Can Delete", "Confidence (%)", "Reason",
                ]
            )
            writer.writerows(rows)
            inaccessible = self.connection.execute(
                "SELECT path, error FROM inaccessible ORDER BY id"
            )
            writer.writerow([])
            writer.writerow(["Inaccessible paths"])
            writer.writerow(["Path", "Error"])
            writer.writerows(inaccessible)

    def close(self) -> None:
        self.connection.commit()
        self.connection.close()