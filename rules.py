import subprocess
import json
import os


def get_media_info(file):

    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        file
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")

    return json.loads(result.stdout)


def check_file(file):

    issues = []

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