"""
Compatibility wrapper for `nas_checker.scan.scanner`.
"""

from nas_checker.scan.scanner import MEDIA_EXTENSIONS, scan_folder  # noqa: F401

__all__ = ["MEDIA_EXTENSIONS", "scan_folder"]

