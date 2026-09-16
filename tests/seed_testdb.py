"""Generate tests/testdb/cass.db from a live cass pull."""

from __future__ import annotations

__docformat__ = "google"

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTDB_DIR = ROOT / "tests" / "testdb"


def main() -> None:
    import sqlite_utils

    from cass.actions.config import load_config
    from cass.actions.pull import pull_all
    from cass.db.core import db_path
    from cass.db.sync import snapshot_canvas_synced

    # Pull into the project root (uses cass.toml)
    cfg = load_config()
    pull_all(cfg)

    # Copy to testdb/
    TESTDB_DIR.mkdir(exist_ok=True)
    src = db_path(cfg.root)
    dst = TESTDB_DIR / "cass.db"
    shutil.copy2(src, dst)

    # Snapshot synced tables on the copy so tests start clean
    sdb = sqlite_utils.Database(str(dst))
    snapshot_canvas_synced(sdb)
    sdb.conn.close()

    print(f"Snapshot saved to {dst}")


if __name__ == "__main__":
    main()
