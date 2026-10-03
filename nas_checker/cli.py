import argparse
import sys

from nas_checker.scan.preflight import format_preflight_error, run_preflight_checks
from nas_checker.scan.scan_path_settings import (
    resolve_scan_path,
    save_scan_path_settings,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nas-media-validator",
        description="Scan a NAS media library and report validation issues.",
    )
    parser.add_argument(
        "--path",
        "-p",
        dest="path",
        help="Media library root path to scan",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the PySide6 GUI instead of a headless scan",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Override parallel scan worker count",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable incremental metadata cache",
    )
    parser.add_argument(
        "--export",
        dest="export_path",
        metavar="FILE",
        help="Write scan report to FILE (.csv or .json)",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    if argv is None:
        argv = sys.argv[1:]
    return build_arg_parser().parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    scan_path = resolve_scan_path(cli_path=args.path)

    if args.gui:
        if args.path:
            save_scan_path_settings({"media_folder": scan_path})

        preflight_errors = run_preflight_checks(require_ffmpeg=False)
        if preflight_errors:
            print(format_preflight_error(preflight_errors), file=sys.stderr)
            return 1

        from PySide6.QtWidgets import QApplication

        from nas_checker.gui.gui import MainWindow

        app = QApplication(sys.argv)
        window = MainWindow(media_folder=scan_path)
        window.resize(800, 600)
        window.show()
        return app.exec()

    preflight_errors = run_preflight_checks(require_ffmpeg=False)
    if preflight_errors:
        print(format_preflight_error(preflight_errors), file=sys.stderr)
        return 1

    from nas_checker.scan.main import run_scan

    run_scan(
        path=scan_path,
        max_workers=args.workers,
        use_cache=not args.no_cache,
        export_path=args.export_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
