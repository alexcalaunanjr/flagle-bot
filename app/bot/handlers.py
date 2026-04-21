"""Telegram bot command and callback handlers."""

import io
import logging
from datetime import date, datetime

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from app.bot import keyboards, messages
from app.db.crud import (
    get_active_game,
    get_all_countries,
    get_country_by_iso2,
    get_daily_game_completed,
    get_guesses_for_game,
    get_or_create_stats,
    get_sovereign_countries,
)
from app.db.models import GameSession
from app.db.session import AsyncSessionLocal
from app.game import engine

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _today() -> date:
    return date.today()


def _now() -> datetime:
    return datetime.utcnow()


def _username(update: Update) -> str | None:
    user = update.effective_user
    return user.username or user.first_name if user else None


def _is_group(update: Update) -> bool:
    return update.effective_chat.type in ("group", "supergroup")


# ── /start ─────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(messages.WELCOME, parse_mode=ParseMode.MARKDOWN)


# ── /daily ─────────────────────────────────────────────────────────────────────

async def cmd_daily(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    today = _today()
    is_group = _is_group(update)

    async with AsyncSessionLocal() as db:
        completed = await get_daily_game_completed(db, chat_id, today)
        if completed:
            target = completed.target_country
            country_name = target.common_name or target.name
            await update.effective_message.reply_text(
                messages.daily_already_done(country_name, completed.guesses_used, completed.status == "won"),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        countries = await get_all_countries(db)
        state = await engine.start_daily_game(db, chat_id, user_id, is_group, countries, today)

    guessed_names = [g.country.common_name or g.country.name for g in state.guesses]
    if state.guesses:
        caption = messages.game_resumed(
            state.game.guesses_used, state.game.max_guesses, guessed_names, state.overlap_pct
        )
    else:
        caption = messages.game_started("daily", state.game.max_guesses, is_group)

    await update.effective_message.reply_photo(
        photo=io.BytesIO(state.revealed_image),
        caption=caption,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboards.game_keyboard(state.game.id),
    )


# ── /play ──────────────────────────────────────────────────────────────────────

async def cmd_play(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "🎲 Choose your flag set:",
        reply_markup=keyboards.play_mode_keyboard(),
    )


async def _start_random_game_with_mode(
    update: Update, mode: str
) -> None:
    """Helper to start a random game with the given mode (random:countries or random:all)."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    today = _today()
    is_group = _is_group(update)

    async with AsyncSessionLocal() as db:
        if mode == "random:countries":
            countries = await get_sovereign_countries(db)
        else:  # random:all
            countries = await get_all_countries(db)

        state = await engine.start_random_game(db, chat_id, user_id, is_group, countries, today, mode=mode)

    await update.effective_message.reply_photo(
        photo=io.BytesIO(state.revealed_image),
        caption=messages.game_started("random", state.game.max_guesses, is_group),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboards.game_keyboard(state.game.id),
    )


# ── /stats ─────────────────────────────────────────────────────────────────────

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    async with AsyncSessionLocal() as db:
        stats = await get_or_create_stats(db, user_id, _username(update))

    if stats.total_games == 0:
        await update.message.reply_text(messages.no_stats())
    else:
        await update.message.reply_text(messages.stats_message(stats), parse_mode=ParseMode.MARKDOWN)


# ── Callback query handler (inline keyboard buttons) ──────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    today = _today()
    now = _now()
    data = query.data

    # ── open_picker:{game_id} ──────────────────────────────────────────────────
    if data.startswith("open_picker:"):
        game_id = int(data.split(":")[1])
        async with AsyncSessionLocal() as db:
            game = await _get_active_game_by_id(db, game_id)
            if not game:
                await query.answer("This game is already over.", show_alert=True)
                return
        await query.edit_message_reply_markup(reply_markup=keyboards.alphabet_keyboard(game_id))

    # ── letter:{game_id}:{A} ───────────────────────────────────────────────────
    elif data.startswith("letter:"):
        _, game_id_str, letter = data.split(":", 2)
        game_id = int(game_id_str)
        async with AsyncSessionLocal() as db:
            game = await _get_active_game_by_id(db, game_id)
            if not game:
                await query.answer("This game is already over.", show_alert=True)
                return
            countries = await get_all_countries(db)
        await query.edit_message_reply_markup(
            reply_markup=keyboards.letter_countries_keyboard(game_id, letter, countries, page=0)
        )

    # ── letter_page:{game_id}:{A}:{n} ─────────────────────────────────────────
    elif data.startswith("letter_page:"):
        parts = data.split(":")
        game_id = int(parts[1])
        letter = parts[2]
        page = int(parts[3])
        async with AsyncSessionLocal() as db:
            game = await _get_active_game_by_id(db, game_id)
            if not game:
                await query.answer("This game is already over.", show_alert=True)
                return
            countries = await get_all_countries(db)
        await query.edit_message_reply_markup(
            reply_markup=keyboards.letter_countries_keyboard(game_id, letter, countries, page=page)
        )

    # ── pick:{game_id}:{iso2} ──────────────────────────────────────────────────
    elif data.startswith("pick:"):
        _, game_id_str, iso2 = data.split(":", 2)
        game_id = int(game_id_str)

        async with AsyncSessionLocal() as db:
            game = await _get_active_game_by_id(db, game_id)
            if not game:
                await query.answer("This game is already over.", show_alert=True)
                return

            guessed_country = await get_country_by_iso2(db, iso2)
            if not guessed_country:
                await query.answer("Unknown country.", show_alert=True)
                return

            # Check if already guessed in this game
            existing_guesses = await get_guesses_for_game(db, game_id)
            already_guessed_ids = {g.country_id for g in existing_guesses}
            if guessed_country.id in already_guessed_ids:
                await query.answer(
                    messages.already_guessed(guessed_country.common_name or guessed_country.name),
                    show_alert=True,
                )
                return

            result = await engine.process_guess(
                db, game, guessed_country, user_id, _username(update), today, now
            )

        guesser_name = _username(update)

        if result.timed_out:
            await query.message.reply_photo(
                photo=io.BytesIO(result.revealed_image),
                caption=messages.timed_out(result.target_country_name),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboards.play_again_keyboard(),
            )
            await query.edit_message_reply_markup(reply_markup=None)
        elif result.is_correct:
            caption = messages.correct_guess(result.target_country_name, result.guesses_used, guesser_name)
            await query.message.reply_photo(
                photo=io.BytesIO(result.revealed_image),
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboards.play_again_keyboard(),
            )
            await query.edit_message_reply_markup(reply_markup=None)
        elif result.is_game_over:
            caption = messages.game_lost(result.target_country_name)
            await query.message.reply_photo(
                photo=io.BytesIO(result.revealed_image),
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboards.play_again_keyboard(),
            )
            await query.edit_message_reply_markup(reply_markup=None)
        else:
            caption = messages.wrong_guess(
                result.guessed_country_name,
                result.guesses_used,
                result.max_guesses,
                result.overlap_pct,
                result.seconds_left,
            )
            await query.message.reply_photo(
                photo=io.BytesIO(result.revealed_image),
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboards.game_keyboard(game_id),
            )

    # ── cancel_pick:{game_id} ──────────────────────────────────────────────────
    elif data.startswith("cancel_pick:"):
        game_id = int(data.split(":")[1])
        await query.edit_message_reply_markup(reply_markup=keyboards.game_keyboard(game_id))

    # ── giveup:{game_id} ──────────────────────────────────────────────────────
    elif data.startswith("giveup:"):
        game_id = int(data.split(":")[1])
        async with AsyncSessionLocal() as db:
            game = await _get_active_game_by_id(db, game_id)
            if not game:
                await query.answer("This game is already over.", show_alert=True)
                return
            flag_bytes, country_name = await engine.give_up(
                db, game, user_id, _username(update), today
            )

        await query.message.reply_photo(
            photo=io.BytesIO(flag_bytes),
            caption=messages.gave_up(country_name),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboards.play_again_keyboard(),
        )
        await query.edit_message_reply_markup(reply_markup=None)

    # ── play:daily / play:random / play:random:* ──────────────────────────────
    elif data == "play:daily":
        await cmd_daily(update, context)
    elif data == "play:random":
        await query.edit_message_reply_markup(reply_markup=keyboards.play_mode_keyboard())
    elif data == "play:random:countries":
        await _start_random_game_with_mode(update, "random:countries")
    elif data == "play:random:all":
        await _start_random_game_with_mode(update, "random:all")


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _get_active_game_by_id(db, game_id: int) -> GameSession | None:
    from sqlalchemy import select
    result = await db.execute(
        select(GameSession).where(
            GameSession.id == game_id,
            GameSession.status == "active",
        )
    )
    return result.scalar_one_or_none()


# ── Handler registration ───────────────────────────────────────────────────────

def register_handlers(application) -> None:
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("daily", cmd_daily))
    application.add_handler(CommandHandler("play", cmd_play))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CallbackQueryHandler(handle_callback))
