"""Part 3: history.

    python -m src.part3 [release_dir]
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://takehome:takehome@localhost:5432/takehome")


def main(release_dir: Path) -> None:
    raise NotImplementedError


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else DATA_DIR / "fhfa")
