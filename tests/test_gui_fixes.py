from nas_checker.gui.fixes import (
    ACTION_FFMPEG,
    ACTION_MANUAL,
    ACTION_RADARR,
    ACTION_SONARR,
    classify_fix_action,
)
from nas_checker.scan.issues import (
    ISSUE_CONTAINER_NOT_ALLOWED,
    ISSUE_HDR_DETECTED,
    ISSUE_NO_AUDIO,
    ISSUE_TENBIT_H264,
    make_issue,
)


def test_ffmpeg_fixable_issue_maps_to_ffmpeg_action():
    action = classify_fix_action(
        r"Z:\Movies\Example.mkv",
        [
            make_issue(ISSUE_CONTAINER_NOT_ALLOWED, "Container is not allowed: mkv"),
            make_issue(ISSUE_TENBIT_H264, "10bit H.264 (bad for Plex)"),
        ],
    )

    assert action.action_id == ACTION_FFMPEG
    assert action.fixable is True
    assert action.label == "Auto-fix with ffmpeg"


def test_missing_audio_tv_episode_maps_to_sonarr_redownload():
    action = classify_fix_action(
        r"Z:\Shows\Example - S01E02.mkv",
        [make_issue(ISSUE_NO_AUDIO, "No audio stream found")],
    )

    assert action.action_id == ACTION_SONARR
    assert action.fixable is True
    assert action.label == "Redownload via Sonarr"


def test_missing_audio_movie_maps_to_radarr_redownload():
    action = classify_fix_action(
        r"Z:\Movies\Example Movie (2024).mkv",
        [make_issue(ISSUE_NO_AUDIO, "No audio stream found")],
    )

    assert action.action_id == ACTION_RADARR
    assert action.fixable is True
    assert action.label == "Redownload via Radarr"


def test_manual_review_issue_is_not_fixable():
    action = classify_fix_action(
        r"Z:\Movies\Example.mkv",
        [make_issue(ISSUE_HDR_DETECTED, "HDR detected")],
    )

    assert action.action_id == ACTION_MANUAL
    assert action.fixable is False
    assert action.label == "No automatic fix / manual review"
