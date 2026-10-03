# scripts/cleanup_duplicates.py
"""
One-off cleanup script: removes duplicate messages from the messages
table. Two messages are duplicates if they have the same
conversation_id, role, and content.

Keeps the OLDEST copy (lowest created_at), deletes the rest.

Run from anywhere:
    python scripts/cleanup_duplicates.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the project root importable when this script is run directly.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def main() -> int:
    from app.bootstrap import bootstrap
    from app.lifecycle import shutdown

    ctx = bootstrap()
    try:
        conn = ctx.database.connection

        rows = conn.execute(
            """
            SELECT message_id, conversation_id, role, content, created_at
            FROM messages
            ORDER BY conversation_id, role, content, created_at ASC
            """
        ).fetchall()

        seen: dict = {}
        to_delete: list[str] = []
        for r in rows:
            key = (r["conversation_id"], r["role"], r["content"])
            if key in seen:
                to_delete.append(r["message_id"])
            else:
                seen[key] = r["message_id"]

        print(f"Total messages: {len(rows)}")
        print(f"Duplicate rows to delete: {len(to_delete)}")

        if to_delete:
            with conn:
                for mid in to_delete:
                    conn.execute(
                        "DELETE FROM messages WHERE message_id = ?;",
                        (mid,),
                    )
            print(f"Deleted {len(to_delete)} duplicate rows.")
        else:
            print("Nothing to delete.")

        remaining = conn.execute(
            "SELECT COUNT(*) AS n FROM messages;"
        ).fetchone()
        print(f"Total messages remaining: {remaining['n']}")
    finally:
        shutdown(ctx)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())