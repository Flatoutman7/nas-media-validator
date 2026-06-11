from __future__ import annotations

from typing import Any

# Stable issue codes used across rules, GUI filters, auto-fix, and reports.
ISSUE_FILE_SMALL = "file_small"
ISSUE_CONTAINER_NOT_ALLOWED = "container_not_allowed"
ISSUE_MEDIA_INFO_ERROR = "media_info_error"
ISSUE_VIDEO_CODEC_NOT_ALLOWED = "video_codec_not_allowed"
ISSUE_AUDIO_CODEC_NOT_ALLOWED = "audio_codec_not_allowed"
ISSUE_SUBTITLE_TRACK = "subtitle_track"
ISSUE_NO_VIDEO = "no_video"
ISSUE_NO_AUDIO = "no_audio"
ISSUE_TENBIT_H264 = "tenbit_h264"
ISSUE_PGS_SUBTITLES = "pgs_subtitles"
ISSUE_HDR_DETECTED = "hdr_detected"
ISSUE_MULTIPLE_COMMENTARY = "multiple_commentary"
ISSUE_MULTIPLE_AUDIO = "multiple_audio"
ISSUE_MULTIPLE_SUBTITLE = "multiple_subtitle"
ISSUE_TEXT_SUBTITLES = "text_subtitles"
ISSUE_WRONG_RESOLUTION = "wrong_resolution"

# Legacy plain-text messages mapped to codes for cache/history compatibility.
_LEGACY_MESSAGE_TO_CODE: dict[str, str] = {
    "file suspiciously small": ISSUE_FILE_SMALL,
    "could not read media info": ISSUE_MEDIA_INFO_ERROR,
    "no video stream found": ISSUE_NO_VIDEO,
    "no audio stream found": ISSUE_NO_AUDIO,
    "subtitle track detected": ISSUE_SUBTITLE_TRACK,
    "hdr detected": ISSUE_HDR_DETECTED,
    "10bit h.264 (bad for plex)": ISSUE_TENBIT_H264,
    "pgs subtitles detected": ISSUE_PGS_SUBTITLES,
    "multiple audio tracks detected": ISSUE_MULTIPLE_AUDIO,
    "multiple subtitle tracks detected": ISSUE_MULTIPLE_SUBTITLE,
    "text subtitles detected": ISSUE_TEXT_SUBTITLES,
    "multiple commentary tracks detected": ISSUE_MULTIPLE_COMMENTARY,
}


def make_issue(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def issue_message(issue: Any) -> str:
    if isinstance(issue, dict):
        return str(issue.get("message") or issue.get("code") or "")
    return str(issue or "")


def issue_code(issue: Any) -> str | None:
    if isinstance(issue, dict):
        code = issue.get("code")
        return str(code) if code else None
    text = str(issue or "").strip()
    if not text:
        return None
    lower = text.lower()
    if lower in _LEGACY_MESSAGE_TO_CODE:
        return _LEGACY_MESSAGE_TO_CODE[lower]
    if lower.startswith("container is not allowed"):
        return ISSUE_CONTAINER_NOT_ALLOWED
    if lower.startswith("video codec is") and "not allowed" in lower:
        return ISSUE_VIDEO_CODEC_NOT_ALLOWED
    if lower.startswith("audio codec is") and "not allowed" in lower:
        return ISSUE_AUDIO_CODEC_NOT_ALLOWED
    if lower.startswith("wrong resolution:"):
        return ISSUE_WRONG_RESOLUTION
    if lower.startswith("ffprobe failed"):
        return ISSUE_MEDIA_INFO_ERROR
    return None


def normalize_issue(issue: Any) -> dict[str, str]:
    if isinstance(issue, dict) and issue.get("code") and issue.get("message"):
        return {"code": str(issue["code"]), "message": str(issue["message"])}
    message = issue_message(issue)
    code = issue_code(issue) or "unknown"
    return make_issue(code, message)


def normalize_issues(issues: list[Any] | None) -> list[dict[str, str]]:
    if not issues:
        return []
    return [normalize_issue(i) for i in issues]


def issues_contain_code(issues: Any, code: str) -> bool:
    if isinstance(issues, str):
        return issue_code(issues) == code
    for issue in issues or []:
        if issue_code(issue) == code:
            return True
    return False


def issues_to_display_text(issues: Any) -> str:
    if isinstance(issues, str):
        return issues
    return ", ".join(issue_message(i) for i in (issues or []))


def collect_issue_codes(issues: Any) -> set[str]:
    codes: set[str] = set()
    if isinstance(issues, str):
        for part in issues.split(","):
            code = issue_code(part.strip())
            if code:
                codes.add(code)
        return codes
    for issue in issues or []:
        code = issue_code(issue)
        if code:
            codes.add(code)
    return codes


def issues_text_blob(issues: Any) -> str:
    if isinstance(issues, str):
        return issues.lower()
    return ",".join(issue_message(i).lower() for i in (issues or []))
