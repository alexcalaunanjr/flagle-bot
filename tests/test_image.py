"""Tests for pixel-overlap revelation and overlap_pct calculation."""

import io
import numpy as np
import pytest
from PIL import Image
from unittest.mock import patch

from app.game.image import (
    _is_colored_mask,
    build_black_image,
    build_full_flag_image,
    build_revealed_image,
)


def _make_rgba_image(pixels: list[list[tuple[int, int, int, int]]]) -> Image.Image:
    h = len(pixels)
    w = len(pixels[0])
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    for r, row in enumerate(pixels):
        for c, px in enumerate(row):
            arr[r, c] = px
    return Image.fromarray(arr, "RGBA")


# 2×2 test flags: target is 2 red + 2 white; guess is 2 red + 2 white (same layout)
TARGET_PIXELS = [
    [(255, 0, 0, 255), (255, 255, 255, 255)],
    [(255, 0, 0, 255), (255, 255, 255, 255)],
]
GUESS_PIXELS = TARGET_PIXELS  # identical layout → 100% overlap


def test_is_colored_mask_marks_red_not_white():
    img = _make_rgba_image(TARGET_PIXELS)
    arr = np.array(img, dtype=np.uint8)
    mask = _is_colored_mask(arr)
    # Top-left and bottom-left are red → colored
    assert mask[0, 0] is np.bool_(True)
    assert mask[1, 0] is np.bool_(True)
    # Top-right and bottom-right are white → not colored
    assert mask[0, 1] is np.bool_(False)
    assert mask[1, 1] is np.bool_(False)


def test_build_black_image_returns_zeros():
    img_bytes, pct = build_black_image()
    assert pct == 0.0
    img = Image.open(io.BytesIO(img_bytes))
    arr = np.array(img)
    assert arr.sum() == 0


def test_build_full_flag_image_returns_100_pct():
    target_img = _make_rgba_image(TARGET_PIXELS)
    with patch("app.game.image.get_flag_image", return_value=target_img):
        img_bytes, pct = build_full_flag_image("xx")
    assert pct == 100.0
    assert len(img_bytes) > 0


def test_build_revealed_image_overlap_pct_identical_flags():
    target_img = _make_rgba_image(TARGET_PIXELS)
    guess_img = _make_rgba_image(GUESS_PIXELS)

    def mock_get(iso2):
        return target_img if iso2 == "tg" else guess_img

    with patch("app.game.image.get_flag_image", side_effect=mock_get):
        img_bytes, pct = build_revealed_image("tg", ["gg"])

    # Target colored pixels = 2 (the reds). Guess colored = same 2. Overlap = 2/2 = 100%.
    assert abs(pct - 100.0) < 0.1


def test_build_revealed_image_overlap_pct_no_overlap():
    # Target: 2 red pixels in left column; guess: 2 blue pixels in right column
    target_pixels = [
        [(255, 0, 0, 255), (255, 255, 255, 255)],
        [(255, 0, 0, 255), (255, 255, 255, 255)],
    ]
    guess_pixels = [
        [(255, 255, 255, 255), (0, 0, 255, 255)],
        [(255, 255, 255, 255), (0, 0, 255, 255)],
    ]
    target_img = _make_rgba_image(target_pixels)
    guess_img = _make_rgba_image(guess_pixels)

    def mock_get(iso2):
        return target_img if iso2 == "tg" else guess_img

    with patch("app.game.image.get_flag_image", side_effect=mock_get):
        _, pct = build_revealed_image("tg", ["gg"])

    assert abs(pct - 0.0) < 0.1


def test_build_revealed_image_partial_overlap():
    # Target: red in all 4 pixels; guess covers only top row (2 pixels)
    target_pixels = [
        [(255, 0, 0, 255), (255, 0, 0, 255)],
        [(255, 0, 0, 255), (255, 0, 0, 255)],
    ]
    guess_pixels = [
        [(255, 0, 0, 255), (255, 0, 0, 255)],
        [(255, 255, 255, 255), (255, 255, 255, 255)],
    ]
    target_img = _make_rgba_image(target_pixels)
    guess_img = _make_rgba_image(guess_pixels)

    def mock_get(iso2):
        return target_img if iso2 == "tg" else guess_img

    with patch("app.game.image.get_flag_image", side_effect=mock_get):
        _, pct = build_revealed_image("tg", ["gg"])

    # 2 out of 4 target colored pixels revealed → 50%
    assert abs(pct - 50.0) < 0.1
