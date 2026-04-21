"""Tests for the timer watchdog."""

import asyncio
import io
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.db import crud
from app.db.models import Country, GameSession
from app.game.watchdog import timer_watchdog


def _make_game(chat_id: int, target_country_id: int, expires_at: datetime) -> GameSession:
    g = GameSession()
    g.id = 1
    g.chat_id = chat_id
    g.creator_user_id = 1
    g.mode = "daily"
    g.target_country_id = target_country_id
    g.status = "active"
    g.guesses_used = 1
    g.max_guesses = 10
    g.timer_expires_at = expires_at
    return g


def _make_country(id_: int) -> Country:
    c = Country()
    c.id = id_
    c.iso2 = "xx"
    c.name = "Testland"
    c.common_name = "Testland"
    return c


@pytest.mark.asyncio
async def test_watchdog_ends_expired_game_and_notifies():
    """Watchdog ends timed-out game and sends photo to the chat."""
    past = datetime.utcnow() - timedelta(seconds=10)
    game = _make_game(chat_id=999, target_country_id=1, expires_at=past)
    country = _make_country(1)

    send_photo_mock = AsyncMock()
    bot_mock = MagicMock()
    bot_mock.send_photo = send_photo_mock

    app_mock = MagicMock()
    app_mock.bot = bot_mock

    with (
        patch("app.game.watchdog.AsyncSessionLocal") as mock_session_cls,
        patch("app.game.watchdog.crud.get_expired_active_games", new_callable=AsyncMock, return_value=[game]),
        patch("app.game.watchdog.crud.get_country_by_id", new_callable=AsyncMock, return_value=country),
        patch("app.game.watchdog.crud.end_game", new_callable=AsyncMock),
        patch("app.game.watchdog.build_full_flag_image", return_value=(b"flag", 100.0)),
    ):
        # Patch AsyncSessionLocal as async context manager
        mock_db = AsyncMock()
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        # Run one tick of the watchdog then cancel
        task = asyncio.create_task(timer_watchdog(app_mock))
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    send_photo_mock.assert_called_once()
    call_kwargs = send_photo_mock.call_args.kwargs
    assert call_kwargs["chat_id"] == 999
    assert isinstance(call_kwargs["photo"], io.BytesIO)


@pytest.mark.asyncio
async def test_watchdog_no_expired_games_sends_nothing():
    """Watchdog does nothing when there are no expired games."""
    send_photo_mock = AsyncMock()
    bot_mock = MagicMock()
    bot_mock.send_photo = send_photo_mock

    app_mock = MagicMock()
    app_mock.bot = bot_mock

    with (
        patch("app.game.watchdog.AsyncSessionLocal") as mock_session_cls,
        patch("app.game.watchdog.crud.get_expired_active_games", new_callable=AsyncMock, return_value=[]),
    ):
        mock_db = AsyncMock()
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        task = asyncio.create_task(timer_watchdog(app_mock))
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    send_photo_mock.assert_not_called()
