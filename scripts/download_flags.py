#!/usr/bin/env python3
"""Download flag images from flagpedia.net, normalize to 800×534, and save locally.

Run once before deploying:
    python -m scripts.download_flags

Flags are saved to app/assets/flags/{iso2}.png and bundled into the Docker image.
"""

import io
import json
import sys
import time
from pathlib import Path

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings

FLAGPEDIA_URL = "https://flagpedia.net/data/flags/w1600/{iso2}.webp"
DATA_FILE = Path(__file__).parent.parent / "data" / "countries.json"
FLAGS_DIR = Path(__file__).parent.parent / "app" / "assets" / "flags"

FLAG_WIDTH = settings.flag_width
FLAG_HEIGHT = settings.flag_height


def download_and_normalize(iso2: str, client: httpx.Client) -> bytes | None:
    url = FLAGPEDIA_URL.format(iso2=iso2.lower())
    try:
        response = client.get(url, timeout=15)
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        print(f"  HTTP {e.response.status_code} for {iso2}: {url}")
        return None
    except Exception as e:
        print(f"  Error downloading {iso2}: {e}")
        return None

    img = Image.open(io.BytesIO(response.content)).convert("RGBA")
    img = img.resize((FLAG_WIDTH, FLAG_HEIGHT), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def main():
    FLAGS_DIR.mkdir(parents=True, exist_ok=True)

    with open(DATA_FILE) as f:
        countries = json.load(f)

    print(f"Downloading {len(countries)} flags → saving to {FLAGS_DIR}")
    print(f"Target size: {FLAG_WIDTH}×{FLAG_HEIGHT} px\n")

    success, failed = 0, []

    with httpx.Client(follow_redirects=True) as client:
        for i, country in enumerate(countries, 1):
            iso2 = country["iso2"]
            name = country.get("common_name") or country["name"]
            dest = FLAGS_DIR / f"{iso2.lower()}.png"

            print(f"[{i:3d}/{len(countries)}] {iso2.upper()} {name}...", end=" ", flush=True)

            png_bytes = download_and_normalize(iso2, client)
            if png_bytes is None:
                failed.append(iso2)
                print("SKIPPED")
                continue

            dest.write_bytes(png_bytes)
            print(f"OK ({len(png_bytes) // 1024} KB)")
            success += 1

            time.sleep(0.1)

    print(f"\n✅ Done: {success} saved, {len(failed)} failed")
    if failed:
        print("Failed ISO2 codes:", ", ".join(failed))


if __name__ == "__main__":
    main()
