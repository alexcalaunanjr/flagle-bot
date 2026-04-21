# Flagle Bot

A Telegram bot that plays Flagle — guess the mystery flag using an inline country picker. After each wrong guess, pixels of the hidden flag that overlap with your guessed flag are revealed, progressively building up the image. Works in both DMs and group chats.

## Features

- `/daily` — shared daily challenge (same flag for the whole chat each day)
- `/play` — random flag, new game any time
- `/stats` — personal win rate, streak, and average guesses
- Inline country picker (A–Z alphabet → paginated country list, no typing required)
- Overlap % shown after each guess (`🧩 42% of the flag revealed`)
- **Group chat support** — anyone in the group can contribute a guess
- **Group timer** — 45s base, +10s per guess, up to 10 combined guesses
- Timer watchdog auto-announces when a group game times out

## Stack

| Concern          | Choice                           | Cost |
| ---------------- | -------------------------------- | ---- |
| Bot framework    | python-telegram-bot v21 (async)  | $0   |
| Web framework    | FastAPI + uvicorn                | $0   |
| Database         | Supabase PostgreSQL              | $0   |
| Flag images      | Local PNG bundle in Docker image | $0   |
| Image processing | Pillow + NumPy                   | $0   |
| Hosting          | Koyeb free tier (recommended)    | $0   |

## Project Structure

```
flagle-bot/
├── app/
│   ├── main.py              # Entry point (webhook + polling modes, timer watchdog)
│   ├── config.py            # Settings from environment variables
│   ├── assets/
│   │   └── flags/           # 250 pre-resized 800×534 PNG flags (run download_flags.py)
│   ├── bot/
│   │   ├── handlers.py      # Telegram command & callback handlers
│   │   ├── keyboards.py     # Inline keyboards (game, alphabet, country list, play again)
│   │   └── messages.py      # Message text templates
│   ├── game/
│   │   ├── engine.py        # Game logic (start, guess, give up, timer)
│   │   ├── image.py         # Pixel-overlap revelation + overlap_pct calculation
│   │   ├── flags.py         # Local PNG loader with lru_cache
│   │   ├── watchdog.py      # Async timer watchdog (polls every 5s)
│   │   └── daily.py         # Deterministic daily country selection
│   └── db/
│       ├── models.py        # SQLAlchemy ORM models
│       ├── crud.py          # Database operations
│       └── session.py       # Async DB session (asyncpg)
├── scripts/
│   ├── fetch_countries.py   # Generate data/countries.json from restcountries.com
│   ├── download_flags.py    # Download flag PNGs → resize → save to app/assets/flags/
│   └── seed_db.py           # Seed countries table from JSON
├── data/
│   └── countries.json       # Country metadata (~250 entries)
├── tests/
│   ├── conftest.py          # SQLite in-memory async DB fixture
│   ├── test_image.py        # Pixel reveal + overlap_pct assertions
│   ├── test_engine.py       # DM flow, group timer, multi-user stats
│   ├── test_watchdog.py     # Expired game ended + chat notified
│   └── test_daily.py        # Deterministic + 7-day variety
├── plans/
│   ├── architecture.md
│   └── flagle-plan-v1.1.md
├── Dockerfile
├── requirements.txt
├── requirements-dev.txt
├── pytest.ini
└── .env.example
```

## Setup

### Prerequisites

- Python 3.12+
- A Telegram bot token ([BotFather](https://t.me/BotFather))
- A [Supabase](https://supabase.com) project (free tier)

### 1. Configure environment

```bash
cp .env.example .env
# Fill in BOT_TOKEN and DATABASE_URL
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Fetch country data

Downloads ~250 countries from restcountries.com and writes `data/countries.json`:

```bash
python -m scripts.fetch_countries
```

### 4. Seed the database

Creates all tables and inserts country rows:

```bash
python -m scripts.seed_db
```

### 5. Download flag images

Downloads flags from flagpedia.net, resizes to 800×534 px, and saves to `app/assets/flags/`:

```bash
python -m scripts.download_flags
```

This populates ~250 PNGs that are bundled into the Docker image at build time. Run once; re-run only if you add countries.

### 6. Run locally (polling mode)

No public URL or webhook needed:

```bash
BOT_MODE=polling python -m app.main
```

### 7. Run tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Deployment (Koyeb — recommended)

1. Push your repo to GitHub (make sure `app/assets/flags/` is committed or built in CI).
2. Create a new Koyeb service → select your repo → Koyeb auto-detects the Dockerfile.
3. Set environment secrets:

```
BOT_TOKEN=...
DATABASE_URL=...
WEBHOOK_URL=https://your-app.koyeb.app/webhook
BOT_MODE=webhook
```

4. Deploy. The app sets the Telegram webhook automatically on startup and starts the timer watchdog.

> The timer watchdog requires an **always-on** host. Koyeb free tier is always-on. Cloud Run (scale-to-zero) is not suitable without extra scheduler setup.

### GCP e2-micro (alternative)

If you prefer maximum control and robustness, deploy to a GCP e2-micro Always Free VM (us-central1/us-west1/us-east1). SSH in, install Docker and Caddy for TLS, then run the container.

## Game Modes

### DM / private chat

| Setting     | Value    |
| ----------- | -------- |
| Max guesses | 6        |
| Timer       | None     |
| Scope       | Per user |

### Group chat

| Setting        | Value                                               |
| -------------- | --------------------------------------------------- |
| Max guesses    | 10 (combined, any member)                           |
| Timer          | 45s base, +10s each wrong guess                     |
| Scope          | Per chat (shared game)                              |
| End conditions | Correct guess, 10 wrong guesses, or timer reaches 0 |

When the timer expires the watchdog announces the answer automatically within ~5 seconds.

## How the pixel revelation works

All flags are stored at 800×534 px (3:2 ratio). When a guess is made:

1. A mask is computed from the guessed flag: a pixel is "colored" if any RGB channel is below the white threshold (240)
2. That mask is unioned with masks from all previous guesses
3. The combined mask is applied to the target flag — revealed pixels show the real color, hidden pixels stay black
4. `overlap_pct` = colored pixels in the intersection ÷ total colored pixels in the target × 100

Flags with lots of distinct color and shape reveal more of the target per guess.

## Environment Variables

| Variable       | Description                                     | Required                |
| -------------- | ----------------------------------------------- | ----------------------- |
| `BOT_TOKEN`    | Telegram bot token from BotFather               | Yes                     |
| `DATABASE_URL` | Supabase asyncpg connection string              | Yes                     |
| `WEBHOOK_URL`  | Public HTTPS URL for `/webhook`                 | Webhook mode            |
| `BOT_MODE`     | `webhook` (production) or `polling` (local dev) | No (default: `webhook`) |
