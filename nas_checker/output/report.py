import csv
import json
import os

from nas_checker.scan.issues import issue_code, issue_message, normalize_issues


def save_report(bad_files, filename="bad_media_report.csv"):
    """Write a CSV report of files and their associated issues.

    Each (filepath, issues) entry is expanded to one row per issue.
    """

    with open(filename, "w", newline="", encoding="utf-8") as file:

        writer = csv.writer(file)

        writer.writerow(["File", "IssueCode", "Issue"])

        for filepath, issues in bad_files:
            for issue in normalize_issues(issues):
                writer.writerow(
                    [filepath, issue_code(issue) or "", issue_message(issue)]
                )


def save_report_json(bad_files, filename="bad_media_report.json"):
    """Write a JSON report of files and their associated structured issues."""

    payload = []
    for filepath, issues in bad_files:
        payload.append(
            {
                "file": filepath,
                "issues": normalize_issues(issues),
            }
        )

    with open(filename, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)


def export_report_csv(bad_files, filename: str) -> None:
    save_report(bad_files, filename=filename)


def export_report_json(bad_files, filename: str) -> None:
    save_report_json(bad_files, filename=filename)


def export_path_with_format(base_path: str, fmt: str) -> str:
    """Return an export filename with the requested extension."""

    root, ext = os.path.splitext(base_path)
    if fmt == "json":
        return root + ".json" if ext.lower() != ".json" else base_path
    return root + ".csv" if ext.lower() != ".csv" else base_path
