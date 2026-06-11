import os

from nas_checker.scan.scanner import MEDIA_EXTENSIONS, scan_folder


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"media")


def test_scan_folder_recurses_across_media_directories(tmp_path):
    movie = tmp_path / "Movies" / "Movie One (2024).mkv"
    tv = tmp_path / "TV" / "Show" / "Season 01" / "Show - S01E01.mp4"
    other = tmp_path / "Other Media" / "Concert.webm"
    ignored = tmp_path / "Movies" / "poster.jpg"

    for path in (movie, tv, other, ignored):
        _touch(path)

    scanned = set(scan_folder(str(tmp_path)))

    assert scanned == {
        os.path.normpath(str(movie)),
        os.path.normpath(str(tv)),
        os.path.normpath(str(other)),
    }


def test_scan_folder_accepts_common_media_extensions(tmp_path):
    paths = []
    for extension in MEDIA_EXTENSIONS:
        path = tmp_path / "Movies" / f"sample{extension.upper()}"
        _touch(path)
        paths.append(os.path.normpath(str(path)))

    assert set(scan_folder(str(tmp_path))) == set(paths)


def test_scan_folder_resume_after_handles_new_extensions(tmp_path):
    first = tmp_path / "Movies" / "a_movie.ts"
    second = tmp_path / "Movies" / "b_movie.wmv"
    for path in (first, second):
        _touch(path)

    assert list(scan_folder(str(tmp_path), resume_after=str(first))) == [
        os.path.normpath(str(second))
    ]
