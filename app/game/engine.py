"""Core game engine.

Handles starting games, processing guesses, and building game state.
Guessing is done via inline keyboard picker — no fuzzy text matching.
"""

import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import crud
from app.db.models import Country, GameSession, Guess
from app.game.daily import daily_country
from app.game.image import build_black_image, build_full_flag_image, build_revealed_image


@dataclass
class GuessResult:
    is_correct: bool
    is_game_over: bool
    game_won: bool
    timed_out: bool
    guesses_used: int
    max_guesses: int
    overlap_pct: float
    revealed_image: bytes  # PNG bytes
    guessed_country_name: str
    target_country_name: str  # only populated when game is over
    seconds_left: int | None  # only for group games in progress


@dataclass
class GameState:
    game: GameSession
    guesses: list[Guess]
    target_country: Country
    revealed_image: bytes  # PNG bytes of current revelation state
    overlap_pct: float


# ── Game lifecycle ─────────────────────────────────────────────────────────────

async def start_daily_game(
    db: AsyncSession,
    chat_id: int,
    creator_user_id: int,
    is_group: bool,
    countries: list[Country],
    today: date,
) -> GameState:
    """Start (or resume) today's daily game. Returns existing active game if present."""
    existing = await crud.get_active_game(db, chat_id, "daily", today)
    if existing:
        return await _build_game_state(db, existing)

    target = daily_country(today, countries)
    max_guesses = settings.max_guesses_group if is_group else settings.max_guesses_dm
    game = await crud.create_game(db, chat_id, creator_user_id, "daily", target.id, max_guesses, today)
    img_bytes, overlap_pct = build_black_image()
    return GameState(
        game=game,
        guesses=[],
        target_country=target,
        revealed_image=img_bytes,
        overlap_pct=overlap_pct,
    )


async def start_random_game(
    db: AsyncSession,
    chat_id: int,
    creator_user_id: int,
    is_group: bool,
    countries: list[Country],
    today: date,
    mode: str = "random:all",
) -> GameState:
    """Start a brand-new random game, abandoning any existing active random game.

    mode should be 'random:countries' (sovereign only) or 'random:all' (all 245).
    """
    existing = await crud.get_active_random_game(db, chat_id)
    if existing:
        await crud.abandon_game(db, existing)

    target = random.choice(countries)
    max_guesses = settings.max_guesses_group if is_group else settings.max_guesses_dm
    game = await crud.create_game(db, chat_id, creator_user_id, mode, target.id, max_guesses, today)
    img_bytes, overlap_pct = build_black_image()
    return GameState(
        game=game,
        guesses=[],
        target_country=target,
        revealed_image=img_bytes,
        overlap_pct=overlap_pct,
    )


