"""
Compatibility wrapper for PyInstaller/spec and older entrypoints.
"""

from nas_checker.gui.gui_entry import main  # noqa: F401


if __name__ == "__main__":
    main()

