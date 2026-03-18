import subprocess
import json
import os

MIN_FILE_SIZE_BYTES = 1_000_000


def check_min_file_size(file):
    """Flag files that are unexpectedly small (often incomplete or corrupt)."""
    if os.path.getsize(file) < MIN_FILE_SIZE_BYTES:
        return ["File suspiciously small"]
    return []


def get_media_info(file):
    """Return ffprobe stream metadata for a media file as parsed JSON."""

    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", file]

    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore"
    )

    return json.loads(result.stdout)


def check_file(file):
    """Validate a media file against your rules and return a list of issues."""

    issues = []

    issues.extend(check_min_file_size(file))

    # check container
    if not file.lower().endswith(".mp4"):
        issues.append("Container is not MP4")

    try:
        info = get_media_info(file)
    except:
        issues.append("Could not read media info")
        return issues

    video_found = False
    audio_found = False

    for stream in info.get("streams", []):

        if stream["codec_type"] == "video":

            video_found = True
            codec = stream["codec_name"]

            if codec != "hevc":
                issues.append(f"Video codec is {codec}, not HEVC")

        elif stream["codec_type"] == "audio":

            audio_found = True
            codec = stream["codec_name"]

            if codec != "aac":
                issues.append(f"Audio codec is {codec}, not AAC")

        elif stream["codec_type"] == "subtitle":

            issues.append("Subtitle track detected")

    if not video_found:
        issues.append("No video stream found")

    if not audio_found:
        issues.append("No audio stream found")

    return issues
