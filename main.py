from __future__ import annotations

import csv
import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QTableView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QListWidgetItem,
    QProgressDialog,
    QTableView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from drivelens.models import Category
from drivelens.recycle_bin import move_to_recycle_bin
from drivelens.scanner import ScanWorker
from drivelens.store import MAX_VISIBLE_ROWS, ScanStore
from drivelens.windows_info import inspect_file


# ============================================================
# HELPERS
# ============================================================

def format_size(value: int) -> str:
    value = max(0, int(value or 0))

    for suffix in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or suffix == "TB":
            if suffix == "B":
                return f"{value} B"
            return f"{value:.1f} {suffix}"
        value /= 1024

    return f"{value:.1f} TB"


# ============================================================
# TABLE MODEL
# ============================================================

class ScanTableModel(QAbstractTableModel):
    headers = (
        "Name",
        "Kind",
        "Location",
        "Size",
        "Classification",
        "Risk",
        "Can Delete",
        "Confidence",
    )

    def __init__(self, store: ScanStore, parent: QObject | None = None):
        super().__init__(parent)

        self.store = store
        self.rows: list[tuple] = []

        self.where_sql = ""
        self.params: tuple = ()
        self.order_by = "scan_order"
        self.parent_path = ""

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.headers)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if (
            role == Qt.ItemDataRole.DisplayRole
            and orientation == Qt.Orientation.Horizontal
        ):
            return self.headers[section]

        return None

    def data(
        self,
        index: QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if not index.isValid() or index.row() >= len(self.rows):
            return None

        row = self.rows[index.row()]

        if role == Qt.ItemDataRole.DisplayRole:
            values = (
                row[1],
                row[2],
                row[3],
                format_size(row[4]),
                row[5],
                row[6],
                row[7],
                f"{row[8]}%",
            )

            return values[index.column()]

        if role == Qt.ItemDataRole.ToolTipRole:
            return row[3]

        if role == Qt.ItemDataRole.ForegroundRole:

            if index.column() == 5:
                color = {
                    "LOW": "#72d6a2",
                    "MEDIUM": "#f6ca77",
                    "HIGH": "#f3a15d",
                    "CRITICAL": "#f27c86",
                }.get(row[6], "#b8c1d1")

                return QColor(color)

            if index.column() == 6 and row[7] == "YES":
                return QColor("#72d6a2")

        if role == Qt.ItemDataRole.UserRole:
            return row[0]

        return None

    def refresh(self):
        self.beginResetModel()

        where = self.where_sql
        params = list(self.params)

        if self.parent_path:
            extra = "parent_path = ?"

            where = (
                f"{where} AND {extra}"
                if where
                else f" WHERE {extra}"
            )

            params.append(self.parent_path)

        self.rows = self.store.fetch_rows(
            where,
            tuple(params),
            order_by=self.order_by,
        )

        self.endResetModel()

    def set_filter(
        self,
        search: str,
        category: str,
        large_only: bool,
        largest_folders: bool,
    ):

        clauses = []
        params = []

        if search.strip():
            clauses.append(
                "(name LIKE ? COLLATE NOCASE OR path LIKE ? COLLATE NOCASE)"
            )

            needle = f"%{search.strip()}%"
            params.extend((needle, needle))

        if category and category != "All":
            clauses.append("category = ?")
            params.append(category)

        if large_only:
            clauses.append("kind = 'File' AND size >= ?")
            params.append(100 * 1024 * 1024)

        if largest_folders:
            clauses.append("kind = 'Folder'")

        self.where_sql = (
            " WHERE " + " AND ".join(clauses)
            if clauses
            else ""
        )

        self.params = tuple(params)

        self.order_by = (
            "size DESC, scan_order"
            if (large_only or largest_folders)
            else "scan_order"
        )

        self.refresh()


# ============================================================
# SUMMARY CARD
# ============================================================

class SummaryCard(QFrame):

    clicked = Signal(str)

    def __init__(
        self,
        key: str,
        title: str,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self.key = key

        self.setObjectName("summaryCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)

        self.value = QLabel("—")
        self.value.setObjectName("summaryValue")

        self.title = QLabel(title)
        self.title.setObjectName("summaryTitle")

        layout.addWidget(self.value)
        layout.addWidget(self.title)

    def mousePressEvent(self, event):
        self.clicked.emit(self.key)
        super().mousePressEvent(event)

    def set_value(self, value: str):
        self.value.setText(value)


# ============================================================
# DETAIL PANEL
# ============================================================

class DetailPanel(QFrame):

    delete_requested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("detailPanel")

        self.item = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)

        title = QLabel("Item details")
        title.setObjectName("panelTitle")

        layout.addWidget(title)

        self.name = QLabel("Select an item")
        self.name.setObjectName("detailName")
        self.name.setWordWrap(True)

        layout.addWidget(self.name)

        self.details = QLabel(
            "Choose a file or folder to inspect its evidence."
        )

        self.details.setObjectName("detailText")
        self.details.setWordWrap(True)

        self.details.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        layout.addWidget(self.details)

        self.delete_button = QPushButton(
            "Move to Recycle Bin"
        )

        self.delete_button.setObjectName("dangerButton")
        self.delete_button.setEnabled(False)

        self.delete_button.clicked.connect(
            self._request_delete
        )

        layout.addWidget(self.delete_button)

        layout.addStretch()

    def show_item(self, item):
        self.item = item

        if item is None:
            self.name.setText("Select an item")

            self.details.setText(
                "Choose a file or folder to inspect its evidence."
            )

            self.delete_button.setEnabled(False)

            return

        self.name.setText(item["name"])

        self.details.setText(
            self._detail_text(item)
        )

        can_delete = (
            item["can_delete"] == "YES"
            and not item["is_protected"]
        )

        self.delete_button.setEnabled(can_delete)

        if not can_delete:

            if item["is_protected"]:
                self.delete_button.setToolTip(
                    "Deletion blocked because this item may be required by Windows."
                )
            else:
                self.delete_button.setToolTip(
                    "This item requires review and cannot be moved automatically."
                )

    def _detail_text(self, item):

        parts = (
            f"<b>Location</b><br>{item['path']}<br><br>"
            f"<b>Type</b><br>{item['kind']}<br><br>"
            f"<b>Size</b><br>{format_size(item['size'])}<br><br>"
        )

        if item["kind"] == "Folder":

            parts += (
                f"<b>Files</b><br>{item.get('file_count', 0):,}<br><br>"
                f"<b>Subfolders</b><br>{item.get('folder_count', 0):,}<br><br>"
            )

        parts += (
            f"<b>Created</b><br>{item['created'] or 'Unknown'}<br><br>"
            f"<b>Modified</b><br>{item['modified'] or 'Unknown'}<br><br>"
            f"<b>Classification</b><br>{item['category']}<br><br>"
            f"<b>Purpose</b><br>{item['purpose']}<br><br>"
            f"<b>Windows required</b><br>{item['windows_required']}<br><br>"
            f"<b>Currently used</b><br>{item['currently_used']}<br><br>"
            f"<b>Associated application</b><br>{item['associated_application']}<br><br>"
            f"<b>Publisher</b><br>{item['publisher']}<br><br>"
            f"<b>Digital signature</b><br>{item['digital_signature']}<br><br>"
            f"<b>Deletion risk</b><br>{item['deletion_risk']}<br><br>"
            f"<b>Can delete</b><br>{item['can_delete']}<br><br>"
            f"<b>Confidence</b><br>{item['confidence']}%<br><br>"
            f"<b>Reason</b><br>{item['reason']}"
        )

        return parts

    def _request_delete(self):

        if self.item:
            self.delete_requested.emit(self.item)


# ============================================================
# SMART CLEANUP DIALOG
# ============================================================
class SmartCleanupDialog(QDialog):
    """
    Fast Smart Cleanup dialog.

    Important:
    - Nothing is deleted automatically.
    - Only items already identified by DriveLens are shown.
    - Windows-protected items are never selectable.
    - Selection uses QListWidget instead of thousands of QWidget checkboxes.
    """

    def __init__(self, store: ScanStore, parent=None):
        super().__init__(parent)

        self.store = store
        self.selected_for_cleanup = []

        self.setWindowTitle("DriveLens — Smart Cleanup")
        self.resize(1000, 700)

        self._build_ui()
        self._load_categories()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel("Smart Cleanup")
        title.setObjectName("cleanupTitle")
        layout.addWidget(title)

        description = QLabel(
            "Select the type of files you want to clean. "
            "DriveLens will show only reviewable user/temporary files. "
            "Windows-protected and critical files are excluded."
        )
        description.setWordWrap(True)
        description.setObjectName("cleanupDescription")
        layout.addWidget(description)

        # --------------------------------------------------
        # CATEGORY SELECTION
        # --------------------------------------------------

        category_frame = QFrame()
        category_layout = QGridLayout(category_frame)

        self.category_checks = {}

        categories = [
            (
                "temporary",
                "Temporary / Cache",
                "Temporary files, cache and crash data",
            ),
            (
                "downloaded",
                "Downloaded Files",
                "Files from Downloads and Desktop",
            ),
            (
                "user",
                "User Files",
                "Documents, pictures, videos, music and archives",
            ),
            (
                "development",
                "Development",
                "Development/project/package-cache files",
            ),
            (
                "large",
                "Large Files",
                "User files larger than 100 MB",
            ),
            (
                "archives",
                "Archives",
                "ZIP, RAR, 7Z, ISO and similar files",
            ),
            (
                "media",
                "Large Media",
                "Large videos, audio and image files",
            ),
            (
                "unknown",
                "Reviewable Unknown",
                "Files DriveLens could not confidently classify",
            ),
        ]

        for index, (key, title_text, description_text) in enumerate(categories):

            checkbox = QCheckBox(title_text)
            checkbox.setProperty("cleanup_key", key)

            label = QLabel(description_text)
            label.setWordWrap(True)
            label.setStyleSheet("color: #8e9aae;")

            box = QVBoxLayout()
            box.addWidget(checkbox)
            box.addWidget(label)

            wrapper = QFrame()
            wrapper.setLayout(box)
            wrapper.setStyleSheet(
                """
                QFrame {
                    background: #1a202b;
                    border: 1px solid #2b3444;
                    border-radius: 8px;
                    padding: 8px;
                }
                """
            )

            category_layout.addWidget(
                wrapper,
                index // 2,
                index % 2,
            )

            self.category_checks[key] = checkbox

        layout.addWidget(category_frame)

        # --------------------------------------------------
        # BUTTONS
        # --------------------------------------------------

        controls = QHBoxLayout()

        self.select_all_button = QPushButton("Select All Categories")
        self.select_all_button.clicked.connect(self._select_all_categories)
        controls.addWidget(self.select_all_button)

        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self._clear_categories)
        controls.addWidget(self.clear_button)

        controls.addStretch()

        self.find_button = QPushButton("Find Cleanup Candidates")
        self.find_button.setObjectName("primaryButton")
        self.find_button.clicked.connect(self._find_candidates)
        controls.addWidget(self.find_button)

        layout.addLayout(controls)

        # --------------------------------------------------
        # CANDIDATE LIST
        # --------------------------------------------------

        self.result_label = QLabel(
            "Select categories and click Find Cleanup Candidates."
        )
        self.result_label.setStyleSheet(
            "color: #72d6a2; font-weight: 600;"
        )
        layout.addWidget(self.result_label)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection
        )

        self.list_widget.itemSelectionChanged.connect(
    self._update_total
)
        layout.addWidget(self.list_widget, 1)

        # --------------------------------------------------
        # FILE SELECTION CONTROLS
        # --------------------------------------------------

        file_controls = QHBoxLayout()

        self.select_files_button = QPushButton("Select All Files")
        self.select_files_button.clicked.connect(
            self._select_all_files
        )
        file_controls.addWidget(self.select_files_button)

        self.clear_files_button = QPushButton("Clear File Selection")
        self.clear_files_button.clicked.connect(
            self._clear_file_selection
        )
        file_controls.addWidget(self.clear_files_button)

        file_controls.addStretch()

        self.total_label = QLabel(
            "Selected: 0 files • 0 B"
        )
        self.total_label.setStyleSheet(
            "color: #72d6a2; font-weight: 600;"
        )
        file_controls.addWidget(self.total_label)

        layout.addLayout(file_controls)

        # --------------------------------------------------
        # FINAL BUTTONS
        # --------------------------------------------------

        buttons = QHBoxLayout()

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(cancel_button)

        buttons.addStretch()

        self.cleanup_button = QPushButton(
            "Move Selected to Recycle Bin"
        )
        self.cleanup_button.setObjectName("dangerButton")
        self.cleanup_button.setEnabled(False)
        self.cleanup_button.clicked.connect(
            self._confirm_cleanup
        )
        buttons.addWidget(self.cleanup_button)

        layout.addLayout(buttons)

    # ======================================================
    # CATEGORY HELPERS
    # ======================================================

    def _select_all_categories(self):
        for checkbox in self.category_checks.values():
            checkbox.setChecked(True)

    def _clear_categories(self):
        for checkbox in self.category_checks.values():
            checkbox.setChecked(False)

        self.list_widget.clear()
        self.result_label.setText(
            "Select categories and click Find Cleanup Candidates."
        )
        self._update_total()

    # ======================================================
    # LOAD CATEGORY INFORMATION
    # ======================================================

    def _load_categories(self):
        summary = self.store.summary()

        # Keep the dialog lightweight.
        # We do not load thousands of rows here.

        if summary.get(Category.TEMPORARY.value, 0):
            self.category_checks["temporary"].setText(
                f"Temporary / Cache "
                f"({summary.get(Category.TEMPORARY.value, 0):,})"
            )

        if summary.get(Category.DOWNLOADED.value, 0):
            self.category_checks["downloaded"].setText(
                f"Downloaded Files "
                f"({summary.get(Category.DOWNLOADED.value, 0):,})"
            )

        if summary.get(Category.USER_FILE.value, 0):
            self.category_checks["user"].setText(
                f"User Files "
                f"({summary.get(Category.USER_FILE.value, 0):,})"
            )

        if summary.get(Category.DEVELOPMENT.value, 0):
            self.category_checks["development"].setText(
                f"Development "
                f"({summary.get(Category.DEVELOPMENT.value, 0):,})"
            )

        if summary.get(Category.UNKNOWN.value, 0):
            self.category_checks["unknown"].setText(
                f"Reviewable Unknown "
                f"({summary.get(Category.UNKNOWN.value, 0):,})"
            )

    # ======================================================
    # FIND CANDIDATES
    # ======================================================

    def _find_candidates(self):

        selected_categories = [
            key
            for key, checkbox in self.category_checks.items()
            if checkbox.isChecked()
        ]

        if not selected_categories:
            QMessageBox.information(
                self,
                "No category selected",
                "Select at least one cleanup category.",
            )
            return

        self.list_widget.clear()

        # Build SQL conditions.
        conditions = []
        params = []

        category_map = {
            "temporary": Category.TEMPORARY.value,
            "downloaded": Category.DOWNLOADED.value,
            "user": Category.USER_FILE.value,
            "development": Category.DEVELOPMENT.value,
            "unknown": Category.UNKNOWN.value,
        }

        normal_categories = [
            category_map[key]
            for key in selected_categories
            if key in category_map
        ]

        if normal_categories:
            placeholders = ",".join(
                "?" for _ in normal_categories
            )
            conditions.append(
                f"category IN ({placeholders})"
            )
            params.extend(normal_categories)

        if "large" in selected_categories:
            conditions.append(
                "(kind = 'File' AND size >= ?)"
            )
            params.append(
                100 * 1024 * 1024
            )

        if "archives" in selected_categories:
            conditions.append(
                """
                (
                    LOWER(name) LIKE '%.zip'
                    OR LOWER(name) LIKE '%.rar'
                    OR LOWER(name) LIKE '%.7z'
                    OR LOWER(name) LIKE '%.iso'
                    OR LOWER(name) LIKE '%.tar'
                    OR LOWER(name) LIKE '%.gz'
                )
                """
            )

        if "media" in selected_categories:
            conditions.append(
                """
                (
                    LOWER(name) LIKE '%.mp4'
                    OR LOWER(name) LIKE '%.mkv'
                    OR LOWER(name) LIKE '%.avi'
                    OR LOWER(name) LIKE '%.mov'
                    OR LOWER(name) LIKE '%.mp3'
                    OR LOWER(name) LIKE '%.wav'
                    OR LOWER(name) LIKE '%.jpg'
                    OR LOWER(name) LIKE '%.jpeg'
                    OR LOWER(name) LIKE '%.png'
                )
                """
            )

        if not conditions:
            return

        where = " WHERE (" + " OR ".join(
            conditions
        ) + ")"

        # IMPORTANT:
        # Never include protected Windows files.
        where += """
            AND is_protected = 0
            AND kind = 'File'
        """

        query = f"""
            SELECT *
            FROM items
            {where}
            ORDER BY size DESC
            LIMIT 10000
        """

        rows = self.store.connection.execute(
            query,
            tuple(params),
        ).fetchall()

        columns = [
            column[1]
            for column in self.store.connection.execute(
                "PRAGMA table_info(items)"
            )
        ]

        items = [
            dict(zip(columns, row))
            for row in rows
        ]

        # Do not show items that DriveLens explicitly says
        # are not approved for deletion.
        items = [
            item
            for item in items
            if item["can_delete"] == "YES"
        ]

        self.current_items = items

        for item in items:

            text = (
                f"{format_size(item['size']):>10}   "
                f"{item['name']}   "
                f"— {item['path']}"
            )

            list_item = QListWidgetItem(text)

            list_item.setData(
                Qt.ItemDataRole.UserRole,
                item,
            )

            self.list_widget.addItem(list_item)

        self.result_label.setText(
            f"Found {len(items):,} reviewable cleanup files "
            f"(largest first)."
        )

        if not items:
            QMessageBox.information(
                self,
                "No cleanup candidates",
                "No files matching the selected categories "
                "were approved by DriveLens for cleanup.",
            )

        self._update_total()

    # ======================================================
    # FAST FILE SELECTION
    # ======================================================

    def _select_all_files(self):

        self.list_widget.blockSignals(True)

        self.list_widget.selectAll()

        self.list_widget.blockSignals(False)

        self._update_total()

    def _clear_file_selection(self):

        self.list_widget.blockSignals(True)

        self.list_widget.clearSelection()

        self.list_widget.blockSignals(False)

        self._update_total()

    def _get_selected_items(self):

        selected = []

        for list_item in self.list_widget.selectedItems():

            item = list_item.data(
                Qt.ItemDataRole.UserRole
            )

            if item:
                selected.append(item)

        return selected

    def _update_total(self):

        selected = self._get_selected_items()

        total = sum(
            int(item.get("size", 0) or 0)
            for item in selected
        )

        self.total_label.setText(
            f"Selected: {len(selected):,} files "
            f"• {format_size(total)}"
        )

        self.cleanup_button.setEnabled(
            bool(selected)
        )

    # ======================================================
    # CLEANUP CONFIRMATION
    # ======================================================

    def _confirm_cleanup(self):

        selected = self._get_selected_items()

        if not selected:
            QMessageBox.information(
                self,
                "Nothing selected",
                "Select the files you want to clean first.",
            )
            return

        # Final safety filtering.
        safe_items = []

        for item in selected:

            if item["is_protected"]:
                continue

            if item["can_delete"] != "YES":
                continue

            if item["kind"] != "File":
                continue

            safe_items.append(item)

        if not safe_items:
            QMessageBox.warning(
                self,
                "Nothing safe to clean",
                "None of the selected files are currently approved "
                "for cleanup.",
            )
            return

        total = sum(
            int(item["size"])
            for item in safe_items
        )

        answer = QMessageBox.question(
            self,
            "Confirm Smart Cleanup",
            (
                f"You selected {len(safe_items):,} files.\n\n"
                f"Space selected: {format_size(total)}\n\n"
                "These files will be moved to the Windows "
                "Recycle Bin.\n\n"
                "They will NOT be permanently deleted.\n\n"
                "Continue?"
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        self.selected_for_cleanup = safe_items

        self.accept()

    def selected_items(self):
        return self.selected_for_cleanup


# ============================================================
# MAIN WINDOW
# ============================================================

class MainWindow(QMainWindow):

    def __init__(self):

        super().__init__()

        self.setWindowTitle(
            "DriveLens"
        )

        self.resize(
            1500,
            920,
        )

        self.database_path = str(
            Path(tempfile.gettempdir())
            / "drivelens-current.sqlite3"
        )

        try:
            Path(
                self.database_path
            ).unlink(
                missing_ok=True
            )

            Path(
                self.database_path + "-wal"
            ).unlink(
                missing_ok=True
            )

            Path(
                self.database_path + "-shm"
            ).unlink(
                missing_ok=True
            )

        except OSError:
            pass

        self.store = ScanStore(
            self.database_path
        )

        self.model = ScanTableModel(
            self.store,
            self,
        )

        self.thread = None
        self.worker = None

        self.scan_status = "not started"

        self.selected_item = None

        self._build_ui()

        self._refresh_timer = QTimer(
            self
        )

        self._refresh_timer.setInterval(
            450
        )

        self._refresh_timer.timeout.connect(
            self._refresh_results
        )

        self._refresh_timer.start()

    # ========================================================
    # UI
    # ========================================================

    def _build_ui(self):

        root = QWidget()
        root.setObjectName("root")

        self.setCentralWidget(root)

        outer = QVBoxLayout(root)

        outer.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        outer.setSpacing(0)

        # HEADER
        header = QFrame()
        header.setObjectName("header")

        header_layout = QHBoxLayout(
            header
        )

        header_layout.setContentsMargins(
            24,
            18,
            24,
            18,
        )

        title_box = QVBoxLayout()

        title = QLabel(
            "DriveLens"
        )

        title.setObjectName(
            "appTitle"
        )

        try:
            import shutil

            total, used, free = shutil.disk_usage(
                "C:\\"
            )

            stats = (
                f"C: Drive — "
                f"{format_size(used)} used / "
                f"{format_size(free)} free "
                f"of {format_size(total)}"
            )

        except Exception:

            stats = (
                "Understand your C: drive "
                "before you change it"
            )

        subtitle = QLabel(
            stats
        )

        subtitle.setObjectName(
            "appSubtitle"
        )

        title_box.addWidget(
            title
        )

        title_box.addWidget(
            subtitle
        )

        header_layout.addLayout(
            title_box
        )

        header_layout.addStretch()

        self.status_label = QLabel(
            "Ready to scan"
        )

        self.status_label.setObjectName(
            "statusLabel"
        )

        header_layout.addWidget(
            self.status_label
        )

        self.scan_button = QPushButton(
            "Scan C: Drive"
        )

        self.scan_button.setObjectName(
            "primaryButton"
        )

        self.scan_button.clicked.connect(
            self.start_scan
        )

        header_layout.addWidget(
            self.scan_button
        )

        self.cancel_button = QPushButton(
            "Cancel Scan"
        )

        self.cancel_button.setObjectName(
            "secondaryButton"
        )

        self.cancel_button.setEnabled(
            False
        )

        self.cancel_button.clicked.connect(
            self.cancel_scan
        )

        header_layout.addWidget(
            self.cancel_button
        )

        outer.addWidget(
            header
        )

        # CONTENT
        content = QSplitter(
            Qt.Orientation.Horizontal
        )

        content.setObjectName(
            "contentSplitter"
        )

        outer.addWidget(
            content,
            1,
        )

        # SIDEBAR
        sidebar = QFrame()
        sidebar.setObjectName(
            "sidebar"
        )

        sidebar.setMinimumWidth(
            250
        )

        sidebar.setMaximumWidth(
            300
        )

        side_layout = QVBoxLayout(
            sidebar
        )

        side_layout.setContentsMargins(
            20,
            24,
            20,
            20,
        )

        side_layout.setSpacing(
            12
        )

        guide = QLabel(
            "DriveLens uses local evidence to explain "
            "files. Windows-protected items are blocked "
            "from Smart Cleanup."
        )

        guide.setObjectName(
            "guideText"
        )

        guide.setWordWrap(
            True
        )

        side_layout.addWidget(
            guide
        )

        self.current_path_label = QLabel(
            "Current path: —"
        )

        self.current_path_label.setObjectName(
            "sideNote"
        )

        self.current_path_label.setWordWrap(
            True
        )

        side_layout.addWidget(
            self.current_path_label
        )

        side_layout.addSpacing(
            10
        )

        # SMART CLEANUP BUTTON
        self.smart_cleanup_button = QPushButton(
            "🧹 Smart Cleanup"
        )

        self.smart_cleanup_button.setObjectName(
            "cleanupSidebarButton"
        )

        self.smart_cleanup_button.clicked.connect(
            self.open_smart_cleanup
        )

        side_layout.addWidget(
            self.smart_cleanup_button
        )

        self.export_button = QPushButton(
            "Export CSV Report"
        )

        self.export_button.setObjectName(
            "secondaryButton"
        )

        self.export_button.clicked.connect(
            self.export_report
        )

        side_layout.addWidget(
            self.export_button
        )

        self.large_button = QPushButton(
            "Show Large Files"
        )

        self.large_button.setObjectName(
            "secondaryButton"
        )

        self.large_button.setCheckable(
            True
        )

        self.large_button.toggled.connect(
            self._apply_filters
        )

        side_layout.addWidget(
            self.large_button
        )

        self.largest_folders_button = QPushButton(
            "Show Largest Folders"
        )

        self.largest_folders_button.setObjectName(
            "secondaryButton"
        )

        self.largest_folders_button.setCheckable(
            True
        )

        self.largest_folders_button.toggled.connect(
            self._largest_folders_toggled
        )

        side_layout.addWidget(
            self.largest_folders_button
        )

        side_layout.addStretch()

        side_note = QLabel(
            "All analysis stays on this computer.\n\n"
            "Smart Cleanup moves selected files "
            "to the Windows Recycle Bin."
        )

        side_note.setObjectName(
            "sideNote"
        )

        side_note.setWordWrap(
            True
        )

        side_layout.addWidget(
            side_note
        )

        content.addWidget(
            sidebar
        )

        # MIDDLE
        middle = QWidget()

        middle_layout = QVBoxLayout(
            middle
        )

        middle_layout.setContentsMargins(
            18,
            18,
            18,
            18,
        )

        middle_layout.setSpacing(
            14
        )

        self.summary_grid = QGridLayout()

        self.summary_grid.setSpacing(
            10
        )

        self.cards = {}

        card_data = (
            ("files", "Files"),
            ("folders", "Folders"),
            ("total_size", "Total size"),
            (
                Category.WINDOWS_SYSTEM,
                "Windows/System",
            ),
            (
                Category.INSTALLED_APPLICATION,
                "Installed apps",
            ),
            (
                Category.DOWNLOADED,
                "Downloaded",
            ),
            (
                Category.USER_FILE,
                "User files",
            ),
            (
                Category.TEMPORARY,
                "Temporary/cache",
            ),
            (
                Category.UNKNOWN,
                "Unknown",
            ),
            (
                Category.SUSPICIOUS,
                "Suspicious review",
            ),
        )

        for position, (
            key,
            label,
        ) in enumerate(card_data):

            card = SummaryCard(
                str(key),
                label,
            )

            card.clicked.connect(
                self._category_card_clicked
            )

            self.cards[
                str(key)
            ] = card

            self.summary_grid.addWidget(
                card,
                position // 5,
                position % 5,
            )

        middle_layout.addLayout(
            self.summary_grid
        )

        # CONTROLS
        controls = QHBoxLayout()

        self.up_button = QPushButton(
            "↑ Up"
        )

        self.up_button.clicked.connect(
            self._navigate_up
        )

        self.up_button.setEnabled(
            False
        )

        controls.addWidget(
            self.up_button
        )

        self.breadcrumb = QLabel(
            "Root: C:\\"
        )

        controls.addWidget(
            self.breadcrumb
        )

        self.search_input = QLineEdit()

        self.search_input.setPlaceholderText(
            "Search filename or folder name..."
        )

        self.search_input.textChanged.connect(
            self._apply_filters
        )

        controls.addWidget(
            self.search_input,
            1,
        )

        self.category_combo = QComboBox()

        self.category_combo.addItem(
            "All"
        )

        self.category_combo.addItems(
            [
                category.value
                for category in Category
            ]
        )

        self.category_combo.currentTextChanged.connect(
            self._apply_filters
        )

        controls.addWidget(
            self.category_combo
        )

        middle_layout.addLayout(
            controls
        )

        # TABLE
        self.table = QTableView()

        self.table.setModel(
            self.model
        )

        self.table.setSelectionBehavior(
            QTableView.SelectionBehavior.SelectRows
        )

        self.table.setSelectionMode(
            QTableView.SelectionMode.SingleSelection
        )

        self.table.setAlternatingRowColors(
            True
        )

        self.table.setSortingEnabled(
            False
        )

        self.table.verticalHeader().setVisible(
            False
        )

        self.table.horizontalHeader().setStretchLastSection(
            True
        )

        self.table.horizontalHeader().setMinimumSectionSize(
            90
        )

        self.table.selectionModel().currentChanged.connect(
            self._selection_changed
        )

        self.table.doubleClicked.connect(
            self._table_double_clicked
        )

        middle_layout.addWidget(
            self.table,
            1,
        )

        self.result_note = QLabel(
            "No scan results yet."
        )

        self.result_note.setObjectName(
            "resultNote"
        )

        middle_layout.addWidget(
            self.result_note
        )

        content.addWidget(
            middle
        )

        # DETAILS
        self.details = DetailPanel()

        self.details.setMinimumWidth(
            320
        )

        self.details.setMaximumWidth(
            430
        )

        self.details.delete_requested.connect(
            self.delete_item
        )

        content.addWidget(
            self.details
        )

        content.setSizes(
            [
                250,
                850,
                370,
            ]
        )

        # PROGRESS
        self.progress = QProgressBar()

        self.progress.setRange(
            0,
            0,
        )

        self.progress.setVisible(
            False
        )

        self.progress.setTextVisible(
            False
        )

        self.statusBar().addWidget(
            self.progress,
            1,
        )

        self.statusBar().showMessage(
            "Ready"
        )

    # ========================================================
    # SCANNING
    # ========================================================

    def start_scan(self):

        if self.thread is not None:
            return

        if os.name != "nt":

            QMessageBox.warning(
                self,
                "Windows required",
                "DriveLens scans C:\\ and must be run on Windows.",
            )

            return

        self.model.beginResetModel()

        self.model.rows = []

        self.model.endResetModel()

        self.details.show_item(
            None
        )

        self.scan_status = "scanning"

        self.status_label.setText(
            "Scanning C: drive..."
        )

        self.statusBar().showMessage(
            "Starting scan..."
        )

        self.scan_button.setEnabled(
            False
        )

        self.cancel_button.setEnabled(
            True
        )

        self.progress.setVisible(
            True
        )

        self.worker = ScanWorker(
            self.database_path
        )

        self.thread = QThread(
            self
        )

        self.worker.moveToThread(
            self.thread
        )

        self.thread.started.connect(
            self.worker.run
        )

        self.worker.progress.connect(
            self._scan_progress
        )

        self.worker.finished.connect(
            self._scan_finished
        )

        self.worker.failed.connect(
            self._scan_failed
        )

        self.worker.finished.connect(
            self.thread.quit
        )

        self.worker.failed.connect(
            self.thread.quit
        )

        self.thread.finished.connect(
            self._thread_finished
        )

        self.thread.start()

    def cancel_scan(self):

        if self.worker:

            self.worker.cancel()

            self.cancel_button.setEnabled(
                False
            )

            self.status_label.setText(
                "Stopping after current item..."
            )

            self.statusBar().showMessage(
                "Cancellation requested"
            )

    def _scan_progress(self, data):

        self.statusBar().showMessage(
            f"Scanning {data['current_path']} | "
            f"{data['files']:,} files and "
            f"{data['folders']:,} folders"
            f" — {format_size(data['total_size'])} analyzed"
        )

        self.current_path_label.setText(
            f"Current path: {data['current_path']}"
        )

        self.status_label.setText(
            f"{data['files']:,} files | "
            f"{data['folders']:,} folders"
        )

    def _scan_finished(self, status):

        self.scan_status = status

        self._refresh_results()

        self.progress.setVisible(
            False
        )

        self.scan_button.setEnabled(
            True
        )

        self.cancel_button.setEnabled(
            False
        )

        if status == "cancelled":

            self.status_label.setText(
                "Scan cancelled"
            )

            self.statusBar().showMessage(
                "Scan cancelled"
            )

        else:

            self.status_label.setText(
                "Scan complete"
            )

            self.statusBar().showMessage(
                "Scan complete"
            )

    def _scan_failed(self, message):

        self.scan_status = "failed"

        self.progress.setVisible(
            False
        )

        self.scan_button.setEnabled(
            True
        )

        self.cancel_button.setEnabled(
            False
        )

        self.status_label.setText(
            "Scan failed"
        )

        QMessageBox.critical(
            self,
            "Scan failed",
            message,
        )

    def _thread_finished(self):

        if self.thread:

            self.thread.deleteLater()

        self.thread = None
        self.worker = None

    # ========================================================
    # RESULTS
    # ========================================================

    def _refresh_results(self):

        if self.scan_status in {
            "not started",
            "failed",
        }:
            return

        self.model.refresh()

        summary = self.store.summary()

        for key, card in self.cards.items():

            value = summary.get(
                key,
                0,
            )

            if key in {
                "files",
                "folders",
                "total_size",
            }:

                if key == "total_size":

                    card.set_value(
                        format_size(value)
                    )

                else:

                    card.set_value(
                        f"{value:,}"
                    )

            else:

                size = summary.get(
                    f"{key}:size",
                    0,
                )

                card.set_value(
                    f"{value:,} items • "
                    f"{format_size(size)}"
                )

        count = self.store.count(
            self.model.where_sql,
            self.model.params,
        )

        self.result_note.setText(
            f"{count:,} matching items"
            + (
                f" (showing the first "
                f"{MAX_VISIBLE_ROWS:,})"
                if count > MAX_VISIBLE_ROWS
                else ""
            )
        )

    # ========================================================
    # FILTERS
    # ========================================================

    def _category_card_clicked(
        self,
        category_key,
    ):

        if category_key in [
            category.value
            for category in Category
        ]:

            self.category_combo.setCurrentText(
                category_key
            )

        else:

            self.category_combo.setCurrentText(
                "All"
            )

    def _navigate_up(self):

        path = getattr(
            self.model,
            "parent_path",
            "",
        )

        if not path:
            return

        parent = os.path.dirname(
            path
        )

        if parent == path or not parent:

            self.model.parent_path = ""

        else:

            self.model.parent_path = parent

        self._apply_filters()

        self._update_breadcrumbs()

    def _update_breadcrumbs(self):

        path = getattr(
            self.model,
            "parent_path",
            "",
        )

        if not path:

            self.breadcrumb.setText(
                "Root: C:\\"
            )

            self.up_button.setEnabled(
                False
            )

        else:

            self.breadcrumb.setText(
                path
            )

            self.up_button.setEnabled(
                True
            )

    def _table_double_clicked(
        self,
        index,
    ):

        item_id = index.data(
            Qt.ItemDataRole.UserRole
        )

        item = self.store.fetch_item(
            int(item_id)
        )

        if item and item["kind"] == "Folder":

            self.model.parent_path = item[
                "path"
            ]

            self._apply_filters()

            self._update_breadcrumbs()

    def _apply_filters(self):

        if self.scan_status == "not started":
            return

        self.model.set_filter(
            self.search_input.text(),
            self.category_combo.currentText(),
            self.large_button.isChecked(),
            self.largest_folders_button.isChecked(),
        )

        self._refresh_results()

    def _largest_folders_toggled(
        self,
        checked,
    ):

        if (
            checked
            and self.large_button.isChecked()
        ):

            self.large_button.setChecked(
                False
            )

        self._apply_filters()

    # ========================================================
    # SELECTION
    # ========================================================

    def _selection_changed(
        self,
        current,
        _previous,
    ):

        if not current.isValid():

            self.selected_item = None

            self.details.show_item(
                None
            )

            return

        item_id = current.data(
            Qt.ItemDataRole.UserRole
        )

        item = self.store.fetch_item(
            int(item_id)
        )

        if item and item["kind"] == "File":

            inspection = inspect_file(
                item["path"]
            )

            item.update(
                currently_used=inspection.currently_used,
                publisher=inspection.publisher,
                digital_signature=inspection.digital_signature,
                associated_application=(
                    item["associated_application"]
                    if inspection.associated_application
                    == "Unknown"
                    else inspection.associated_application
                ),
            )

        self.selected_item = item

        self.details.show_item(
            item
        )

    # ========================================================
    # INDIVIDUAL DELETE
    # ========================================================

    def delete_item(
        self,
        item,
    ):

        if item["is_protected"]:

            QMessageBox.warning(
                self,
                "Deletion blocked",
                "Deletion blocked because this item "
                "may be required by Windows.",
            )

            return

        if item["can_delete"] != "YES":

            QMessageBox.information(
                self,
                "Review required",
                "DriveLens cannot approve this item "
                "for deletion. Review it manually instead.",
            )

            return

        if item["currently_used"] == "YES":

            QMessageBox.warning(
                self,
                "Item is in use",
                "This item appears to be in use "
                "and will not be moved.",
            )

            return

        answer = QMessageBox.question(
            self,
            "Confirm Recycle Bin move",
            (
                "Move this item to the Recycle Bin?\n\n"
                f"{item['path']}\n\n"
                "The item can usually be restored "
                "from the Recycle Bin."
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        try:

            move_to_recycle_bin(
                item["path"]
            )

        except Exception as error:

            QMessageBox.critical(
                self,
                "Could not move item",
                str(error),
            )

            return

        try:

            self.store.connection.execute(
                "DELETE FROM items WHERE id = ?",
                (item["id"],),
            )

            self.store.connection.commit()

        except Exception:
            pass

        QMessageBox.information(
            self,
            "Moved to Recycle Bin",
            "The selected item was moved to the Recycle Bin.",
        )

        self.details.show_item(
            None
        )

        self._refresh_results()

    # ========================================================
    # SMART CLEANUP
     # ========================================================
    # SMART CLEANUP
    # ========================================================

    def open_smart_cleanup(self):

        if self.scan_status not in {"complete", "cancelled"}:
            QMessageBox.information(
                self,
                "Scan required",
                (
                    "Run a DriveLens scan first.\n\n"
                    "Smart Cleanup uses the scan results to "
                    "find cleanup candidates."
                ),
            )
            return

        dialog = SmartCleanupDialog(
            self.store,
            self,
        )

        result = dialog.exec()

        if result != QDialog.DialogCode.Accepted:
            return

        selected_items = dialog.selected_items()

        if not selected_items:
            return

        self._perform_smart_cleanup(selected_items)

    def _perform_smart_cleanup(self, items):

        moved = 0
        failed = 0
        skipped = 0
        freed = 0

        # Progress dialog
        progress_dialog = QDialog(self)
        progress_dialog.setWindowTitle(
            "DriveLens Smart Cleanup"
        )
        progress_dialog.setModal(True)
        progress_dialog.resize(600, 150)

        dialog_layout = QVBoxLayout(
            progress_dialog
        )

        progress_label = QLabel(
            "Starting cleanup..."
        )

        progress_label.setWordWrap(True)

        progress = QProgressBar()

        progress.setRange(
            0,
            len(items),
        )

        progress.setValue(0)

        dialog_layout.addWidget(
            progress_label
        )

        dialog_layout.addWidget(
            progress
        )

        progress_dialog.show()

        QApplication.processEvents()

        for index, item in enumerate(
            items,
            start=1,
        ):

            path = item["path"]

            progress_label.setText(
                f"Moving {index:,} of {len(items):,}\n"
                f"{path}"
            )

            progress.setValue(index - 1)

            QApplication.processEvents()

            # ---------------------------------------------
            # FINAL SAFETY CHECK
            # ---------------------------------------------

            if item.get("is_protected", 0):
                skipped += 1
                continue

            if item.get("can_delete") != "YES":
                skipped += 1
                continue

            if item.get("kind") != "File":
                skipped += 1
                continue

            if not os.path.exists(path):
                skipped += 1
                continue

            try:

                move_to_recycle_bin(path)

                moved += 1

                freed += int(
                    item.get("size", 0) or 0
                )

                # Remove successfully moved item
                # from the current scan database.
                try:

                    self.store.connection.execute(
                        "DELETE FROM items WHERE id = ?",
                        (item["id"],),
                    )

                except Exception:
                    pass

            except Exception:

                failed += 1

        # Commit database changes
        try:

            self.store.connection.commit()

        except Exception:
            pass

        progress.setValue(
            len(items)
        )

        progress_label.setText(
            "Cleanup complete."
        )

        QApplication.processEvents()

        progress_dialog.close()

        self.details.show_item(
            None
        )

        self.selected_item = None

        self._refresh_results()

        QMessageBox.information(
            self,
            "Smart Cleanup Complete",
            (
                f"Moved to Recycle Bin: {moved:,}\n"
                f"Skipped: {skipped:,}\n"
                f"Failed: {failed:,}\n\n"
                f"Space selected: {format_size(freed)}\n\n"
                "The files were moved to the Windows "
                "Recycle Bin rather than permanently deleted."
            ),
        )

    def _perform_smart_cleanup_duplicate(
        self,
        items,
    ):

        moved = 0
        failed = 0
        skipped = 0
        freed = 0

        progress = QProgressBar(
            self
        )

        progress.setWindowTitle(
            "DriveLens Smart Cleanup"
        )

        progress.setRange(
            0,
            len(items),
        )

        progress.setValue(
            0
        )

        # Use a small modal dialog to show progress
        progress_dialog = QDialog(
            self
        )

        progress_dialog.setWindowTitle(
            "Cleaning selected files..."
        )

        progress_dialog.setModal(
            True
        )

        dialog_layout = QVBoxLayout(
            progress_dialog
        )

        progress_label = QLabel(
            "Starting cleanup..."
        )

        dialog_layout.addWidget(
            progress_label
        )

        dialog_layout.addWidget(
            progress
        )

        progress_dialog.resize(
            500,
            130,
        )

        progress_dialog.show()

        QApplication.processEvents()

        for index, item in enumerate(
            items,
            start=1,
        ):

            path = item["path"]

            progress_label.setText(
                f"Moving {index:,} of "
                f"{len(items):,}\n{path}"
            )

            progress.setValue(
                index - 1
            )

            QApplication.processEvents()

            # Safety check again immediately before deletion
            if item.get(
                "is_protected",
                0,
            ):

                skipped += 1
                continue

            try:

                if not os.path.exists(
                    path
                ):

                    skipped += 1
                    continue

                move_to_recycle_bin(
                    path
                )

                moved += 1

                freed += int(
                    item.get(
                        "size",
                        0,
                    )
                    or 0
                )

                try:

                    self.store.connection.execute(
                        "DELETE FROM items WHERE id = ?",
                        (item["id"],),
                    )

                except Exception:
                    pass

            except Exception:

                failed += 1

        try:

            self.store.connection.commit()

        except Exception:
            pass

        progress.setValue(
            len(items)
        )

        progress_label.setText(
            "Cleanup complete."
        )

        QApplication.processEvents()

        progress_dialog.close()

        self.details.show_item(
            None
        )

        self._refresh_results()

        QMessageBox.information(
            self,
            "Smart Cleanup Complete",
            (
                f"Moved to Recycle Bin: {moved:,}\n"
                f"Skipped: {skipped:,}\n"
                f"Failed: {failed:,}\n\n"
                f"Space selected: {format_size(freed)}\n\n"
                "The files were moved to the Windows "
                "Recycle Bin rather than permanently deleted."
            ),
        )

    # ========================================================
    # EXPORT
    # ========================================================

    def export_report(self):

        if self.scan_status == "not started":

            QMessageBox.information(
                self,
                "No scan yet",
                "Run a scan before exporting a report.",
            )

            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export DriveLens report",
            "drivelens-report.csv",
            "CSV files (*.csv)",
        )

        if not path:
            return

        try:

            self.store.export_csv(
                path,
                self.scan_status,
            )

        except OSError as error:

            QMessageBox.critical(
                self,
                "Export failed",
                str(error),
            )

            return

        QMessageBox.information(
            self,
            "Report exported",
            f"Saved report to:\n{path}",
        )

    # ========================================================
    # CLOSE
    # ========================================================

    def closeEvent(
        self,
        event,
    ):

        if self.worker:

            self.worker.cancel()

            self.thread.quit()

            self.thread.wait(
                3000
            )

        self.store.close()

        try:

            Path(
                self.database_path
            ).unlink(
                missing_ok=True
            )

            Path(
                self.database_path + "-wal"
            ).unlink(
                missing_ok=True
            )

            Path(
                self.database_path + "-shm"
            ).unlink(
                missing_ok=True
            )

        except OSError:
            pass

        event.accept()


# ============================================================
# THEME
# ============================================================

def apply_theme(
    app: QApplication,
):

    app.setStyle(
        "Fusion"
    )

    app.setStyleSheet(
        """
        QWidget {
            color: #e8edf5;
            font-family: "Segoe UI";
            font-size: 10pt;
        }

        #root {
            background: #11151d;
        }

        #header {
            background: #1a202b;
            border-bottom: 1px solid #2b3444;
        }

        #sidebar,
        #detailPanel {
            background: #171c25;
        }

        #sidebar {
            border-right: 1px solid #2b3444;
        }

        #detailPanel {
            border-left: 1px solid #2b3444;
        }

        #appTitle {
            font-size: 22pt;
            font-weight: 700;
            color: #f2f5fa;
        }

        #appSubtitle,
        #guideText,
        #sideNote,
        #resultNote {
            color: #8e9aae;
        }

        #statusLabel {
            color: #72d6a2;
            padding-right: 14px;
        }

        #summaryCard {
            background: #1a202b;
            border: 1px solid #2b3444;
            border-radius: 8px;
        }

        #summaryValue {
            font-size: 15pt;
            font-weight: 700;
            color: #f2f5fa;
        }

        #summaryTitle {
            color: #91a0b5;
            font-size: 8.5pt;
        }

        #panelTitle {
            color: #91a0b5;
            font-size: 9pt;
        }

        #detailName {
            font-size: 13pt;
            font-weight: 700;
            color: #f2f5fa;
        }

        #detailText {
            color: #c2cad8;
        }

        QLineEdit,
        QComboBox {
            background: #1a202b;
            border: 1px solid #344052;
            border-radius: 6px;
            padding: 9px;
            color: #eef2f8;
        }

        QLineEdit:focus,
        QComboBox:focus {
            border: 1px solid #6d9ef8;
        }

        QPushButton {
            border-radius: 6px;
            padding: 9px 14px;
            font-weight: 600;
        }

        #primaryButton {
            background: #5d8ff0;
            color: white;
            border: 1px solid #6d9ef8;
        }

        #primaryButton:hover {
            background: #6d9ef8;
        }

        #primaryButton:disabled {
            background: #39475f;
            color: #8c98aa;
        }

        #secondaryButton {
            background: #242c3a;
            color: #d8e0ec;
            border: 1px solid #39475a;
        }

        #secondaryButton:hover {
            background: #2c3748;
        }

        #secondaryButton:checked {
            background: #344b73;
            border-color: #6d9ef8;
        }

        #dangerButton {
            background: #612f3a;
            color: #ffd9de;
            border: 1px solid #8c4554;
        }

        #dangerButton:disabled {
            background: #282d35;
            color: #6f7a8b;
            border-color: #343b47;
        }

        #cleanupSidebarButton {
            background: #27634c;
            color: #d9fff0;
            border: 1px solid #3d9875;
            font-size: 10.5pt;
        }

        #cleanupSidebarButton:hover {
            background: #327d60;
        }

        #cleanupButton {
            background: #5d8ff0;
            color: white;
            border: 1px solid #6d9ef8;
        }

        #cleanupButton:hover {
            background: #6d9ef8;
        }

        #cleanupButton:disabled {
            background: #39475f;
            color: #8c98aa;
        }

        QTableView {
            background: #151a22;
            alternate-background-color: #1a202b;
            border: 1px solid #2b3444;
            border-radius: 7px;
            gridline-color: #252d3a;
            selection-background-color: #2e4b78;
            selection-color: #ffffff;
        }

        QHeaderView::section {
            background: #202735;
            color: #aab6c8;
            padding: 9px;
            border: none;
            border-bottom: 1px solid #344052;
            font-weight: 600;
        }

        QProgressBar {
            border: none;
            background: #202735;
            height: 5px;
        }

        QProgressBar::chunk {
            background: #5d8ff0;
        }

        QStatusBar {
            background: #151a22;
            color: #8e9aae;
        }

        /* SMART CLEANUP */

        #cleanupTitle {
            font-size: 22pt;
            font-weight: 700;
            color: #f2f5fa;
        }

        #cleanupDescription {
            color: #9ca9bc;
            padding-bottom: 8px;
        }

        #cleanupCategory {
            background: #1a202b;
            border: 1px solid #2b3444;
            border-radius: 8px;
            padding: 6px;
        }

        #cleanupCategory:hover {
            border: 1px solid #48658e;
        }

        #cleanupCategoryDescription {
            color: #7f8ca1;
            font-size: 8.5pt;
            padding-left: 4px;
        }

        #cleanupTotal {
            background: #202735;
            border: 1px solid #344052;
            border-radius: 6px;
            padding: 10px;
            color: #72d6a2;
            font-weight: 700;
        }

        QDialog {
            background: #11151d;
        }

        QTableWidget {
            background: #151a22;
            alternate-background-color: #1a202b;
            border: 1px solid #2b3444;
            gridline-color: #252d3a;
            selection-background-color: #2e4b78;
        }

        QCheckBox {
            spacing: 7px;
            color: #dce3ef;
        }

        QCheckBox::indicator {
            width: 17px;
            height: 17px;
        }
        """
    )


# ============================================================
# MAIN
# ============================================================

def main():

    app = QApplication(
        sys.argv
    )

    app.setApplicationName(
        "DriveLens"
    )

    apply_theme(
        app
    )

    window = MainWindow()

    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(
        main()
    )