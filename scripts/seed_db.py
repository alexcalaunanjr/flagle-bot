#!/usr/bin/env python3
"""Seed the countries table from data/countries.json.

Run once (or re-run safely — it upserts):
    python -m scripts.seed_db

Requires .env to be populated with DATABASE_URL.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.dialects.postgresql import insert

from app.db.models import Country
from app.db.session import AsyncSessionLocal, Base, engine

DATA_FILE = Path(__file__).parent.parent / "data" / "countries.json"


async def seed():
    with open(DATA_FILE) as f:
        countries = json.load(f)

    print(f"Seeding {len(countries)} countries into the database...")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        for c in countries:
            stmt = (
                insert(Country)
                .values(
                    iso2=c["iso2"].lower(),
                    name=c["name"],
                    common_name=c.get("common_name"),
                    aliases=c.get("aliases", []),
                    continent=c.get("continent"),
                    capital=c.get("capital"),
                    lat=c.get("lat"),
                    lon=c.get("lon"),
                    is_sovereign=c.get("is_sovereign", True),
                )
                .on_conflict_do_update(
                    index_elements=["iso2"],
                    set_={
                        "name": c["name"],
                        "common_name": c.get("common_name"),
                        "aliases": c.get("aliases", []),
                        "continent": c.get("continent"),
                        "capital": c.get("capital"),
                        "lat": c.get("lat"),
                        "lon": c.get("lon"),
                        "is_sovereign": c.get("is_sovereign", True),
                    },
                )
            )
            await db.execute(stmt)
        await db.commit()

    print(f"✅ Seeded {len(countries)} countries successfully.")


if __name__ == "__main__":
    asyncio.run(seed())
