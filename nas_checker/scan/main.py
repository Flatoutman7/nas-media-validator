import os
import time

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from nas_checker.output.report import export_report_csv, export_report_json, save_report
from nas_checker.scan.issues import issue_message, normalize_issues
from nas_checker.scan.preflight import format_preflight_error, run_preflight_checks
from nas_checker.scan.scan_path_settings import resolve_scan_path
from nas_checker.scan.scan_rules_settings import load_scan_rules_settings
from nas_checker.scan.scanner import MEDIA_EXTENSIONS, scan_folder
from health.hardware import recommend_scan_workers
from health.scan_metadata_cache import ScanMetadataCache


def _empty_stats_delta():
    return {
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
        "hdr_detected_files": 0,
        "tenbit_h264_files": 0,
        "pgs_subtitles_files": 0,
        "multiple_commentary_files": 0,
        "wrong_resolution_files": 0,
        "multiple_audio_tracks_files": 0,
        "multiple_subtitle_tracks_files": 0,
        "text_subtitles_files": 0,
        "cache_hits": 0,
        "cache_misses": 0,
    }


def _process_completed_file(
    file_path,
    issues,
    file_stats,
    from_cache,
    *,
    stats_delta,
    bad_files,
    files_processed,
    total_discovered,
    start_time,
    issue_callback,
    progress_callback,
):
    """Apply per-file scan results to running counters and callbacks."""

    issues = normalize_issues(issues)

    if from_cache:
        stats_delta["cache_hits"] += 1
    else:
        stats_delta["cache_misses"] += 1

    files_processed += 1

    if issues:
        bad_files.append((file_path, issues))
        stats_delta["files_with_issues"] += 1
        if issue_callback:
            for issue in issues:
                issue_callback(file_path, issue_message(issue))

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

    elapsed = time.time() - start_time if start_time else 0
    speed = files_processed / elapsed if elapsed > 0 else 0
    remaining = (total_discovered - files_processed) / speed if speed > 0 else 0

    if progress_callback:
        progress_callback(
            files_processed,
            total_discovered,
            speed,
            remaining,
            stats_delta["cache_hits"],
            stats_delta["cache_misses"],
        )

    return files_processed


def run_scan(
    path=None,
    progress_callback=None,
    log_callback=None,
    issue_callback=None,
    resume_after=None,
    stop_event=None,
    max_workers=None,
    use_cache=True,
    export_path=None,
):
    """Scan media files and validate them against rules.

    Supports resuming after a given file and early cancellation via `stop_event`.
    """

    if path is None:
        path = resolve_scan_path()

    preflight_errors = run_preflight_checks(require_ffmpeg=False)
    if preflight_errors:
        message = format_preflight_error(preflight_errors)
        if log_callback:
            log_callback(message)
        raise RuntimeError(message)

    stats_delta = _empty_stats_delta()

    def log(msg):
        if log_callback:
            log_callback(msg)

    accepted_extensions = ", ".join(MEDIA_EXTENSIONS)
    log(f"Scanning root: {os.path.normpath(path)}")
    log(f"Accepted media extensions: {accepted_extensions}")
    if resume_after:
        log(f"Resuming after: {resume_after}")
    log("Checking files...")

    if max_workers is None:
        max_workers = recommend_scan_workers(path)

    log(f"Parallel workers: {max_workers}")

    rules_settings = load_scan_rules_settings()
    cache = None
    if use_cache:
        cache = ScanMetadataCache(
            db_path=os.path.join(os.path.dirname(__file__), "scan_metadata.db"),
            rules_settings=rules_settings,
        )

    bad_files = []
    files_processed = 0
    total_discovered = 0

    start_time = time.time()

    cancelled = False
    resume_after_next = resume_after

    index_to_file = []
    completed_indices = set()
    next_resume_index = 0

    def process_file(file):
        if cache is not None:
            return cache.analyze_file_cached(file)
        from nas_checker.scan.rules import analyze_file

        issues, stats = analyze_file(file, rules_settings=rules_settings)
        return issues, stats, False

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

            if len(futures) >= 64:
                done, futures = wait(futures, return_when=FIRST_COMPLETED)
                for future in done:
                    idx = future_to_index.pop(future)
                    file_path = index_to_file[idx]
                    issues, file_stats, from_cache = future.result()
                    files_processed = _process_completed_file(
                        file_path,
                        issues,
                        file_stats,
                        from_cache,
                        stats_delta=stats_delta,
                        bad_files=bad_files,
                        files_processed=files_processed,
                        total_discovered=total_discovered,
                        start_time=start_time,
                        issue_callback=issue_callback,
                        progress_callback=progress_callback,
                    )
                    completed_indices.add(idx)
                    while next_resume_index in completed_indices:
                        next_resume_index += 1

                if stop_event is not None and stop_event.is_set():
                    cancelled = True
                    break

        if cancelled:
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

        for future in futures:
            idx = future_to_index.pop(future)
            file_path = index_to_file[idx]
            issues, file_stats, from_cache = future.result()
            files_processed = _process_completed_file(
                file_path,
                issues,
                file_stats,
                from_cache,
                stats_delta=stats_delta,
                bad_files=bad_files,
                files_processed=files_processed,
                total_discovered=total_discovered,
                start_time=start_time,
                issue_callback=issue_callback,
                progress_callback=progress_callback,
            )
            completed_indices.add(idx)
            while next_resume_index in completed_indices:
                next_resume_index += 1

        log("")
        log("Scan complete")
        log(
            f"Incremental cache: {stats_delta['cache_hits']} hits / "
            f"{stats_delta['cache_misses']} misses"
        )
        log(f"Files with issues: {len(bad_files)}")

        report_file = export_path or "bad_media_report.csv"
        if export_path and export_path.lower().endswith(".json"):
            export_report_json(bad_files, export_path)
            log(f"Exported report: {export_path}")
        elif export_path:
            export_report_csv(bad_files, export_path)
            log(f"Exported report: {export_path}")
        else:
            save_report(bad_files, filename=report_file)

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

    from nas_checker.cli import main as cli_main

    raise SystemExit(cli_main())
