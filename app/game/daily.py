"""Daily challenge selection.

Uses a deterministic date-based hash so all users get the same flag each day
without needing a cron job or a separate database write.
"""

from datetime import date

from app.db.models import Country


def daily_country(today: date, countries: list[Country]) -> Country:
    """Return today's challenge country deterministically from the sorted country list."""
    if not countries:
        raise ValueError("Country list is empty — run the seed script first.")
    seed = int(today.strftime("%Y%m%d"))
    idx = seed % len(countries)
    return countries[idx]
