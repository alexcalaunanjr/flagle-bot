"""Pixel overlap revelation mechanic + comparison visualizations.

Reveal rule (used by the bot):
  A target pixel is revealed by a guess iff ALL of:
    1. local SSIM similarity >= SSIM_REVEAL_THRESHOLD
    2. the guessed pixel's RGB color is close to the target pixel's RGB color
       (sum of absolute per-channel differences <= COLOR_MATCH_THRESHOLD)
    3. the guessed pixel is itself "colored" (not white, not transparent)

  Rule (2) is what stops guesses like China from revealing most of Nigeria:
  SSIM alone measures local *structure*, so a flat red field and a flat green
  field look "structurally similar" even though they share no colors.
"""

import io

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity

from app.config import settings
from app.game.flags import get_flag_image

SSIM_REVEAL_THRESHOLD = 0.75
COLOR_MATCH_THRESHOLD = 120  # max L1 RGB distance (sum of |ΔR|+|ΔG|+|ΔB|)

VALID_VIS_MODES = (
    "similarity_map",
    "overlay",
    "similar_parts",
    "heatmap",
    "difference",
)


def _is_colored_mask(img_rgba: np.ndarray) -> np.ndarray:
    """Return a 2-D boolean mask where pixels are NOT white and NOT transparent."""
    t = settings.white_threshold
    r, g, b, a = img_rgba[:, :, 0], img_rgba[:, :, 1], img_rgba[:, :, 2], img_rgba[:, :, 3]
    is_white = (r >= t) & (g >= t) & (b >= t)
    is_transparent = a == 0
    return ~(is_white | is_transparent)


def _ssim_analysis(
    target_arr: np.ndarray, guessed_arr: np.ndarray
) -> tuple[float, np.ndarray, np.ndarray]:
    """Return (overall_score, raw_similarity_map [-1..1], normalized_map [0..1]).

    Uses grayscale SSIM. For images too small for the default 7×7 window
    (e.g. 2×2 unit-test fixtures) we fall back to an equality-based map so
    callers keep a well-defined 2-D similarity array.
    """
    gray_t = np.array(Image.fromarray(target_arr, "RGBA").convert("L"), dtype=np.uint8)
    gray_g = np.array(Image.fromarray(guessed_arr, "RGBA").convert("L"), dtype=np.uint8)

    h, w = gray_t.shape
    win = min(7, h, w)
    if win % 2 == 0:
        win -= 1

    if win < 3:
        ident = (gray_t == gray_g).astype(np.float64)
        sim_map = ident * 2.0 - 1.0
        return float(ident.mean() * 2.0 - 1.0), sim_map, ident

    score, sim_map = structural_similarity(
        gray_t, gray_g, full=True, data_range=255, win_size=win
    )
    sim_map_norm = np.clip((sim_map + 1.0) / 2.0, 0.0, 1.0)
    return float(score), sim_map, sim_map_norm


def _color_match_mask(
    target_arr: np.ndarray, guessed_arr: np.ndarray, tol: int = COLOR_MATCH_THRESHOLD
) -> np.ndarray:
    diff = np.abs(
        target_arr[:, :, :3].astype(np.int16) - guessed_arr[:, :, :3].astype(np.int16)
    )
    return diff.sum(axis=-1) <= tol


def _is_white_mask(img_rgba: np.ndarray) -> np.ndarray:
    """Return True for white (all RGB >= threshold) non-transparent pixels."""
    t = settings.white_threshold
    r, g, b, a = img_rgba[:, :, 0], img_rgba[:, :, 1], img_rgba[:, :, 2], img_rgba[:, :, 3]
    is_white = (r >= t) & (g >= t) & (b >= t)
    is_transparent = a == 0
    return is_white & ~is_transparent


def _reveal_mask(target_arr: np.ndarray, guessed_arr: np.ndarray) -> np.ndarray:
    _, sim_map, _ = _ssim_analysis(target_arr, guessed_arr)
    structural = sim_map >= SSIM_REVEAL_THRESHOLD
    color = _color_match_mask(target_arr, guessed_arr)
    guessed_colored = _is_colored_mask(guessed_arr)

    # Allow white pixels in guess to match white pixels in target
    target_white = _is_white_mask(target_arr)
    guessed_white = _is_white_mask(guessed_arr)
    both_white = target_white & guessed_white

    can_reveal = guessed_colored | both_white
    return structural & color & can_reveal


