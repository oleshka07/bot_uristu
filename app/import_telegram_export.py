"""Import a Telegram Desktop export (result.json). Run inside the container:

    docker cp result.json networking-ai-web-1:/tmp/result.json
    docker compose exec web python -m app.import_telegram_export /tmp/result.json

Options:
    --no-backfill   style only, don't add historical interactions
    --create-all    also CREATE contacts for every person you actually
                    wrote to (bots/service chats are skipped); they get
                    the "tg-export" tag and quarterly cadence — triage
                    them later via the queue's stop-list or the web UI
"""

from __future__ import annotations

import json
import sys

from .core.database import SessionLocal, init_db
from .modules.integrations.tgexport.importer import import_export

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("Usage: python -m app.import_telegram_export <path/to/result.json>")
        sys.exit(1)
    backfill = "--no-backfill" not in sys.argv
    create_missing = "--create-all" in sys.argv

    init_db()
    db = SessionLocal()
    try:
        report = import_export(
            db, args[0], backfill=backfill, create_missing=create_missing
        )
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    finally:
        db.close()
