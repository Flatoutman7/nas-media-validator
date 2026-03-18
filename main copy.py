from scanner import scan_folder
from rules import check_file
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from report import save_report

MEDIA_FOLDER = "Z:/"

print("Scanning:", MEDIA_FOLDER)

files = scan_folder(MEDIA_FOLDER)

print("Total files found:", len(files))
print()

bad_files = []

def process_file(file):

    issues = check_file(file)

    if issues:
        return (file, issues)

    return None


with ThreadPoolExecutor(max_workers=12) as executor:

    futures = [executor.submit(process_file, file) for file in files]

    for future in tqdm(
    as_completed(futures),
    total=len(files),
    desc="Checking files",
    dynamic_ncols=True,
    bar_format="{l_bar}{bar} | {n_fmt}/{total_fmt} | Elapsed: {elapsed} | ETA: {remaining} | {rate_fmt}"
):

        result = future.result()

        if result:
            bad_files.append(result)


print()
print("----- Issues Found -----")
print()

for file, issues in bad_files:

    print("File:", file)

    for issue in issues:
        print(" -", issue)

    print()


print("Scan complete")
print("Files with issues:", len(bad_files))

save_report(bad_files)
print("Report saved to bad_media_report.csv")