def _encode_png(arr_u8: np.ndarray, mode: str = "RGB") -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr_u8, mode).save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _load_init_image_array() -> np.ndarray:
    """Load init.png and return as RGBA numpy array, matching flag dimensions."""
    from pathlib import Path
    init_path = Path(__file__).parent.parent / "assets" / "init.png"
    try:
        img = Image.open(init_path)
        # Resize to match flag dimensions
        img = img.resize((settings.flag_width, settings.flag_height), Image.Resampling.LANCZOS)
        img = img.convert("RGBA")
        return np.array(img, dtype=np.uint8)
    except FileNotFoundError:
        # Fallback: transparent background
        return np.zeros((settings.flag_height, settings.flag_width, 4), dtype=np.uint8)


def build_revealed_image(target_iso2: str, guessed_iso2_list: list[str]) -> tuple[bytes, float]:
    """Build the progressively revealed flag image on top of init.png and return (PNG bytes, overlap_pct)."""
    target_arr = np.array(get_flag_image(target_iso2), dtype=np.uint8)

    target_colored_mask = _is_colored_mask(target_arr)
    target_colored_total = int(target_colored_mask.sum())

    H, W = target_arr.shape[:2]
    combined_mask = np.zeros((H, W), dtype=bool)

    for iso2 in guessed_iso2_list:
        guessed_arr = np.array(get_flag_image(iso2), dtype=np.uint8)
        combined_mask |= _reveal_mask(target_arr, guessed_arr)

    if target_colored_total > 0:
        revealed_colored = int((combined_mask & target_colored_mask).sum())
        overlap_pct = float(revealed_colored / target_colored_total * 100)
    else:
        overlap_pct = 0.0

    # Start with init.png as the base
    output = _load_init_image_array()
    # Overlay revealed target flag pixels
    output[combined_mask] = target_arr[combined_mask]
    output[:, :, 3] = 255

    img_out = Image.fromarray(output, "RGBA").convert("RGB")
    buf = io.BytesIO()
    img_out.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), overlap_pct


def build_full_flag_image(iso2: str) -> tuple[bytes, float]:
    img = get_flag_image(iso2).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), 100.0


def build_black_image() -> tuple[bytes, float]:
    img = Image.new("RGB", (settings.flag_width, settings.flag_height), color=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), 0.0


def build_init_image() -> tuple[bytes, float]:
    """Load the init.png asset and return as PNG bytes."""
    from pathlib import Path
    init_path = Path(__file__).parent.parent / "assets" / "init.png"
    try:
        img = Image.open(init_path).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), 0.0
    except FileNotFoundError:
        return build_black_image()


# ─────────────────────────────── Visualizations ───────────────────────────────


def visualize_comparison(
    target_iso2: str, guess_iso2: str, mode: str
) -> tuple[bytes, float, float]:
    """Return (png_bytes, overall_ssim_score, similarity_percentage).

    `mode` must be one of VALID_VIS_MODES.
    `similarity_percentage` is the mean of the normalized [0..1] similarity map ×100.
    """
    if mode not in VALID_VIS_MODES:
        raise ValueError(f"mode must be one of {VALID_VIS_MODES}, got {mode!r}")

    target_arr = np.array(get_flag_image(target_iso2), dtype=np.uint8)
    guess_arr = np.array(get_flag_image(guess_iso2), dtype=np.uint8)

    score, sim_map, sim_map_norm = _ssim_analysis(target_arr, guess_arr)
    similarity_pct = float(sim_map_norm.mean() * 100.0)

    target_rgb = target_arr[:, :, :3]
    similar = sim_map >= SSIM_REVEAL_THRESHOLD

    if mode == "similarity_map":
        gray = (sim_map_norm * 255).astype(np.uint8)
        arr = np.stack([gray, gray, gray], axis=-1)

    elif mode == "overlay":
        base = target_rgb.copy()
        green = np.zeros_like(base)
        green[..., 1] = 255
        alpha = 0.5
        blended = (base * (1 - alpha) + green * alpha).astype(np.uint8)
        arr = base.copy()
        arr[similar] = blended[similar]

    elif mode == "similar_parts":
        arr = np.zeros_like(target_rgb)
        arr[similar] = target_rgb[similar]

    elif mode == "heatmap":
        v = sim_map_norm
        r = (v * 255).astype(np.uint8)
        b = ((1.0 - v) * 255).astype(np.uint8)
        g = np.zeros_like(r)
        arr = np.stack([r, g, b], axis=-1)

    else:  # "difference"
        arr = target_rgb.copy()
        arr[~similar] = [255, 0, 0]
        arr[similar] = (arr[similar] * 0.3).astype(np.uint8)

    return _encode_png(arr, "RGB"), score, similarity_pct
