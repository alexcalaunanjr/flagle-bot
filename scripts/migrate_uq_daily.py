#!/usr/bin/env python3
"""Migrate the uq_chat_daily constraint to a partial unique index (daily mode only).

This allows multiple random games per chat per day.

Run once:
    python -m scripts.migrate_uq_daily
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import engine


async def migrate():
    async with engine.begin() as conn:
        await conn.execute(__import__("sqlalchemy", fromlist=["text"]).text(
            "ALTER TABLE game_sessions DROP CONSTRAINT IF EXISTS uq_chat_daily"
        ))
        await conn.execute(__import__("sqlalchemy", fromlist=["text"]).text(
            "DROP INDEX IF EXISTS uq_chat_daily"
        ))
        await conn.execute(__import__("sqlalchemy", fromlist=["text"]).text(
            "CREATE UNIQUE INDEX uq_chat_daily ON game_sessions (chat_id, created_date) "
            "WHERE mode = 'daily'"
        ))
    print("✅ Migrated uq_chat_daily to partial unique index (daily mode only).")


if __name__ == "__main__":
    asyncio.run(migrate())
