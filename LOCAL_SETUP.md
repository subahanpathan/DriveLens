# DriveLens local setup and credentials guide

This guide is for running DriveLens on a Windows laptop and building the `.exe`.

## 1. What you need

- Windows 10 or Windows 11, 64-bit
- Python 3.11+ from https://www.python.org/downloads/windows/
- PowerShell
- About 2 GB of free disk space for Python, Qt, and the build output

During Python installation, enable **Add Python to PATH** and install the **Python launcher**. A normal per-user Python installation is sufficient.

## 2. Credentials

DriveLens requires **no credentials**:

- No email or account
- No API key
- No cloud service
- No database password
- No internet connection after dependencies are installed

The project does not read or store credentials. The only permission involved is the normal Windows file permission of the user who launches it.

Some folders such as `C:\System Volume Information` may be inaccessible. That is expected: DriveLens records the path and continues instead of asking for or storing an administrator password.

## 3. Open the project

Extract the ZIP to a normal folder, for example:

```text
C:\Tools\DriveLens
```

Do not run the application directly from inside the ZIP archive.

Open PowerShell in the extracted `DriveLens` folder:

```powershell
cd C:\Tools\DriveLens
```

If PowerShell blocks local scripts, allow scripts only for the current PowerShell window:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

## 4. Run from source

The provided script creates a private virtual environment and installs everything:

```powershell
.\run_windows.ps1
```

The first run may take several minutes because PySide6 is a large desktop UI dependency. The app window opens after installation completes.

Manual commands, if preferred:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

## 5. Scan safely

1. Click **Scan C: Drive**.
2. Let it run, or click **Cancel Scan** to stop after the current item.
3. Search by name or path.
4. Use **Show Large Files** or **Show Largest Folders** for space investigation.
5. Select a row to see the evidence and confidence.
6. DriveLens disables deletion for Windows-critical items.
7. For an enabled item, click **Move to Recycle Bin** and confirm the exact path.

DriveLens never permanently deletes an item and never deletes automatically.

## 6. Export a report

After starting or completing a scan, click **Export CSV Report** and choose a location such as:

```text
C:\Users\<your-windows-user>\Desktop\drivelens-report.csv
```

The CSV includes item metadata, classification reasoning, confidence, and inaccessible paths. A cancelled scan is clearly marked as cancelled.

## 7. Build the Windows executable

From the project folder:

```powershell
.\build_windows.ps1
```

The output is:

```text
dist\DriveLens\DriveLens.exe
dist\DriveLens.zip
```

Run `DriveLens.exe` from inside the `dist\DriveLens` folder. Keep the other files in that folder beside the executable; they are required by the PyInstaller build.

The build script is equivalent to:

```powershell
.\.venv\Scripts\python.exe -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --name DriveLens `
  --collect-all PySide6 `
  --hidden-import send2trash `
  main.py
```

## 8. If the scan reports inaccessible paths

This is normal on Windows. Do not enter a password into DriveLens. If you intentionally need to inspect more protected locations, close the app and start PowerShell with **Run as administrator**, then run it again. Review every deletion manually even when elevated.

## 9. Troubleshooting

### `py` is not recognized

Reinstall Python from python.org and enable the launcher and PATH options. Then open a new PowerShell window.

### `python -m pip install` fails

Confirm that the laptop has internet access during the first setup. The app itself is local-only, but PySide6 and send2trash must be downloaded once.

### The scan is slow

An entire C: drive may contain hundreds of thousands or millions of entries. The scan is incremental and cancellable. Close other disk-heavy applications and allow the scan to finish if you need a complete report.

### Windows Defender warns about the new executable

The build is an unsigned local PyInstaller executable. Review the source and build it locally; do not bypass a warning for an executable received from an unknown source.