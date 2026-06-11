# NAS Media Validator

Scans a NAS or local media library with **ffprobe**, flags Plex-oriented compatibility issues, and optionally auto-fixes files with **ffmpeg**. Includes a PySide6 GUI with live progress, filters, scan history, and NAS health scheduling.

## Prerequisites

- Python 3.11+ (see `environment.yml` for conda setup)
- **ffprobe** and **ffmpeg** on `PATH` (install [FFmpeg](https://ffmpeg.org/download.html))
- Optional: NVIDIA GPU + drivers for NVENC auto-fix (falls back to `libx265` on CPU)
- Windows-focused paths (`Z:/`) but CLI scanning works cross-platform

## Quick start

```bash
# Create environment
conda env create -f environment.yml
conda activate nas-media-validator

# GUI
python main.py --gui --path "Z:/"

# Headless CLI scan
python main.py --path "Z:/"

# Export JSON report, disable cache
python main.py --path "Z:/" --no-cache --export report.json
```

## CLI options

| Flag | Description |
|------|-------------|
| `--path`, `-p` | Media root (overrides settings / `NAS_SCAN_PATH`) |
| `--gui` | Launch GUI |
| `--workers`, `-w` | Parallel ffprobe workers |
| `--no-cache` | Skip incremental SQLite metadata cache |
| `--export FILE` | Write CSV or JSON report (extension selects format) |
| `--help` | Show usage |

Environment variable: `NAS_SCAN_PATH` sets the default scan path.

## Configuration

Copy example templates and edit:

| File | Purpose |
|------|---------|
| `scan_rules_settings.json.example` | Allowed codecs/containers and rule toggles |
| `scan_path_settings.json.example` | Default media library path |
| `arr_config.json.example` | Sonarr/Radarr API for redownload actions |

GUI **Scan Settings** writes rules to `nas_checker/gui/scan_rules_settings.json` and path/worker preferences to `nas_checker/gui/scan_path_settings.json`.
Use **Test Read Speed** there to run a read-only NAS throughput benchmark; Auto workers use the measured MB/s when available.

### Rule toggles (Scan Settings)

- Default allowed containers: `mp4`, `mkv`
- Default allowed video codecs: `hevc`, `h264`
- Default allowed audio codecs: `aac`, `ac3`, `eac3`
- Minimum file size threshold: 1,000,000 bytes
- Default-on checks: 10-bit H.264, multiple commentary tracks, wrong resolution vs filename (`1080p` in name)
- Default-off checks: subtitles, HDR, multiple audio tracks, multiple subtitle tracks

Changing rules invalidates the incremental cache via a rules hash.

## Issue types

| Code | Meaning | Auto-fix support |
|------|---------|------------------|
| `container_not_allowed` | Extension not in allowed list | Remux to MP4 |
| `video_codec_not_allowed` | Video codec not allowed | Re-encode (HEVC) |
| `audio_codec_not_allowed` | Audio codec not allowed | Transcode to AAC |
| `subtitle_track` / `pgs_subtitles` / `text_subtitles` | Subtitle tracks present | Remove subtitles (`-sn`) |
| `tenbit_h264` | 10-bit H.264 | Re-encode to HEVC |
| `wrong_resolution` | Height mismatch vs filename | Scale to expected height |
| `hdr_detected` | HDR metadata | Report only |
| `no_audio` / `no_video` | Missing streams | Sonarr/Radarr redownload |
| `file_small` | Below size threshold | Report only |
| `media_info_error` | ffprobe failure | Report only |

Issues are stored as structured `{code, message}` objects; legacy plain-text cache/history entries are normalized automatically.

## GUI features

- Live issue table with type filters and export (CSV/JSON)
- Auto-fix with progress, cancel, and `.bak` backup before replace
- Scan history and library-wide stats
- NAS Health tab: OK%, schedule, overdue reminders, Task Scheduler command helper
- Network Performance Monitor: latency plus read/throughput sampling
- Cache hit rate shown in scan progress stats
- Read-only media folder speed test for Auto worker tuning

## Scheduled scans

Configure schedule on the **NAS Health** tab. Options:

- In-app reminder when a scan is overdue (prompt or auto-start)
- **Copy Task Scheduler command** for unattended Windows runs:

```text
schtasks /Create /TN "NAS Media Validator Scan" /TR "python main.py --path Z:/" ...
```

## Development

```bash
pytest
```

Tests mock ffprobe JSON and do not require PySide6 or real media files.
