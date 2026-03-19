"""
Compatibility wrapper for `nas_checker.media.autofix`.
"""

from nas_checker.media.autofix import build_ffmpeg_command, run_ffmpeg  # noqa: F401

__all__ = ["build_ffmpeg_command", "run_ffmpeg"]

