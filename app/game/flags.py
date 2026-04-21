from functools import lru_cache
from pathlib import Path

from PIL import Image

FLAGS_DIR = Path(__file__).resolve().parent.parent / "assets" / "flags"


@lru_cache(maxsize=300)
def get_flag_image(iso2: str) -> Image.Image:
    return Image.open(FLAGS_DIR / f"{iso2.lower()}.png").convert("RGBA")