async def process_guess(
    db: AsyncSession,
    game: GameSession,
    guessed_country: Country,
    guesser_user_id: int,
    guesser_username: str | None,
    today: date,
    now: datetime,
) -> GuessResult:
    """Process a guess, update DB, and return the result with the new revealed image."""
    target = await crud.get_country_by_id(db, game.target_country_id)

    # Guard: check if timer already expired
    if game.timer_expires_at and now >= game.timer_expires_at:
        img_bytes, _ = build_full_flag_image(target.iso2)
        await crud.end_game(db, game, "timed_out", winner_user_id=None)
        return GuessResult(
            is_correct=False,
            is_game_over=True,
            game_won=False,
            timed_out=True,
            guesses_used=game.guesses_used,
            max_guesses=game.max_guesses,
            overlap_pct=100.0,
            revealed_image=img_bytes,
            guessed_country_name=guessed_country.common_name or guessed_country.name,
            target_country_name=target.common_name or target.name,
            seconds_left=None,
        )

    is_correct = guessed_country.id == target.id
    await crud.add_guess(db, game, guessed_country.id, is_correct, guesser_user_id, guesser_username)
    guesses = await crud.get_guesses_for_game(db, game.id)
    guessed_iso2_list = [g.country.iso2 for g in guesses]

    if is_correct:
        img_bytes, overlap_pct = build_full_flag_image(target.iso2)
        await crud.end_game(db, game, "won", winner_user_id=guesser_user_id)
        return GuessResult(
            is_correct=True,
            is_game_over=True,
            game_won=True,
            timed_out=False,
            guesses_used=game.guesses_used,
            max_guesses=game.max_guesses,
            overlap_pct=overlap_pct,
            revealed_image=img_bytes,
            guessed_country_name=guessed_country.common_name or guessed_country.name,
            target_country_name=target.common_name or target.name,
            seconds_left=None,
        )

    if game.guesses_used >= game.max_guesses:
        img_bytes, overlap_pct = build_full_flag_image(target.iso2)
        await crud.end_game(db, game, "out_of_guesses", winner_user_id=None)
        return GuessResult(
            is_correct=False,
            is_game_over=True,
            game_won=False,
            timed_out=False,
            guesses_used=game.guesses_used,
            max_guesses=game.max_guesses,
            overlap_pct=overlap_pct,
            revealed_image=img_bytes,
            guessed_country_name=guessed_country.common_name or guessed_country.name,
            target_country_name=target.common_name or target.name,
            seconds_left=None,
        )

    # Still active — extend or set timer for group games
    seconds_left: int | None = None
    if game.timer_expires_at is None and game.max_guesses == settings.max_guesses_group:
        # First guess in a group game — start the timer
        game.timer_expires_at = now + timedelta(seconds=settings.timer_initial_seconds)
        await db.commit()
        await db.refresh(game)
        seconds_left = settings.timer_initial_seconds
    elif game.timer_expires_at is not None:
        game.timer_expires_at += timedelta(seconds=settings.timer_per_guess_seconds)
        await db.commit()
        await db.refresh(game)
        remaining = (game.timer_expires_at - now).total_seconds()
        seconds_left = max(0, int(remaining))

    img_bytes, overlap_pct = build_revealed_image(target.iso2, guessed_iso2_list)
    return GuessResult(
        is_correct=False,
        is_game_over=False,
        game_won=False,
        timed_out=False,
        guesses_used=game.guesses_used,
        max_guesses=game.max_guesses,
        overlap_pct=overlap_pct,
        revealed_image=img_bytes,
        guessed_country_name=guessed_country.common_name or guessed_country.name,
        target_country_name="",
        seconds_left=seconds_left,
    )


async def give_up(
    db: AsyncSession,
    game: GameSession,
    invoker_user_id: int,
    invoker_username: str | None,
    today: date,
) -> tuple[bytes, str]:
    """Abandon the current game. Returns (full_flag_bytes, target_country_name)."""
    target = await crud.get_country_by_id(db, game.target_country_id)
    # Add invoker as a guesser so they get a loss recorded
    if game.guesses_used == 0:
        await crud.add_guess(db, game, target.id, False, invoker_user_id, invoker_username)
    await crud.end_game(db, game, "abandoned", winner_user_id=None)
    img_bytes, _ = build_full_flag_image(target.iso2)
    return img_bytes, (target.common_name or target.name)


async def _build_game_state(db: AsyncSession, game: GameSession) -> GameState:
    """Reconstruct the current visual state of an in-progress game."""
    target = await crud.get_country_by_id(db, game.target_country_id)
    guesses = await crud.get_guesses_for_game(db, game.id)
    guessed_iso2_list = [g.country.iso2 for g in guesses]

    if guessed_iso2_list:
        img_bytes, overlap_pct = build_revealed_image(target.iso2, guessed_iso2_list)
    else:
        img_bytes, overlap_pct = build_black_image()

    return GameState(
        game=game,
        guesses=guesses,
        target_country=target,
        revealed_image=img_bytes,
        overlap_pct=overlap_pct,
    )
