"""Quick DB inspector used only during manual verification."""

from __future__ import annotations

import sqlite3
import sys


def main(db_path: str = "alewife.db") -> int:
    conn = sqlite3.connect(db_path)
    try:
        summary = conn.execute(
            "select count(*), min(seed_rating), max(seed_rating) from building"
        ).fetchone()
        print(f"count={summary[0]} min_rating={summary[1]} max_rating={summary[2]}")
        hanover = conn.execute(
            "select name, seed_rating, seed_review_count from building where slug = ?",
            ("hanover-alewife",),
        ).fetchone()
        print(f"hanover_spot_check={hanover}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
