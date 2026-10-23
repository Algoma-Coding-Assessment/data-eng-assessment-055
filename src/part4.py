"""Part 4: answers.

    python -m src.part4
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "output"
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://takehome:takehome@localhost:5432/takehome")


def main() -> None:
    raise NotImplementedError


if __name__ == "__main__":
    main()
