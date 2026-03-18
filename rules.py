import subprocess
import json
import os
import re

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


def analyze_file(file):
    """Return (issues, stats) for a file using a single ffprobe call.

    `issues` is the list of validation problems, and `stats` contains per-file
    stream/container facts for building library-wide statistics.
    """

    stats = {
        "container_is_mp4": file.lower().endswith(".mp4"),
        "min_file_size_issue": False,
        "media_info_error": False,
        "video_found": False,
        "audio_found": False,
        "subtitle_tracks": 0,
        "video_codecs": [],
        "audio_codecs": [],
        # Extended analyzer fields:
        "video_width": None,
        "video_height": None,
        "bit_depth": None,
        "frame_rate": None,
        "hdr_detected": False,
        "audio_track_count": 0,
        "commentary_track_count": 0,
        "subtitle_codec_counts": {},
        "expected_resolution_height": None,
        "tenbit_h264_issue": False,
        "pgs_subtitles_detected": False,
        "hdr_detected_issue": False,
        "multiple_audio_tracks_issue": False,
        "multiple_subtitle_tracks_issue": False,
        "text_subtitles_detected": False,
        "multiple_commentary_issue": False,
        "wrong_resolution_issue": False,
    }

    issues = []
    issues.extend(check_min_file_size(file))
    if issues and issues[0] == "File suspiciously small":
        stats["min_file_size_issue"] = True

    # check container
    if not stats["container_is_mp4"]:
        issues.append("Container is not MP4")

    def parse_rational(value):
        if not value:
            return None
        try:
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str) and "/" in value:
                num, den = value.split("/", 1)
                num_f = float(num.strip())
                den_f = float(den.strip())
                if den_f == 0:
                    return None
                return num_f / den_f
            return float(value)
        except Exception:
            return None

    def expected_resolution_height_from_filename(path):
        base = os.path.basename(path).lower()
        # Common patterns: 1080p / 720p / 2160p
        m = re.search(r"(\d{3,4})p", base)
        if not m:
            return None
        try:
            h = int(m.group(1))
        except Exception:
            return None
        return h

    stats["expected_resolution_height"] = expected_resolution_height_from_filename(file)

    try:
        info = get_media_info(file)
    except Exception:
        issues.append("Could not read media info")
        stats["media_info_error"] = True
        return issues, stats

    video_primary_codec = None
    for stream in info.get("streams", []):
        codec_type = stream.get("codec_type")
        codec_name = stream.get("codec_name") or ""
        disposition = stream.get("disposition") or {}
        tags = stream.get("tags") or {}

        if codec_type == "video":
            stats["video_found"] = True
            stats["video_codecs"].append(codec_name)
            if video_primary_codec is None:
                video_primary_codec = codec_name
                stats["video_width"] = stream.get("width")
                stats["video_height"] = stream.get("height")

                # Bit depth extraction
                bprs = stream.get("bits_per_raw_sample")
                if bprs is not None:
                    try:
                        stats["bit_depth"] = int(bprs)
                    except Exception:
                        stats["bit_depth"] = None
                if stats["bit_depth"] is None:
                    pix_fmt = (stream.get("pix_fmt") or "").lower()
                    m_bit = re.search(r"p(\d{2})", pix_fmt)
                    if m_bit:
                        try:
                            stats["bit_depth"] = int(m_bit.group(1))
                        except Exception:
                            stats["bit_depth"] = None

                # Frame rate extraction
                fr = stream.get("avg_frame_rate") or stream.get("r_frame_rate")
                stats["frame_rate"] = parse_rational(fr)

                # HDR-ish detection based on color transfer
                color_transfer = (stream.get("color_transfer") or "").lower()
                if color_transfer in {"smpte2084", "arib-std-b67"}:
                    stats["hdr_detected"] = True

            if codec_name != "hevc":
                issues.append(f"Video codec is {codec_name}, not HEVC")

        elif codec_type == "audio":
            stats["audio_found"] = True
            stats["audio_track_count"] += 1
            stats["audio_codecs"].append(codec_name)
            if codec_name != "aac":
                issues.append(f"Audio codec is {codec_name}, not AAC")

            commentary = bool(disposition.get("commentary", 0))
            title = (tags.get("title") or "").lower()
            if "commentary" in title:
                commentary = True
            if commentary:
                stats["commentary_track_count"] += 1

        elif codec_type == "subtitle":
            stats["subtitle_tracks"] += 1
            stats["subtitle_codec_counts"][codec_name] = (
                stats["subtitle_codec_counts"].get(codec_name, 0) + 1
            )

            # PGS is typically `hdmv_pgs_subtitle`
            if codec_name == "hdmv_pgs_subtitle":
                stats["pgs_subtitles_detected"] = True

    if not stats["video_found"]:
        issues.append("No video stream found")

    if not stats["audio_found"]:
        issues.append("No audio stream found")

    if stats["subtitle_tracks"] > 0:
        issues.append("Subtitle track detected")

    # Derived issue checks:
    if stats.get("hdr_detected"):
        stats["hdr_detected_issue"] = True
        issues.append("HDR detected")

    if stats.get("audio_track_count", 0) > 1:
        stats["multiple_audio_tracks_issue"] = True
        issues.append("Multiple audio tracks detected")

    if (
        stats["bit_depth"] is not None
        and video_primary_codec is not None
        and video_primary_codec.lower().startswith("h264")
        and stats["bit_depth"] >= 10
    ):
        stats["tenbit_h264_issue"] = True
        issues.append("10bit H.264 (bad for Plex)")

    if stats["pgs_subtitles_detected"]:
        issues.append("PGS subtitles detected")

    if stats["subtitle_tracks"] > 1:
        stats["multiple_subtitle_tracks_issue"] = True
        issues.append("Multiple subtitle tracks detected")

    if stats["subtitle_tracks"] > 0 and not stats["pgs_subtitles_detected"]:
        stats["text_subtitles_detected"] = True
        issues.append("Text subtitles detected")

    if stats["commentary_track_count"] > 1:
        stats["multiple_commentary_issue"] = True
        issues.append("Multiple commentary tracks detected")

    if (
        stats["expected_resolution_height"] is not None
        and stats["video_height"] is not None
        and int(stats["expected_resolution_height"]) != int(stats["video_height"])
    ):
        stats["wrong_resolution_issue"] = True
        issues.append(
            f"Wrong resolution: expected {stats['expected_resolution_height']}p, found {stats['video_height']}p"
        )

    return issues, stats


def check_file(file):
    """Validate a media file against your rules and return a list of issues."""
    issues, _stats = analyze_file(file)
    return issues
