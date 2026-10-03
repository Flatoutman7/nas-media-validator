import os
import sys


def persistent_data_path(source_path: str) -> str:
    """Keep packaged application data outside PyInstaller's temporary bundle."""
    if not getattr(sys, "frozen", False):
        return source_path
    data_dir = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, os.path.basename(source_path))
