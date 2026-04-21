# Flagle Bot — Claude Code Context

## What this project is

A Telegram Flagle bot. Players guess a mystery flag using an inline country picker. After each wrong guess, pixels of the hidden flag that overlap with the guessed flag are revealed. Runs in both DMs (6 guesses, no timer) and group chats (10 guesses, 45s+10s/guess timer with a background watchdog).

## Stack

- **python-telegram-bot v21** (async, webhook + polling modes)
- **FastAPI + uvicorn** (webhook receiver)
- **SQLAlchemy 2.0 async + asyncpg** against **Supabase PostgreSQL**
- **Pillow + NumPy** for pixel-overlap image processing
- **Flag PNGs** bundled locally in `app/assets/flags/` (no external storage)
- **Koyeb** for hosting (always-on, required for the timer watchdog)

## Key architecture decisions

- **No fuzzy text matching** — country selection is entirely via inline keyboard picker (alphabet → country list). There is no `MessageHandler` for text guesses.
- **Chat-scoped games** — `game_sessions.chat_id` is the scope key, not `user_id`. In DMs, `chat_id == user_id` so behaviour is identical to the old per-user flow.
- **Local flag bundle** — flags live in `app/assets/flags/{iso2}.png`, loaded via `app/game/flags.py` with `lru_cache`. No boto3/R2.
- **Timer watchdog** — `app/game/watchdog.py` runs as an `asyncio.Task` launched on FastAPI startup. It polls every 5s for expired group games and calls `bot.send_photo` to announce timeout. This requires an always-on host.
- **Multi-user stats** — when a game ends, all distinct guessers get `+1 game`. The winner gets `+1 win`; others get `+1 loss`. Logic lives in `crud.update_stats_for_game_end`.

## Project layout

```
app/
  main.py          — FastAPI app, startup/shutdown, watchdog task
  config.py        — Pydantic settings (no R2 vars)
  assets/flags/    — 250 PNG flags at 800×534 px
  bot/
    handlers.py    — all Telegram handlers (commands + callback query only)
    keyboards.py   — game_keyboard, alphabet_keyboard, letter_countries_keyboard, play_again_keyboard
    messages.py    — message templates (includes overlap_pct, timer display)
  game/
    engine.py      — start_daily_game, start_random_game, process_guess, give_up
    image.py       — build_revealed_image → (bytes, float), build_full_flag_image, build_black_image
    flags.py       — get_flag_image(iso2) with lru_cache
    watchdog.py    — timer_watchdog(app) async loop
    daily.py       — daily_country(today, countries) deterministic picker
  db/
    models.py      — Country, GameSession, Guess, UserStats
    crud.py        — all DB operations
    session.py     — AsyncSessionLocal, Base, engine
scripts/
  fetch_countries.py  — generates data/countries.json
  download_flags.py   — downloads flags → app/assets/flags/
  seed_db.py          — seeds countries table
tests/
  conftest.py         — SQLite in-memory async DB fixture
  test_image.py
  test_engine.py
  test_watchdog.py
  test_daily.py
```

## Data model (key fields)

```
game_sessions
  chat_id           BIGINT        — scope key (not user_id)
  creator_user_id   BIGINT        — nullable
  max_guesses       INTEGER       — 6 (DM) or 10 (group)
  timer_expires_at  TIMESTAMP     — null until first group guess
  end_reason        VARCHAR(20)   — 'won' | 'out_of_guesses' | 'timed_out' | 'abandoned'
  status            VARCHAR(10)   — 'active' | 'won' | 'lost'
  UNIQUE (chat_id, mode, created_date)

guesses
  guessed_by_user_id   BIGINT
  guessed_by_username  VARCHAR(100)
```

## Settings (app/config.py)

| Name | Default | Notes |
|---|---|---|
| `max_guesses_dm` | 6 | DM game limit |
| `max_guesses_group` | 10 | Group game limit |
| `timer_initial_seconds` | 45 | Timer set on first group guess |
| `timer_per_guess_seconds` | 10 | Added to timer on each subsequent guess |
| `flag_width` / `flag_height` | 800 / 534 | PNG dimensions |
| `white_threshold` | 240 | RGB channels ≥ this → treated as white |

## Callback data format

| Callback | Meaning |
|---|---|
| `open_picker:{game_id}` | Open the A–Z alphabet keyboard |
| `letter:{game_id}:{A}` | Show countries starting with letter A, page 0 |
| `letter_page:{game_id}:{A}:{n}` | Show page n of countries starting with A |
| `pick:{game_id}:{iso2}` | Submit a country guess |
| `cancel_pick:{game_id}` | Dismiss picker, restore game keyboard |
| `giveup:{game_id}` | Give up the current game |
| `play:daily` | Start today's daily |
| `play:random` | Start a random game |

## Running locally

```bash
cp .env.example .env   # fill in BOT_TOKEN and DATABASE_URL
pip install -r requirements.txt
python -m scripts.fetch_countries   # once
python -m scripts.seed_db           # once
python -m scripts.download_flags    # once — populates app/assets/flags/
BOT_MODE=polling python -m app.main
```

## Running tests

```bash
pip install -r requirements-dev.txt
pytest
```

Tests use SQLite in-memory via `aiosqlite`. Image functions are mocked in engine tests.

## Deployment checklist

1. Commit `app/assets/flags/` (or build it in CI before `docker build`)
2. Set env secrets: `BOT_TOKEN`, `DATABASE_URL`, `WEBHOOK_URL`, `BOT_MODE=webhook`
3. Deploy to Koyeb (Dockerfile auto-detected on push)
4. Bot sets webhook and starts watchdog on FastAPI startup automatically

## What NOT to do

- Do not add a `MessageHandler` for text — guessing is picker-only by design
- Do not reintroduce `boto3`, `rapidfuzz`, or R2 env vars
- Do not scope games by `user_id` — always use `chat_id`
- Do not use a scale-to-zero host (Cloud Run without Cloud Scheduler) — the watchdog needs to run continuously
