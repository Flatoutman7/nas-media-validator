import os

MEDIA_EXTENSIONS = (".mp4", ".mkv", ".avi", ".mov", ".m4v")

def scan_folder(path):

    for root, dirs, filenames in os.walk(path):
        for file in filenames:

            if not file.lower().endswith(MEDIA_EXTENSIONS):
                continue

            yield os.path.join(root, file)