"""Абсолютна точка входу для автозапуску з довільної робочої папки."""

import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from blackout_planner.app import main

    main()
