"""Tests for game engine: DM flow, group timer, multi-user stats."""

import pytest
from datetime import date, datetime, timedelta
from unittest.mock import patch, AsyncMock, MagicMock

from app.db import crud
from app.db.models import Country, GameSession, UserStats
from app.game import engine
from app.config import settings


def _make_country(id_: int, iso2: str, name: str) -> Country:
    c = Country()
    c.id = id_
    c.iso2 = iso2
    c.name = name
    c.common_name = name
    c.aliases = []
    return c


COUNTRIES = [_make_country(i, f"c{i}", f"Country{i}") for i in range(1, 11)]
TODAY = date(2025, 6, 1)
NOW = datetime(2025, 6, 1, 12, 0, 0)

BLACK_IMG = (b"black", 0.0)
FULL_IMG = (b"full", 100.0)
PARTIAL_IMG = (b"partial", 30.0)


@pytest.fixture
def mock_image():
    with (
        patch("app.game.engine.build_black_image", return_value=BLACK_IMG),
        patch("app.game.engine.build_full_flag_image", return_value=FULL_IMG),
        patch("app.game.engine.build_revealed_image", return_value=PARTIAL_IMG),
    ):
        yield


# ── DM game ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dm_game_6_guess_limit(db, mock_image):
    """DM game ends after max_guesses_dm (6) wrong guesses."""
    target = COUNTRIES[0]
    wrong = COUNTRIES[1]

    with patch("app.game.engine.daily_country", return_value=target):
        state = await engine.start_daily_game(db, chat_id=100, creator_user_id=1, is_group=False,
                                               countries=COUNTRIES, today=TODAY)

    assert state.game.max_guesses == settings.max_guesses_dm  # 6
    assert state.game.timer_expires_at is None

    for i in range(settings.max_guesses_dm):
        result = await engine.process_guess(db, state.game, wrong, 1, "user1", TODAY, NOW)
        if i < settings.max_guesses_dm - 1:
            assert not result.is_game_over
        else:
            assert result.is_game_over
            assert result.game_won is False
            assert state.game.end_reason == "out_of_guesses"


@pytest.mark.asyncio
async def test_dm_game_no_timer_set(db, mock_image):
    """DM game never sets timer_expires_at even after guesses."""
    target = COUNTRIES[0]
    wrong = COUNTRIES[1]

    with patch("app.game.engine.daily_country", return_value=target):
        state = await engine.start_daily_game(db, chat_id=200, creator_user_id=2, is_group=False,
                                               countries=COUNTRIES, today=TODAY)

    result = await engine.process_guess(db, state.game, wrong, 2, "user2", TODAY, NOW)
    assert state.game.timer_expires_at is None


@pytest.mark.asyncio
async def test_dm_game_win_records_stats(db, mock_image):
    """Correct guess in DM records a win for the guesser."""
    target = COUNTRIES[0]

    with patch("app.game.engine.daily_country", return_value=target):
        state = await engine.start_daily_game(db, chat_id=300, creator_user_id=3, is_group=False,
                                               countries=COUNTRIES, today=TODAY)

    result = await engine.process_guess(db, state.game, target, 3, "user3", TODAY, NOW)
    assert result.is_correct
    assert result.game_won

    stats = await crud.get_or_create_stats(db, 3, "user3")
    assert stats.total_wins == 1
    assert stats.total_games == 1


# ── Group game ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_group_game_10_guess_limit(db, mock_image):
    """Group game allows 10 guesses."""
    target = COUNTRIES[0]
    wrong = COUNTRIES[1]

    with patch("app.game.engine.daily_country", return_value=target):
        state = await engine.start_daily_game(db, chat_id=400, creator_user_id=4, is_group=True,
                                               countries=COUNTRIES, today=TODAY)

    assert state.game.max_guesses == settings.max_guesses_group  # 10


@pytest.mark.asyncio
async def test_group_timer_starts_on_first_guess(db, mock_image):
    """First wrong guess in a group game sets timer_expires_at = now + 45s."""
    target = COUNTRIES[0]
    wrong = COUNTRIES[1]

    with patch("app.game.engine.daily_country", return_value=target):
        state = await engine.start_daily_game(db, chat_id=500, creator_user_id=5, is_group=True,
                                               countries=COUNTRIES, today=TODAY)

    assert state.game.timer_expires_at is None
    result = await engine.process_guess(db, state.game, wrong, 5, "user5", TODAY, NOW)
    assert state.game.timer_expires_at is not None
    expected = NOW + timedelta(seconds=settings.timer_initial_seconds)
    assert abs((state.game.timer_expires_at - expected).total_seconds()) < 1


@pytest.mark.asyncio
async def test_group_timer_extends_on_second_guess(db, mock_image):
    """Second wrong guess adds +10s to timer."""
    target = COUNTRIES[0]
    wrong1 = COUNTRIES[1]
    wrong2 = COUNTRIES[2]

    with patch("app.game.engine.daily_country", return_value=target):
        state = await engine.start_daily_game(db, chat_id=600, creator_user_id=6, is_group=True,
                                               countries=COUNTRIES, today=TODAY)

    await engine.process_guess(db, state.game, wrong1, 6, "user6", TODAY, NOW)
    first_expiry = state.game.timer_expires_at

    await engine.process_guess(db, state.game, wrong2, 6, "user6", TODAY, NOW)
    second_expiry = state.game.timer_expires_at

    delta = (second_expiry - first_expiry).total_seconds()
    assert abs(delta - settings.timer_per_guess_seconds) < 1


@pytest.mark.asyncio
async def test_group_timer_expiry_ends_game(db, mock_image):
    """Guess after timer expiry returns timed_out result."""
    target = COUNTRIES[0]
    wrong = COUNTRIES[1]
    another = COUNTRIES[2]

    with patch("app.game.engine.daily_country", return_value=target):
        state = await engine.start_daily_game(db, chat_id=700, creator_user_id=7, is_group=True,
                                               countries=COUNTRIES, today=TODAY)

    # First guess sets timer
    await engine.process_guess(db, state.game, wrong, 7, "user7", TODAY, NOW)

    # Simulate clock past expiry
    past_expiry = state.game.timer_expires_at + timedelta(seconds=1)
    result = await engine.process_guess(db, state.game, another, 7, "user7", TODAY, past_expiry)
    assert result.timed_out
    assert result.is_game_over
    assert state.game.end_reason == "timed_out"


# ── Multi-user stats ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_multiuser_stats_winner_and_loser(db, mock_image):
    """User A wrong, User B correct → A gets loss, B gets win."""
    target = COUNTRIES[0]
    wrong = COUNTRIES[1]

    with patch("app.game.engine.daily_country", return_value=target):
        state = await engine.start_daily_game(db, chat_id=800, creator_user_id=10, is_group=True,
                                               countries=COUNTRIES, today=TODAY)

    # User A guesses wrong
    await engine.process_guess(db, state.game, wrong, 10, "userA", TODAY, NOW)
    # User B guesses correctly
    result = await engine.process_guess(db, state.game, target, 11, "userB", TODAY, NOW)

    assert result.is_correct

    stats_a = await crud.get_or_create_stats(db, 10, "userA")
    stats_b = await crud.get_or_create_stats(db, 11, "userB")

    assert stats_a.total_wins == 0
    assert stats_a.total_games == 1
    assert stats_b.total_wins == 1
    assert stats_b.total_games == 1
