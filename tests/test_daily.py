"""Tests for deterministic daily country selection."""

from datetime import date

import pytest

from app.game.daily import daily_country
from app.db.models import Country


def _make_countries(n: int) -> list[Country]:
    countries = []
    for i in range(n):
        c = Country()
        c.id = i + 1
        c.iso2 = f"x{i:01d}"
        c.name = f"Country {i}"
        countries.append(c)
    return countries


def test_daily_country_is_stable():
    """Same date always returns same country."""
    countries = _make_countries(50)
    today = date(2025, 1, 15)
    result1 = daily_country(today, countries)
    result2 = daily_country(today, countries)
    assert result1.id == result2.id


def test_daily_country_varies_across_7_days():
    """7 consecutive dates produce 7 distinct countries (for list size > 7)."""
    countries = _make_countries(100)
    base = date(2025, 3, 1)
    seen = set()
    for offset in range(7):
        d = date(base.year, base.month, base.day + offset)
        c = daily_country(d, countries)
        seen.add(c.id)
    assert len(seen) == 7, f"Expected 7 distinct countries, got {len(seen)}: {seen}"


def test_daily_country_different_dates_differ():
    """Dates with different seeds produce different results."""
    countries = _make_countries(50)
    d1 = date(2025, 1, 1)
    d2 = date(2025, 1, 2)
    # Not guaranteed to differ for every pair, but these specific dates should
    # (seed 20250101 % 50 vs 20250102 % 50 = 1 vs 2 — both distinct)
    c1 = daily_country(d1, countries)
    c2 = daily_country(d2, countries)
    assert c1.id != c2.id
