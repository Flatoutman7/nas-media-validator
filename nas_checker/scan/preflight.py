import shutil
from typing import Iterable


def is_tool_available(name: str) -> bool:
    return shutil.which(name) is not None


def run_preflight_checks(require_ffmpeg: bool = False) -> list[str]:
    """Return a list of human-readable errors when dependencies are missing."""

    errors: list[str] = []
    if not is_tool_available("ffprobe"):
        errors.append("ffprobe not found on PATH (required for scanning)")
    if require_ffmpeg and not is_tool_available("ffmpeg"):
        errors.append("ffmpeg not found on PATH (required for auto-fix)")
    return errors


def format_preflight_error(errors: Iterable[str]) -> str:
    lines = list(errors)
    if not lines:
        return ""
    return "Preflight failed:\n" + "\n".join(f"  - {e}" for e in lines)
