"""Part 2: fewer blanks.

    python -m src.part1 [release_dir]

You may add modules, helpers and dependencies. Keep this command working as described in the README.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
OUTPUT_DIR = REPO_ROOT / "output"


def main(release_dir: Path) -> None:
    raise NotImplementedError


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else DATA_DIR / "fhfa")
