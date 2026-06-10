from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any

from nas_checker.scan.issues import (
    ISSUE_AUDIO_CODEC_NOT_ALLOWED,
    ISSUE_CONTAINER_NOT_ALLOWED,
    ISSUE_FILE_SMALL,
    ISSUE_HDR_DETECTED,
    ISSUE_MEDIA_INFO_ERROR,
    ISSUE_MULTIPLE_AUDIO,
    ISSUE_MULTIPLE_COMMENTARY,
    ISSUE_MULTIPLE_SUBTITLE,
    ISSUE_NO_AUDIO,
    ISSUE_NO_VIDEO,
    ISSUE_PGS_SUBTITLES,
    ISSUE_SUBTITLE_TRACK,
    ISSUE_TENBIT_H264,
    ISSUE_TEXT_SUBTITLES,
    ISSUE_VIDEO_CODEC_NOT_ALLOWED,
    ISSUE_WRONG_RESOLUTION,
    collect_issue_codes,
)

ACTION_FFMPEG = "ffmpeg"
ACTION_MANUAL = "manual"
ACTION_RADARR = "radarr"
ACTION_SONARR = "sonarr"

FFMPEG_FIX_CODES = {
    ISSUE_AUDIO_CODEC_NOT_ALLOWED,
    ISSUE_CONTAINER_NOT_ALLOWED,
    ISSUE_MULTIPLE_SUBTITLE,
    ISSUE_PGS_SUBTITLES,
    ISSUE_SUBTITLE_TRACK,
    ISSUE_TENBIT_H264,
    ISSUE_TEXT_SUBTITLES,
    ISSUE_VIDEO_CODEC_NOT_ALLOWED,
    ISSUE_WRONG_RESOLUTION,
}

MANUAL_REVIEW_CODES = {
    ISSUE_FILE_SMALL,
    ISSUE_HDR_DETECTED,
    ISSUE_MEDIA_INFO_ERROR,
    ISSUE_MULTIPLE_AUDIO,
    ISSUE_MULTIPLE_COMMENTARY,
}


@dataclass(frozen=True)
class FixAction:
    action_id: str
    label: str
    fixable: bool
    status: str


def is_tv_episode_path(file_path: str) -> bool:
    base = os.path.basename(file_path or "")
    return bool(re.search(r"\bS\d{1,2}E\d{1,2}\b", base, flags=re.IGNORECASE))


def classify_fix_action(file_path: str, issues: Any) -> FixAction:
    issue_codes = collect_issue_codes(issues)

    if ISSUE_NO_AUDIO in issue_codes or ISSUE_NO_VIDEO in issue_codes:
        if is_tv_episode_path(file_path):
            return FixAction(
                ACTION_SONARR,
                "Redownload via Sonarr",
                True,
                "Ready",
            )
        return FixAction(
            ACTION_RADARR,
            "Redownload via Radarr",
            True,
            "Ready",
        )

    if issue_codes.intersection(FFMPEG_FIX_CODES):
        return FixAction(
            ACTION_FFMPEG,
            "Auto-fix with ffmpeg",
            True,
            "Ready",
        )

    if issue_codes.intersection(MANUAL_REVIEW_CODES) or issue_codes:
        return FixAction(
            ACTION_MANUAL,
            "No automatic fix / manual review",
            False,
            "Manual review",
        )

    return FixAction(
        ACTION_MANUAL,
        "No automatic fix / manual review",
        False,
        "Manual review",
    )
