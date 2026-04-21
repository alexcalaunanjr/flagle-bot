"""Message text templates for the bot."""

from app.db.models import UserStats


WELCOME = (
    "🌍 *Welcome to Flagle Bot!*\n\n"
    "Guess the mystery flag.\n\n"
    "After each wrong guess, pixels of the hidden flag that overlap with your "
    "guessed flag will be revealed — building up a picture over time.\n\n"
    "Commands:\n"
    "  /daily — today's daily challenge\n"
    "  /play — random flag\n"
    "  /stats — your statistics\n\n"
    "Tap *🌍 Guess* to open the country picker!"
)


def game_started(mode: str, max_guesses: int, is_group: bool = False) -> str:
    label = "Daily challenge" if mode == "daily" else "Random game"
    msg = f"🚩 *{label} started!*\n\n_{max_guesses} guesses available._"
    if is_group:
        msg += "\n\n⏱ Timer starts on the first guess (45s base, +10s per guess, max 10 guesses)."
    return msg


def game_resumed(guesses_used: int, max_guesses: int, guessed_names: list[str], overlap_pct: float) -> str:
    guesses_left = max_guesses - guesses_used
    history = "\n".join(f"  ❌ {name}" for name in guessed_names)
    return (
        f"↩️ *Game resumed* — {guesses_left} guesses left.\n\n"
        f"Previous guesses:\n{history}\n\n"
        f"🧩 *{overlap_pct:.0f}%* of the flag revealed"
    )


def wrong_guess(
    guessed_name: str,
    guesses_used: int,
    max_guesses: int,
    overlap_pct: float,
    seconds_left: int | None = None,
) -> str:
    lines = [
        f"❌ *{guessed_name}* — wrong!",
        f"🧩 *{overlap_pct:.0f}%* of the flag revealed",
        f"🎯 *{guesses_used}/{max_guesses}* guesses",
    ]
    if seconds_left is not None:
        lines.append(f"⏱ *{seconds_left}s* remaining")
    return "\n".join(lines)


def correct_guess(country_name: str, guesses_used: int, guesser_name: str | None = None) -> str:
    who = f" by *{guesser_name}*" if guesser_name else ""
    return (
        f"🎉 *Correct{who}! It was {country_name}!*\n\n"
        f"Got it in *{guesses_used}* {'guess' if guesses_used == 1 else 'guesses'}."
    )


def game_lost(country_name: str) -> str:
    return f"😔 *Out of guesses!*\n\nThe answer was *{country_name}*."


def timed_out(country_name: str) -> str:
    return f"⏰ *Time's up!* The flag was *{country_name}*."


def gave_up(country_name: str) -> str:
    return f"🏳️ You gave up.\n\nThe flag was *{country_name}*."


def already_guessed(country_name: str) -> str:
    return f"You already guessed *{country_name}*."


def no_active_game() -> str:
    return "No active game. Use /daily or /play to start one!"


def daily_already_done(country_name: str, guesses_used: int, won: bool) -> str:
    outcome = f"won in {guesses_used} guesses 🎉" if won else "lost 😔"
    return (
        f"Today's daily ({country_name}) is already done — {outcome}.\n\n"
        "Use /play for a random game."
    )


def stats_message(s: UserStats) -> str:
    win_rate = (s.total_wins / s.total_games * 100) if s.total_games else 0
    avg_guesses = (s.sum_guesses_on_win / s.total_wins) if s.total_wins else 0
    return (
        f"📊 *Your Stats*\n\n"
        f"Games played: *{s.total_games}*\n"
        f"Wins: *{s.total_wins}* ({win_rate:.0f}%)\n"
        f"Current streak: *{s.current_streak}*\n"
        f"Best streak: *{s.max_streak}*\n"
        f"Avg guesses (wins): *{avg_guesses:.1f}*"
    )


def no_stats() -> str:
    return "You haven't played any games yet. Try /daily or /play!"
