"""
Compatibility wrapper.

Implementation lives in `health.hardware`.
"""

from health.hardware import (  # noqa: F401
    detect_nvidia_gpu,
    get_storage_profile,
    recommend_scan_workers,
)

__all__ = ["detect_nvidia_gpu", "get_storage_profile", "recommend_scan_workers"]

