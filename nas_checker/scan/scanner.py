import os

MEDIA_EXTENSIONS = (
    ".avi",
    ".flv",
    ".iso",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".ts",
    ".vob",
    ".webm",
    ".wmv",
)


def scan_folder(path, resume_after=None):
    """Yield full paths for media files under `path`, optionally resuming.

    If `resume_after` is provided, the generator skips files up to and including
    `resume_after` so the next run can continue from where the last run left off.
    """

    if resume_after is None:
        resume_after_key = None
        should_skip_until_resume_marker = False
    else:
        resume_after_norm = os.path.normpath(resume_after)
        resume_after_key = os.path.normcase(os.path.abspath(resume_after_norm))
        # Only skip if the marker file still exists; otherwise resume would yield nothing.
        should_skip_until_resume_marker = os.path.isfile(resume_after_norm)

    def walk_error(error):
        # An unavailable share or unreadable subtree is not a successful empty scan.
        raise error

    for root, dirs, filenames in os.walk(path, onerror=walk_error):
        dirs.sort()
        for file in sorted(filenames):
            if not file.lower().endswith(MEDIA_EXTENSIONS):
                continue

            file_path = os.path.normpath(os.path.join(root, file))

            if should_skip_until_resume_marker:
                # Normalize identity only; preserve traversal order and returned spelling.
                if os.path.normcase(os.path.abspath(file_path)) == resume_after_key:
                    should_skip_until_resume_marker = False
                # Skip everything until we reach (and then skip) the resume marker.
                continue

            yield file_path
