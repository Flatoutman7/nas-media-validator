import os

MEDIA_EXTENSIONS = (".mp4", ".mkv", ".avi", ".mov", ".m4v")


def _raise_folder_error(error):
    raise OSError(
        f"Cannot read media folder '{error.filename}': {error.strerror}. "
        "Check that the folder is available and you have permission to open it."
    ) from error


def validate_scan_path(path):
    """Reject missing or unreadable roots before starting a scan."""
    if not path:
        raise ValueError("Select a media folder before scanning.")
    try:
        with os.scandir(path) as entries:
            next(entries, None)
    except OSError as error:
        _raise_folder_error(error)


def scan_folder(path, resume_after=None):
    """Yield full paths for media files under `path`, optionally resuming.

    If `resume_after` is provided, the generator skips files up to and including
    `resume_after` so the next run can continue from where the last run left off.
    """

    if resume_after is None:
        resume_after_norm = None
        should_skip_until_resume_marker = False
    else:
        resume_after_norm = os.path.normpath(resume_after)
        # Only skip if the marker file still exists; otherwise resume would yield nothing.
        should_skip_until_resume_marker = os.path.isfile(resume_after_norm)

    for root, dirs, filenames in os.walk(path, onerror=_raise_folder_error):
        for file in filenames:
            if not file.lower().endswith(MEDIA_EXTENSIONS):
                continue

            file_path = os.path.normpath(os.path.join(root, file))

            if should_skip_until_resume_marker:
                if file_path == resume_after_norm:
                    should_skip_until_resume_marker = False
                # Skip everything until we reach (and then skip) the resume marker.
                continue

            yield file_path
