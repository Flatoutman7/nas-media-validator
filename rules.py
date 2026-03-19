"""
Compatibility wrapper for `nas_checker.scan.rules`.
"""

from nas_checker.scan.rules import analyze_file, check_file  # noqa: F401

__all__ = ["analyze_file", "check_file"]

