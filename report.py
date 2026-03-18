import csv

def save_report(bad_files, filename="bad_media_report.csv"):

    with open(filename, "w", newline="", encoding="utf-8") as file:

        writer = csv.writer(file)

        writer.writerow(["File", "Issue"])

        for filepath, issues in bad_files:

            for issue in issues:

                writer.writerow([filepath, issue])