from nas_checker.media.autofix import build_ffmpeg_command
from nas_checker.scan.issues import make_issue
from nas_checker.scan.issues import (
    ISSUE_AUDIO_CODEC_NOT_ALLOWED,
    ISSUE_CONTAINER_NOT_ALLOWED,
    ISSUE_NO_AUDIO,
    ISSUE_SUBTITLE_TRACK,
    ISSUE_TENBIT_H264,
    ISSUE_VIDEO_CODEC_NOT_ALLOWED,
    ISSUE_WRONG_RESOLUTION,
)


def test_build_ffmpeg_command_container_to_mp4():
    issues = [make_issue(ISSUE_CONTAINER_NOT_ALLOWED, "Container is not allowed: mkv")]
    cmd, out = build_ffmpeg_command(r"Z:\Movies\file.mkv", issues)
    assert cmd is not None
    assert out.endswith(".mp4")
    assert "-f" in cmd and "mp4" in cmd


def test_build_ffmpeg_command_hevc_and_aac():
    issues = [
        make_issue(ISSUE_VIDEO_CODEC_NOT_ALLOWED, "Video codec is h264, not allowed"),
        make_issue(ISSUE_AUDIO_CODEC_NOT_ALLOWED, "Audio codec is ac3, not allowed"),
    ]
    cmd, _out = build_ffmpeg_command(r"Z:\Movies\file.mp4", issues)
    assert cmd is not None
    joined = " ".join(cmd)
    assert "-c:a" in joined and "aac" in joined


def test_build_ffmpeg_command_removes_subtitles():
    issues = [make_issue(ISSUE_SUBTITLE_TRACK, "Subtitle track detected")]
    cmd, _out = build_ffmpeg_command(r"Z:\Movies\file.mp4", issues)
    assert cmd is not None
    assert "-sn" in cmd


def test_build_ffmpeg_command_wrong_resolution_scale():
    issues = [
        make_issue(
            ISSUE_WRONG_RESOLUTION,
            "Wrong resolution: expected 1080p, found 720p",
        )
    ]
    cmd, _out = build_ffmpeg_command(r"Z:\Movies\file.mp4", issues)
    assert cmd is not None
    assert "scale=-2:1080" in " ".join(cmd)


def test_build_ffmpeg_command_skips_no_audio():
    issues = [make_issue(ISSUE_NO_AUDIO, "No audio stream found")]
    cmd, out = build_ffmpeg_command(r"Z:\Movies\file.mp4", issues)
    assert cmd is None and out is None


def test_build_ffmpeg_command_legacy_string_issues():
    cmd, out = build_ffmpeg_command(
        r"Z:\Movies\file.mkv",
        "Container is not allowed: mkv, 10bit H.264 (bad for Plex)",
    )
    assert cmd is not None
    assert out.endswith(".mp4")
    assert "-c:v" in cmd
