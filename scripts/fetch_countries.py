#!/usr/bin/env python3
"""Fetch country data from restcountries.com and write data/countries.json.

Run this once before seeding the database:
    python -m scripts.fetch_countries

This generates data/countries.json (~250 entries) with:
  iso2, name, common_name, aliases, continent, capital, lat, lon

Requires: httpx  (pip install httpx)
"""

import json
import sys
from pathlib import Path

import httpx

OUTPUT_FILE = Path(__file__).parent.parent / "data" / "countries.json"

# Known aliases / alternate names users commonly type
# Format: iso2 (lowercase) → list of extra aliases
EXTRA_ALIASES: dict[str, list[str]] = {
    "us": ["USA", "United States", "America", "United States of America"],
    "gb": ["UK", "Britain", "Great Britain", "England", "United Kingdom"],
    "ru": ["Russia"],
    "kr": ["South Korea"],
    "kp": ["North Korea"],
    "tw": ["Taiwan"],
    "vn": ["Vietnam"],
    "ir": ["Iran"],
    "sy": ["Syria"],
    "cd": ["Congo", "DRC", "Democratic Republic of Congo"],
    "cg": ["Republic of Congo"],
    "tz": ["Tanzania"],
    "bo": ["Bolivia"],
    "ve": ["Venezuela"],
    "la": ["Laos"],
    "mm": ["Burma", "Myanmar"],
    "mk": ["North Macedonia", "Macedonia"],
    "ci": ["Ivory Coast", "Cote d'Ivoire"],
    "cv": ["Cape Verde"],
    "sz": ["Eswatini", "Swaziland"],
    "bn": ["Brunei"],
    "tl": ["East Timor", "Timor-Leste"],
    "ps": ["Palestine"],
    "xk": ["Kosovo"],
    "ae": ["UAE", "United Arab Emirates"],
}

# Countries to exclude (disputed territories with no widely-recognized flag,
# or those not on flagpedia.net)
EXCLUDE_ISO2 = {"AQ", "BV", "TF", "HM", "UM"}


def continent_from_list(continents: list[str]) -> str | None:
    return continents[0] if continents else None


def build_entry(c: dict) -> dict | None:
    iso2 = c.get("cca2", "").lower()
    if not iso2 or iso2.upper() in EXCLUDE_ISO2:
        return None

    name_obj = c.get("name", {})
    official = name_obj.get("official", "")
    common = name_obj.get("common", "")

    latlng = c.get("latlng", [])
    lat = latlng[0] if len(latlng) > 0 else None
    lon = latlng[1] if len(latlng) > 1 else None

    capital_list = c.get("capital", [])
    capital = capital_list[0] if capital_list else None

    continent = continent_from_list(c.get("continents", []))

    aliases = list(EXTRA_ALIASES.get(iso2, []))
    # Add official name as alias if it differs from common name
    if official and official != common and official not in aliases:
        aliases.append(official)

    return {
        "iso2": iso2,
        "name": official or common,
        "common_name": common if common != (official or common) else None,
        "aliases": aliases,
        "continent": continent,
        "capital": capital,
        "lat": lat,
        "lon": lon,
    }


def main():
    print("Fetching country data from restcountries.com...")
    url = "https://restcountries.com/v3.1/all?fields=name,cca2,continents,capital,latlng"

    with httpx.Client(timeout=30) as client:
        response = client.get(url)
        response.raise_for_status()
        raw = response.json()

    print(f"Received {len(raw)} entries from API.")

    countries = []
    for c in raw:
        entry = build_entry(c)
        if entry:
            countries.append(entry)

    # Sort by name for consistent ordering (important for daily_country determinism)
    countries.sort(key=lambda x: x["name"])

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(countries, f, indent=2, ensure_ascii=False)

    print(f"✅ Wrote {len(countries)} countries to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
