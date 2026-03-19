from nas_checker.scan.scanner import scan_folder
from concurrent.futures import ThreadPoolExecutor, as_completed
from nas_checker.output.report import save_report
from health.hardware import recommend_scan_workers
from health.scan_metadata_cache import ScanMetadataCache
from nas_checker.scan.scan_rules_settings import load_scan_rules_settings

MEDIA_FOLDER = "Z:/"


def run_scan(
    path=MEDIA_FOLDER,
    progress_callback=None,
    log_callback=None,
    issue_callback=None,
    resume_after=None,
    stop_event=None,
    max_workers=None,
):
    """Scan media files and validate them against rules.

    Supports resuming after a given file and early cancellation via `stop_event`.
    """

    import time
    import os
    from concurrent.futures import wait, FIRST_COMPLETED

    stats_delta = {
        "scanned_files": 0,
        "files_with_issues": 0,
        "container_not_allowed": 0,
        "video_codec_counts": {},
        "audio_codec_counts": {},
        "subtitle_tracks": 0,
        "missing_video": 0,
        "missing_audio": 0,
        "media_info_errors": 0,
        "small_files": 0,
        # Extended analyzer counts:
        "hdr_detected_files": 0,
        "tenbit_h264_files": 0,
        "pgs_subtitles_files": 0,
        "multiple_commentary_files": 0,
        "wrong_resolution_files": 0,
        "multiple_audio_tracks_files": 0,
        "multiple_subtitle_tracks_files": 0,
        "text_subtitles_files": 0,
    }

    def log(msg):
        if log_callback:
            log_callback(msg)

    log(f"Scanning: {path}")
    if resume_after:
        log(f"Resuming after: {resume_after}")
    log("Checking files...")

    if max_workers is None:
        max_workers = recommend_scan_workers(path)

    log(f"Parallel workers: {max_workers}")

    rules_settings = load_scan_rules_settings()
    cache = ScanMetadataCache(
        db_path=os.path.join(os.path.dirname(__file__), "scan_metadata.db"),
        rules_settings=rules_settings,
    )
    cache_hits = 0
    cache_misses = 0

    bad_files = []
    files_processed = 0
    total_discovered = 0

    start_time = time.time()

    cancelled = False
    resume_after_next = resume_after

    # We use contiguous completion (by submission index) to avoid skipping files
    # that haven't actually finished yet.
    index_to_file = []
    completed_indices = set()
    next_resume_index = 0  # first not-yet-completed index

    def process_file(file):
        return cache.analyze_file_cached(file)  # (issues, stats, from_cache)

    executor = ThreadPoolExecutor(max_workers=max_workers)
    futures = set()
    future_to_index = {}
    shutdown_called = False

    try:
        for file in scan_folder(path, resume_after=resume_after):
            if stop_event is not None and stop_event.is_set():
                cancelled = True
                break

            idx = len(index_to_file)
            index_to_file.append(file)

            future = executor.submit(process_file, file)
            futures.add(future)
            future_to_index[future] = idx
            total_discovered += 1

            # Keep the queue from growing forever.
            if len(futures) >= 64:
                done, futures = wait(futures, return_when=FIRST_COMPLETED)
                for future in done:
                    idx = future_to_index.pop(future)
                    file_path = index_to_file[idx]
                    issues, file_stats, from_cache = future.result()
                    if from_cache:
                        cache_hits += 1
                    else:
                        cache_misses += 1

                    files_processed += 1
                    completed_indices.add(idx)
                    while next_resume_index in completed_indices:
                        next_resume_index += 1

                    if issues:
                        bad_files.append((file_path, issues))
                        stats_delta["files_with_issues"] += 1
                        if issue_callback:
                            for issue in issues:
                                issue_callback(file_path, issue)

                    # stats aggregation uses the per-file stats regardless of issue count
                    stats_delta["scanned_files"] += 1
                    if not file_stats.get("container_is_allowed", True):
                        stats_delta["container_not_allowed"] += 1
                    stats_delta["subtitle_tracks"] += file_stats.get(
                        "subtitle_tracks", 0
                    )

                    if file_stats.get("hdr_detected"):
                        stats_delta["hdr_detected_files"] += 1
                    if file_stats.get("tenbit_h264_issue"):
                        stats_delta["tenbit_h264_files"] += 1
                    if file_stats.get("pgs_subtitles_detected"):
                        stats_delta["pgs_subtitles_files"] += 1
                    if file_stats.get("multiple_commentary_issue"):
                        stats_delta["multiple_commentary_files"] += 1
                    if file_stats.get("wrong_resolution_issue"):
                        stats_delta["wrong_resolution_files"] += 1
                    if file_stats.get("multiple_audio_tracks_issue"):
                        stats_delta["multiple_audio_tracks_files"] += 1
                    if file_stats.get("multiple_subtitle_tracks_issue"):
                        stats_delta["multiple_subtitle_tracks_files"] += 1
                    if file_stats.get("text_subtitles_detected"):
                        stats_delta["text_subtitles_files"] += 1

                    if file_stats.get("media_info_error"):
                        stats_delta["media_info_errors"] += 1
                    if file_stats.get("min_file_size_issue"):
                        stats_delta["small_files"] += 1

                    if not file_stats.get("media_info_error", False):
                        if not file_stats.get("video_found", False):
                            stats_delta["missing_video"] += 1
                        if not file_stats.get("audio_found", False):
                            stats_delta["missing_audio"] += 1

                    for codec in file_stats.get("video_codecs", []):
                        stats_delta["video_codec_counts"][codec] = (
                            stats_delta["video_codec_counts"].get(codec, 0) + 1
                        )
                    for codec in file_stats.get("audio_codecs", []):
                        stats_delta["audio_codec_counts"][codec] = (
                            stats_delta["audio_codec_counts"].get(codec, 0) + 1
                        )

                    elapsed = time.time() - start_time
                    speed = files_processed / elapsed if elapsed > 0 else 0
                    remaining = (
                        (total_discovered - files_processed) / speed if speed > 0 else 0
                    )

                    if progress_callback:
                        progress_callback(
                            files_processed, total_discovered, speed, remaining
                        )

                if stop_event is not None and stop_event.is_set():
                    cancelled = True
                    break

        if cancelled:
            # Cancel work that hasn't started yet; don't wait for running tasks.
            for future in futures:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            shutdown_called = True

            last_idx = next_resume_index - 1
            resume_after_next = (
                index_to_file[last_idx] if last_idx >= 0 else resume_after
            )

            log("Scan stopped.")
            return {
                "bad_files": bad_files,
                "cancelled": True,
                "resume_after": resume_after_next,
                "stats": stats_delta,
            }

        # Finish remaining futures (normal completion).
        for future in futures:
            idx = future_to_index.pop(future)
            file_path = index_to_file[idx]
            issues, file_stats, from_cache = future.result()
            if from_cache:
                cache_hits += 1
            else:
                cache_misses += 1

            files_processed += 1
            completed_indices.add(idx)
            while next_resume_index in completed_indices:
                next_resume_index += 1

            if issues:
                bad_files.append((file_path, issues))
                stats_delta["files_with_issues"] += 1
                if issue_callback:
                    for issue in issues:
                        issue_callback(file_path, issue)

            stats_delta["scanned_files"] += 1
            if not file_stats.get("container_is_allowed", True):
                stats_delta["container_not_allowed"] += 1
            stats_delta["subtitle_tracks"] += file_stats.get("subtitle_tracks", 0)

            if file_stats.get("hdr_detected"):
                stats_delta["hdr_detected_files"] += 1
            if file_stats.get("tenbit_h264_issue"):
                stats_delta["tenbit_h264_files"] += 1
            if file_stats.get("pgs_subtitles_detected"):
                stats_delta["pgs_subtitles_files"] += 1
            if file_stats.get("multiple_commentary_issue"):
                stats_delta["multiple_commentary_files"] += 1
            if file_stats.get("wrong_resolution_issue"):
                stats_delta["wrong_resolution_files"] += 1
            if file_stats.get("multiple_audio_tracks_issue"):
                stats_delta["multiple_audio_tracks_files"] += 1
            if file_stats.get("multiple_subtitle_tracks_issue"):
                stats_delta["multiple_subtitle_tracks_files"] += 1
            if file_stats.get("text_subtitles_detected"):
                stats_delta["text_subtitles_files"] += 1

            if file_stats.get("media_info_error"):
                stats_delta["media_info_errors"] += 1
            if file_stats.get("min_file_size_issue"):
                stats_delta["small_files"] += 1

            if not file_stats.get("media_info_error", False):
                if not file_stats.get("video_found", False):
                    stats_delta["missing_video"] += 1
                if not file_stats.get("audio_found", False):
                    stats_delta["missing_audio"] += 1

            for codec in file_stats.get("video_codecs", []):
                stats_delta["video_codec_counts"][codec] = (
                    stats_delta["video_codec_counts"].get(codec, 0) + 1
                )
            for codec in file_stats.get("audio_codecs", []):
                stats_delta["audio_codec_counts"][codec] = (
                    stats_delta["audio_codec_counts"].get(codec, 0) + 1
                )

            elapsed = time.time() - start_time
            speed = files_processed / elapsed if elapsed > 0 else 0
            remaining = (total_discovered - files_processed) / speed if speed > 0 else 0

            if progress_callback:
                progress_callback(files_processed, total_discovered, speed, remaining)

        log("")
        log("Scan complete")
        log(f"Incremental cache: {cache_hits} hits / {cache_misses} misses")
        log(f"Files with issues: {len(bad_files)}")

        save_report(bad_files)

        return {
            "bad_files": bad_files,
            "cancelled": False,
            "resume_after": None,
            "stats": stats_delta,
        }
    finally:
        if not shutdown_called:
            executor.shutdown(wait=True)


if __name__ == "__main__":

    import sys

    if "--gui" in sys.argv:

        from PySide6.QtWidgets import QApplication
        from nas_checker.gui.gui import MainWindow

        app = QApplication(sys.argv)

        window = MainWindow()
        window.resize(800, 600)
        window.show()

        sys.exit(app.exec())

    else:
        run_scan()
