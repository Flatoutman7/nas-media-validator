import os
import ntpath
import posixpath
from types import SimpleNamespace

import pytest

from nas_checker.scan import scanner
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


def test_missing_root_is_not_a_successful_empty_scan(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        list(scan_folder(str(tmp_path / 'missing')))


def test_unreadable_subtree_is_not_silently_skipped(monkeypatch):
    import pytest

    def walk(path, onerror):
        onerror(PermissionError('share unavailable'))
        return []

    monkeypatch.setattr(os, 'walk', walk)
    with pytest.raises(PermissionError):
        list(scan_folder('Z:/Media'))


@pytest.mark.parametrize(
    'root,marker',
    [
        (r'C:\Media Library', r'c:\MEDIA LIBRARY\a CLIP.MP4'),
        (r'C:\Media Library', 'c:/MEDIA LIBRARY/./a CLIP.MP4'),
        (r'\\NAS\Media Library', r'\\nas\MEDIA LIBRARY\a CLIP.MP4'),
        (r'\\NAS\Media Library', '//nas/MEDIA LIBRARY/./a CLIP.MP4'),
    ],
)
def test_windows_resume_path_identity_preserves_filename_order(monkeypatch, root, marker):
    # Exercise Windows identity rules on Linux CI too, without changing global os.path.
    paths = SimpleNamespace(
        **{name: getattr(ntpath, name) for name in ('normpath', 'normcase', 'abspath', 'join')},
        isfile=lambda path: ntpath.normcase(ntpath.normpath(path)) ==
        ntpath.normcase(ntpath.join(root, 'A clip.mp4')),
    )

    def walk(path, onerror):
        assert path == root
        yield root, [], ['b clip.mp4', 'A clip.mp4', 'Z clip.mp4', 'poster.jpg']

    monkeypatch.setattr(scanner, 'os', SimpleNamespace(path=paths, walk=walk))
    assert list(scan_folder(root, resume_after=marker)) == [
        ntpath.join(root, 'Z clip.mp4'),
        ntpath.join(root, 'b clip.mp4'),
    ]


def test_posix_resume_keeps_case_distinct(monkeypatch):
    paths = SimpleNamespace(
        **{name: getattr(posixpath, name) for name in ('normpath', 'normcase', 'abspath', 'join')},
        isfile=lambda path: path == '/media/a.mp4',
    )

    def walk(path, onerror):
        yield path, [], ['a.mp4', 'A.mp4', 'b.mp4']

    monkeypatch.setattr(scanner, 'os', SimpleNamespace(path=paths, walk=walk))
    assert list(scan_folder('/media', resume_after='/media/a.mp4')) == ['/media/b.mp4']


@pytest.mark.parametrize('relative_root', [False, True])
def test_resume_matches_absolute_and_relative_paths(tmp_path, monkeypatch, relative_root):
    folder = tmp_path / 'Media Library'
    first = folder / 'A clip.mp4'
    second = folder / 'B clip.mp4'
    for path in (first, second):
        _touch(path)
    monkeypatch.chdir(tmp_path)
    root = 'Media Library' if relative_root else str(folder)
    marker = str(first) if relative_root else os.path.join('Media Library', '.', first.name)
    assert list(scan_folder(root, resume_after=marker)) == [os.path.join(root, second.name)]


def test_resume_preserves_sorted_directory_traversal(tmp_path):
    for relative in ('B/final.mp4', 'A/b.mp4', 'A/a.mp4', 'root.mp4'):
        _touch(tmp_path / relative)
    assert list(scan_folder(str(tmp_path), resume_after=str(tmp_path / 'A' / 'a.mp4'))) == [
        str(tmp_path / 'A' / 'b.mp4'), str(tmp_path / 'B' / 'final.mp4'),
    ]


def test_missing_resume_marker_restarts_scan(tmp_path):
    first = tmp_path / 'a.mp4'
    _touch(first)
    assert list(scan_folder(str(tmp_path), resume_after=str(tmp_path / 'missing.mp4'))) == [str(first)]


@pytest.mark.skipif(os.name != 'nt', reason='requires a real Windows filesystem')
def test_resume_matches_case_variant_on_windows_filesystem(tmp_path):
    first = tmp_path / 'Média 日本語' / 'A clip.MP4'
    second = first.with_name('B clip.mp4')
    for path in (first, second):
        _touch(path)
    marker = str(first).upper().replace('\\', '/')
    assert os.path.isfile(marker)
    assert list(scan_folder(str(tmp_path), resume_after=marker)) == [str(second)]
