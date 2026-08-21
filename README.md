# DriveLens

DriveLens is a small, local-only Windows desktop utility for understanding what is using space on the `C:\` drive. It scans files and folders in a background worker, applies explainable rules to classify each item, and lets you move explicitly selected non-critical items to the Windows Recycle Bin.

## What it does

- Scans `C:\` without freezing the window.
- Skips symbolic links and Windows reparse points so junctions cannot create scan loops.
- Continues through access-denied, locked, and disappearing items.
- Records inaccessible paths separately in the exported report.
- Classifies items using path, extension, timestamps, file metadata, and Windows directory conventions.
- Clearly uses `Unknown — insufficient evidence` when the available evidence is not enough.
- Shows size, purpose, risk, deletion recommendation, confidence, and reasoning for the selected item.
- Supports search by filename or full path and category filters.
- Supports a largest-files view and a largest-folders view.
- Cancels a scan safely.
- Moves selected items to the Windows Recycle Bin only after confirmation.
- Blocks deletion for Windows-protected and critical-looking items.
- Exports the current scan, including inaccessible paths, as a streaming CSV report.

DriveLens does **not** automatically delete anything. It does not require an account, server, database, API key, or internet connection.

## Requirements

- Windows 10 or Windows 11, 64-bit
- Python 3.11 or newer (3.11 or 3.12 recommended)
- PowerShell 5+ (included with supported Windows versions)

## Credentials and permissions

No credentials are required. There are no cloud services or API keys in this project.

The app normally runs with the permissions of the Windows user who launched it. Some protected folders will be inaccessible, and DriveLens will log them instead of crashing. Do not run as Administrator unless you understand why you need access to additional protected locations. Elevated access does not make deletion of critical system items available; those items remain blocked by the safety rules.

## Run locally

Open PowerShell in this folder:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\run_windows.ps1
```

The first run creates `.venv`, upgrades pip, and installs the dependencies from `requirements.txt`. Later runs reuse the same environment.

Manual equivalent:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

## Build a Windows `.exe`

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\build_windows.ps1
```

The finished executable is:

```text
dist\DriveLens\DriveLens.exe
```

This is a directory-based PyInstaller build. Zip the entire `dist\DriveLens` folder when distributing it; the `.exe` depends on the files beside it. The build script also creates `dist\DriveLens.zip`.

To build manually:

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --name DriveLens --collect-all PySide6 --hidden-import send2trash main.py
Compress-Archive -Path dist\DriveLens\* -DestinationPath dist\DriveLens.zip -Force
```

## Using the application

1. Start DriveLens.
2. Click **Scan C: Drive**.
3. Wait for the scan to finish, or click **Cancel Scan**.
4. Use the search box and category filter to narrow the results.
5. Select a row to inspect its evidence and deletion recommendation.
6. Only if the details panel enables it, click **Move to Recycle Bin**.
7. Confirm the exact path and consequence in the confirmation dialog.
8. Use **Export CSV Report** to save a report. The report includes inaccessible paths and the scan summary.

The initial scan can take a long time on a large or busy drive. It is safe to cancel. A cancelled scan remains available in the table and can still be exported; its report is marked as cancelled.

## Classification safety model

DriveLens does not claim certainty from a single filename. It combines several signals and displays the reason and confidence:

- Windows directories and known protected locations increase system-critical evidence.
- `Program Files`, `Program Files (x86)`, and application installation metadata increase installed-application evidence.
- `System32\drivers` and driver extensions increase driver evidence.
- Downloads and common archive/media/document extensions increase downloaded or user-file evidence.
- Temp and cache path markers increase temporary/cache evidence.
- Executable or script-like files in download locations may be flagged for review as potentially suspicious, but this is not malware detection.

Digital signatures and publisher metadata are checked when a selected executable or DLL is opened in the details panel. Signature information is never guessed.

## Development checks

From PowerShell:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m py_compile main.py drivelens\*.py
```

## Project layout

```text
drivelens/
├── main.py                 # Qt application and UI
├── drivelens/
│   ├── classifier.py       # Explainable classification rules
│   ├── models.py           # Item and scan counter models
│   ├── recycle_bin.py      # Windows Recycle Bin integration
│   ├── scanner.py          # C: traversal and background worker
│   ├── store.py            # Temporary disk-backed SQLite scan store
│   └── windows_info.py     # Windows usage, signature, and metadata checks
├── tests/
│   └── test_classifier.py  # Deterministic classifier checks
├── requirements.txt
├── run_windows.ps1
└── build_windows.ps1
```

## Limitations

- Classification is advisory, not antivirus or a guarantee that deletion is safe.
- "Currently used" is determined on demand for the selected item when Windows can answer; otherwise it is shown as unknown.
- A scan of millions of items is stored in a temporary SQLite file so the UI does not keep every row in Python memory. The visible table loads only the first 20,000 matching rows for responsiveness.
- Folder sizes are calculated from successfully scanned children. Inaccessible children are listed separately and may make a folder's size incomplete."# DriveLens" 
