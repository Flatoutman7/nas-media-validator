import sys

from nas_checker.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["--gui"] + sys.argv[1:]))
