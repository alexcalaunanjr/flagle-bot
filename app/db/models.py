from datetime import date, datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Country(Base):
    __tablename__ = "countries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    iso2: Mapped[str] = mapped_column(String(2), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    common_name: Mapped[str | None] = mapped_column(String(100))
    aliases: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    continent: Mapped[str | None] = mapped_column(String(50))
    capital: Mapped[str | None] = mapped_column(String(100))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    is_sovereign: Mapped[bool] = mapped_column(Boolean, default=True)

    game_sessions: Mapped[list["GameSession"]] = relationship(back_populates="target_country")
    guesses: Mapped[list["Guess"]] = relationship(back_populates="country")


class GameSession(Base):
    __tablename__ = "game_sessions"
    __table_args__ = (
        # Partial unique index: one daily game per chat per day; random games are unlimited.
        Index("uq_chat_daily", "chat_id", "created_date", unique=True,
              postgresql_where=text("mode = 'daily'")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    creator_user_id: Mapped[int | None] = mapped_column(BigInteger)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)  # 'daily' | 'random:countries' | 'random:all'
    target_country_id: Mapped[int] = mapped_column(ForeignKey("countries.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="active")  # 'active' | 'won' | 'lost'
    end_reason: Mapped[str | None] = mapped_column(String(20))  # 'won' | 'out_of_guesses' | 'timed_out' | 'abandoned'
    guesses_used: Mapped[int] = mapped_column(Integer, default=0)
    max_guesses: Mapped[int] = mapped_column(Integer, nullable=False)
    timer_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    created_date: Mapped[date] = mapped_column(Date, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    target_country: Mapped["Country"] = relationship(back_populates="game_sessions")
    guesses: Mapped[list["Guess"]] = relationship(back_populates="game", order_by="Guess.guess_number")


class Guess(Base):
    __tablename__ = "guesses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("game_sessions.id"), nullable=False, index=True)
    guess_number: Mapped[int] = mapped_column(Integer, nullable=False)
    country_id: Mapped[int] = mapped_column(ForeignKey("countries.id"), nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    guessed_by_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    guessed_by_username: Mapped[str | None] = mapped_column(String(100))
    guessed_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    game: Mapped["GameSession"] = relationship(back_populates="guesses")
    country: Mapped["Country"] = relationship(back_populates="guesses")


class UserStats(Base):
    __tablename__ = "user_stats"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(100))
    total_games: Mapped[int] = mapped_column(Integer, default=0)
    total_wins: Mapped[int] = mapped_column(Integer, default=0)
    current_streak: Mapped[int] = mapped_column(Integer, default=0)
    max_streak: Mapped[int] = mapped_column(Integer, default=0)
    sum_guesses_on_win: Mapped[int] = mapped_column(Integer, default=0)
    last_daily_date: Mapped[date | None] = mapped_column(Date)
