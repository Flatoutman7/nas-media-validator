"""
Compatibility wrapper.

Implementation lives in `health.scan_metadata_cache`.
"""

from health.scan_metadata_cache import (  # noqa: F401
    ScanMetadataCache,
    canonicalize_path_key,
)

__all__ = ["ScanMetadataCache", "canonicalize_path_key"]

