import os
import re
import subprocess
from typing import Iterable

VIDEO_ENCODER_NVENC = "hevc_nvenc"


def _parse_expected_height_from_wrong_resolution(issue: str):
    """
    Parse `Wrong resolution: expected <Xp>, found <Yp>` and return X as int.
    """

    m = re.search(r"Wrong resolution:\s*expected\s*(\d{3,4})p", issue, flags=re.I)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _unique_output_path(output_path: str) -> str:
    if not os.path.exists(output_path):
        return output_path

    base, ext = os.path.splitext(output_path)
    for i in range(1, 1000):
        candidate = f"{base}_{i}{ext}"
        if not os.path.exists(candidate):
            return candidate
    return output_path


def build_ffmpeg_command(
    input_path: str, issues: Iterable[str] | str | None
) -> tuple[list[str], str] | tuple[None, None]:
    """
    Build an ffmpeg command to fix a file based on detected issues.

    Returns `(cmd, temp_output_path)` or `(None, None)` when the file already
    meets the supported fix criteria.
    """

    if isinstance(issues, str):
        issues_text = issues.lower()
    else:
        issues_text = ",".join([str(i).lower() for i in (issues or [])])

    input_path_norm = os.path.normpath(input_path)
    folder = os.path.dirname(input_path_norm)
    base = os.path.splitext(os.path.basename(input_path_norm))[0]
    input_ext = os.path.splitext(input_path_norm)[1].lower() or ".mp4"

    wants_mp4_container = "container is not mp4" in issues_text
    target_ext = ".mp4" if wants_mp4_container else input_ext

    temp_output_path = _unique_output_path(
        os.path.join(folder, f"{base}_auto_fix_tmp{target_ext}")
    )

    needs_hevc = "not hevc" in issues_text or "10bit h.264" in issues_text
    needs_aac = "not aac" in issues_text

    # Subtitles: if anything indicates subtitles are "bad", we remove them.
    remove_subtitles = any(
        s in issues_text
        for s in (
            "subtitle track detected",
            "pgs subtitles detected",
            "text subtitles detected",
            "pgs subtitles",
        )
    )

    expected_height = _parse_expected_height_from_wrong_resolution(issues_text)

    # Only fix when we can confidently improve based on supported issue types.
    should_fix = any(
        [
            needs_hevc,
            needs_aac,
            remove_subtitles,
            expected_height is not None,
            wants_mp4_container,
        ]
    )
    if not should_fix:
        return None, None

    # Video codec selection
    if needs_hevc:
        # NVIDIA hardware encoding
        video_codec_args = ["-c:v", VIDEO_ENCODER_NVENC]
        # A reasonable starting point; tweak later if you want.
        video_codec_args += ["-preset", "p5"]
    else:
        video_codec_args = ["-c:v", "copy"]

    # Audio selection
    if needs_aac:
        audio_codec_args = ["-c:a", "aac", "-b:a", "192k"]
    else:
        audio_codec_args = ["-c:a", "copy"]

    filter_args = []
    if expected_height is not None:
        # Scale keeping aspect ratio; -2 forces even width.
        filter_args = ["-vf", f"scale=-2:{expected_height}"]

    # If there are multiple tracks, keep Plex-friendlier "first stream only".
    multiple_audio_issue = "multiple audio tracks detected" in issues_text
    multiple_subtitle_issue = "multiple subtitle tracks detected" in issues_text

    # Map video+audio, optionally subtitles.
    # -map 0:a:0? makes audio optional.
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        input_path_norm,
        "-map",
        "0:v:0",
    ]

    # Audio mapping
    if multiple_audio_issue:
        cmd += ["-map", "0:a:0?"]
    else:
        cmd += ["-map", "0:a?"]

    # Subtitle mapping / removal
    if remove_subtitles:
        cmd.append("-sn")
    else:
        if multiple_subtitle_issue:
            cmd += ["-map", "0:s:0?"]
        else:
            cmd += ["-map", "0:s?"]
        # Copy subtitles verbatim when we are not removing them.
        cmd += ["-c:s", "copy"]

    if filter_args:
        cmd += filter_args

    cmd += video_codec_args
    cmd += audio_codec_args

    # Container/muxer selection.
    if wants_mp4_container:
        cmd += ["-f", "mp4", "-movflags", "+faststart"]

    cmd += [temp_output_path]

    return cmd, temp_output_path


def run_ffmpeg(cmd: list[str]):
    """
    Run ffmpeg command and return (exit_code, combined_output_text).

    Note: this is intended to be called from a background thread.
    """

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output_lines = []
    assert proc.stdout is not None
    for line in proc.stdout:
        output_lines.append(line)
        yield line.rstrip("\n")
    proc.wait()
    return proc.returncode, "\n".join(output_lines)
