NAS Media Validator

Scans a NAS media library and reports issues such as:
- wrong container
- wrong codecs
- missing audio/video
- subtitles

Includes a PySide6 GUI with live progress and issue table.

## How to run

CLI scan (default scan root is `Z:/`):

```bash
python main.py
```

GUI:

```bash
python main.py --gui
```

## Features

- Scan History tab (persistent past scan results).
- NAS Health dashboard tab:
  - OK% progress
  - Corrupted / Unreadable / Unrepairable counts
  - Last Scan + Next Scan scheduling (Daily / Weekly / Custom date)
- Incremental scanning cache (faster repeat scans by reusing per-file results when unchanged).
- Network Performance Monitor (best-effort):
  - Latency (ICMP when possible, SMB TCP connect fallback)
  - Read speed + throughput measured by sampling a file under the scan root

## Configuration

- Default scan root is `Z:/` (see `nas_checker/scan/main.py` -> `MEDIA_FOLDER`).

## Where data is stored

- `scan_history.json` (repo root)
  - scan history used by the “Scan History” and “NAS Health” tabs
- `nas_checker/scan/scan_metadata.db`
  - SQLite incremental scan cache (keyed by file path + `size` + `mtime_ns`)
- `nas_checker/gui/health_settings.json`
  - persisted “NAS Health” scheduling settings

Currently set to my preferences, feel free to ask how to edit it for your own needs.
