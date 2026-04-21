#!/usr/bin/env python3
"""Add is_sovereign column to countries and expand game_sessions.mode from VARCHAR(10) to VARCHAR(20).

This supports the new game modes: 'random:countries' and 'random:all'.

Run once:
    python -m scripts.migrate_sovereignty
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import engine


async def migrate():
    async with engine.begin() as conn:
        await conn.execute(__import__("sqlalchemy", fromlist=["text"]).text(
            "ALTER TABLE countries ADD COLUMN IF NOT EXISTS is_sovereign BOOLEAN DEFAULT TRUE"
        ))
        await conn.execute(__import__("sqlalchemy", fromlist=["text"]).text(
            "ALTER TABLE game_sessions ALTER COLUMN mode TYPE VARCHAR(20)"
        ))
    print("✅ Added is_sovereign column and expanded mode column to VARCHAR(20).")


if __name__ == "__main__":
    asyncio.run(migrate())
