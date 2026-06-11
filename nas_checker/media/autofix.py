import os
import re
import subprocess
from typing import Iterable

from health.hardware import detect_nvidia_gpu
from nas_checker.scan.issues import (
    ISSUE_AUDIO_CODEC_NOT_ALLOWED,
    ISSUE_CONTAINER_NOT_ALLOWED,
    ISSUE_MULTIPLE_SUBTITLE,
    ISSUE_NO_AUDIO,
    ISSUE_PGS_SUBTITLES,
    ISSUE_SUBTITLE_TRACK,
    ISSUE_TENBIT_H264,
    ISSUE_TEXT_SUBTITLES,
    ISSUE_VIDEO_CODEC_NOT_ALLOWED,
    ISSUE_WRONG_RESOLUTION,
    collect_issue_codes,
    issues_text_blob,
    normalize_issues,
)

VIDEO_ENCODER_NVENC = "hevc_nvenc"


def _parse_expected_height_from_wrong_resolution(issues) -> int | None:
    """
    Parse `Wrong resolution: expected <Xp>, found <Yp>` and return X as int.
    """

    if isinstance(issues, str):
        text = issues
    else:
        text = issues_text_blob(issues)

    m = re.search(r"Wrong resolution:\s*expected\s*(\d{3,4})p", text, flags=re.I)
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
    input_path: str, issues: Iterable[str] | str | list | None
) -> tuple[list[str], str] | tuple[None, None]:
    """
    Build an ffmpeg command to fix a file based on detected issues.

    Returns `(cmd, temp_output_path)` or `(None, None)` when the file already
    meets the supported fix criteria.
    """

    if isinstance(issues, str):
        issue_list = normalize_issues([issues])
    else:
        issue_list = normalize_issues(list(issues or []))

    issue_codes = collect_issue_codes(issue_list)

    if ISSUE_NO_AUDIO in issue_codes:
        return None, None

    input_path_norm = os.path.normpath(input_path)
    folder = os.path.dirname(input_path_norm)
    base = os.path.splitext(os.path.basename(input_path_norm))[0]
    input_ext = os.path.splitext(input_path_norm)[1].lower() or ".mp4"

    wants_mp4_container = ISSUE_CONTAINER_NOT_ALLOWED in issue_codes
    target_ext = ".mp4" if wants_mp4_container else input_ext

    temp_output_path = _unique_output_path(
        os.path.join(folder, f"{base}_auto_fix_tmp{target_ext}")
    )

    needs_hevc = (
        ISSUE_VIDEO_CODEC_NOT_ALLOWED in issue_codes or ISSUE_TENBIT_H264 in issue_codes
    )
    needs_aac = ISSUE_AUDIO_CODEC_NOT_ALLOWED in issue_codes

    remove_subtitles = issue_codes.intersection(
        {
            ISSUE_SUBTITLE_TRACK,
            ISSUE_PGS_SUBTITLES,
            ISSUE_TEXT_SUBTITLES,
        }
    )

    expected_height = _parse_expected_height_from_wrong_resolution(issue_list)

    should_fix = any(
        [
            needs_hevc,
            needs_aac,
            bool(remove_subtitles),
            expected_height is not None,
            wants_mp4_container,
        ]
    )
    if not should_fix:
        return None, None

    if needs_hevc:
        if detect_nvidia_gpu():
            video_codec_args = ["-c:v", VIDEO_ENCODER_NVENC, "-preset", "p5"]
        else:
            video_codec_args = ["-c:v", "libx265", "-preset", "medium", "-crf", "23"]
    else:
        video_codec_args = ["-c:v", "copy"]

    if needs_aac:
        audio_codec_args = ["-c:a", "aac", "-b:a", "192k"]
    else:
        audio_codec_args = ["-c:a", "copy"]

    filter_args = []
    if expected_height is not None:
        filter_args = ["-vf", f"scale=-2:{expected_height}"]

    multiple_subtitle_issue = ISSUE_MULTIPLE_SUBTITLE in issue_codes

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        input_path_norm,
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
    ]

    if remove_subtitles:
        cmd.append("-sn")
    else:
        if multiple_subtitle_issue:
            cmd += ["-map", "0:s:0?"]
        else:
            cmd += ["-map", "0:s?"]
        cmd += ["-c:s", "copy"]

    if filter_args:
        cmd += filter_args

    cmd += video_codec_args
    cmd += audio_codec_args

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


def backup_original_file(input_path: str) -> str | None:
    """Create a `.bak` backup of the original file before replacement."""

    backup_path = input_path + ".bak"
    if os.path.exists(backup_path):
        base, ext = os.path.splitext(input_path)
        for i in range(1, 1000):
            candidate = f"{base}.bak{i}{ext}"
            if not os.path.exists(candidate):
                backup_path = candidate
                break

    try:
        import shutil

        shutil.copy2(input_path, backup_path)
        return backup_path
    except Exception:
        return None
