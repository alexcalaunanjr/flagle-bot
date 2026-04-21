from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Country, GameSession, Guess, UserStats


# ── Countries ──────────────────────────────────────────────────────────────────

async def get_all_countries(db: AsyncSession) -> list[Country]:
    result = await db.execute(select(Country).order_by(Country.id))
    return list(result.scalars().all())


async def get_sovereign_countries(db: AsyncSession) -> list[Country]:
    result = await db.execute(
        select(Country).where(Country.is_sovereign == True).order_by(Country.id)
    )
    return list(result.scalars().all())


async def get_country_by_id(db: AsyncSession, country_id: int) -> Country | None:
    return await db.get(Country, country_id)


async def get_country_by_iso2(db: AsyncSession, iso2: str) -> Country | None:
    result = await db.execute(select(Country).where(Country.iso2 == iso2.lower()))
    return result.scalar_one_or_none()


# ── Game sessions ──────────────────────────────────────────────────────────────

async def get_active_game(db: AsyncSession, chat_id: int, mode: str, today: date) -> GameSession | None:
    """Return the active game for this chat in the given mode (daily = today, random = any active)."""
    stmt = select(GameSession).where(
        GameSession.chat_id == chat_id,
        GameSession.mode == mode,
        GameSession.status == "active",
    )
    if mode == "daily":
        stmt = stmt.where(GameSession.created_date == today)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_active_random_game(db: AsyncSession, chat_id: int) -> GameSession | None:
    """Return any active random game for this chat (random:countries or random:all)."""
    from sqlalchemy import or_
    result = await db.execute(
        select(GameSession).where(
            GameSession.chat_id == chat_id,
            GameSession.mode.in_(["random:countries", "random:all"]),
            GameSession.status == "active",
        )
    )
    return result.scalar_one_or_none()


async def get_daily_game_completed(db: AsyncSession, chat_id: int, today: date) -> GameSession | None:
    """Return today's completed daily game for the chat, if any."""
    result = await db.execute(
        select(GameSession)
        .options(selectinload(GameSession.target_country))
        .where(
            GameSession.chat_id == chat_id,
            GameSession.mode == "daily",
            GameSession.created_date == today,
            GameSession.status.in_(["won", "lost"]),
        )
    )
    return result.scalar_one_or_none()


async def create_game(
    db: AsyncSession,
    chat_id: int,
    creator_user_id: int,
    mode: str,
    target_country_id: int,
    max_guesses: int,
    today: date,
) -> GameSession:
    game = GameSession(
        chat_id=chat_id,
        creator_user_id=creator_user_id,
        mode=mode,
        target_country_id=target_country_id,
        status="active",
        guesses_used=0,
        max_guesses=max_guesses,
        created_at=datetime.utcnow(),
        created_date=today,
    )
    db.add(game)
    await db.commit()
    await db.refresh(game)
    return game


async def add_guess(
    db: AsyncSession,
    game: GameSession,
    country_id: int,
    is_correct: bool,
    user_id: int,
    username: str | None,
) -> Guess:
    guess_number = game.guesses_used + 1
    guess = Guess(
        game_id=game.id,
        guess_number=guess_number,
        country_id=country_id,
        is_correct=is_correct,
        guessed_by_user_id=user_id,
        guessed_by_username=username,
        guessed_at=datetime.utcnow(),
    )
    db.add(guess)
    game.guesses_used = guess_number
    await db.commit()
    await db.refresh(guess)
    await db.refresh(game)
    return guess


async def end_game(
    db: AsyncSession,
    game: GameSession,
    end_reason: str,
    winner_user_id: int | None,
) -> None:
    """End a game with the given reason and update stats for all participants."""
    game.status = "won" if end_reason == "won" else "lost"
    game.end_reason = end_reason
    game.completed_at = datetime.utcnow()
    await db.commit()
    await db.refresh(game)
    await update_stats_for_game_end(db, game.id, winner_user_id)


async def update_stats_for_game_end(
    db: AsyncSession,
    game_id: int,
    winner_user_id: int | None,
) -> None:
    """Update stats: winner gets +1 win, all other guessers get +1 loss."""
    game = await db.get(GameSession, game_id)
    guesses = await get_guesses_for_game(db, game_id)

    # Collect all distinct guessers
    guesser_map: dict[int, str | None] = {}
    for g in guesses:
        guesser_map[g.guessed_by_user_id] = g.guessed_by_username

    today = game.created_date

    for user_id, username in guesser_map.items():
        won = user_id == winner_user_id
        stats = await get_or_create_stats(db, user_id, username)
        stats.total_games += 1
        if won:
            stats.total_wins += 1
            stats.sum_guesses_on_win += game.guesses_used
            stats.current_streak += 1
            if stats.current_streak > stats.max_streak:
                stats.max_streak = stats.current_streak
        else:
            stats.current_streak = 0
        stats.last_daily_date = today
    await db.commit()


async def get_guesses_for_game(db: AsyncSession, game_id: int) -> list[Guess]:
    result = await db.execute(
        select(Guess)
        .where(Guess.game_id == game_id)
        .order_by(Guess.guess_number)
        .options(__import__("sqlalchemy.orm", fromlist=["joinedload"]).joinedload(Guess.country))
    )
    return list(result.scalars().all())


async def abandon_game(db: AsyncSession, game: GameSession) -> None:
    await end_game(db, game, "abandoned", winner_user_id=None)


async def get_expired_active_games(db: AsyncSession, now: datetime) -> list[GameSession]:
    """Return all active games whose timer has expired."""
    result = await db.execute(
        select(GameSession).where(
            GameSession.status == "active",
            GameSession.timer_expires_at.isnot(None),
            GameSession.timer_expires_at <= now,
        )
    )
    return list(result.scalars().all())


# ── User stats ─────────────────────────────────────────────────────────────────

async def get_or_create_stats(db: AsyncSession, user_id: int, username: str | None) -> UserStats:
    stats = await db.get(UserStats, user_id)
    if not stats:
        stats = UserStats(user_id=user_id, username=username)
        db.add(stats)
        await db.commit()
        await db.refresh(stats)
    elif username and stats.username != username:
        stats.username = username
        await db.commit()
    return stats
