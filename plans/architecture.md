# Flagle Telegram Bot — Architecture Plan

## Context
Build a Telegram bot that replicates the Flagle game (https://flagle-game.com/). Players get 6 tries to guess a country's flag. After each wrong guess, the pixels of the hidden target flag that overlap positionally with the guessed flag are progressively revealed. The bot offers daily (same flag for all users) and random modes. Stack must be minimal cost.

---

## Architecture Overview

```
Telegram ──webhook──► FastAPI app (Fly.io)
                          │
                 ┌────────┼────────┐
                 │        │        │
              Supabase  Cloudflare  Pillow
              Postgres    R2       (image
                       (flag PNGs) processing)
```

**No separate web frontend** — the bot is self-contained. FastAPI handles the Telegram webhook endpoint and houses all game logic.

---

## Stack

| Concern | Choice | Cost |
|---|---|---|
| Bot framework | python-telegram-bot v20+ (async) | free |
| Web framework | FastAPI + uvicorn | free |
| Database | Supabase PostgreSQL (free tier, 500MB) | $0 |
| ORM | SQLAlchemy async + asyncpg | free |
| Flag image storage | Cloudflare R2 (free: 10GB, 1M reads/mo) | $0 |
| Image processing | Pillow + NumPy | free |
| Country name fuzzy match | rapidfuzz | free |
| Hosting | Fly.io free tier (256MB RAM, 3 shared CPU) | $0 |

---

## Core Mechanic: Pixel Overlap Revelation

All flags normalized to **800×534 px** (standard 3:2 ratio), stored as PNGs in R2.

```
reveal(target_flag, guessed_flags[]):
  mask = union of (pixel != white) for each guessed_flag
  revealed_image = target_flag * mask + black * (1 - mask)
  return revealed_image
```

- "Not white" threshold: any pixel channel < 240 is considered colored
- Mask is **recomputed each turn** from the stored guess history — no mask stored in DB
- Flag images are **cached in memory** at startup/first-access (250 flags × ~100KB each ≈ 25MB) to avoid repeated R2 fetches

---

## Project Structure

```
flagle-bot/
├── app/
│   ├── main.py              # FastAPI app + Telegram Application setup, /webhook endpoint
│   ├── config.py            # Pydantic-settings: BOT_TOKEN, DATABASE_URL, R2_*, etc.
│   ├── bot/
│   │   ├── handlers.py      # /start, /daily, /play, /stats + text guess handler
│   │   ├── keyboards.py     # InlineKeyboard builders (give up button, etc.)
│   │   └── messages.py      # Message text templates
│   ├── game/
│   │   ├── engine.py        # Core: start_game(), process_guess(), get_game_state()
│   │   ├── image.py         # Pillow: build_revealed_image(target, guessed_list) → bytes
│   │   └── daily.py         # daily_country(date) → deterministic hash-based selection
│   ├── db/
│   │   ├── models.py        # SQLAlchemy ORM models
│   │   ├── crud.py          # DB read/write operations
│   │   └── session.py       # Async session factory (asyncpg)
│   └── storage/
│       └── r2.py            # boto3 S3-compatible R2 client, get_flag(iso2) → PIL.Image
├── scripts/
│   ├── fetch_countries.py   # Fetch ~250 countries from restcountries.com → data/countries.json
│   ├── download_flags.py    # Download from flagpedia.net → resize to 800×534 → upload to R2
│   └── seed_db.py           # Seed countries table from data/countries.json
├── data/
│   └── countries.json       # ~250 entries: iso2, name, common_name, aliases[], continent, lat, lon
├── plans/
│   └── architecture.md      # This file
├── Dockerfile
├── fly.toml                 # min_machines_running = 1 (always-on for webhook)
├── requirements.txt
└── .env.example
```

---

## Data Model (Supabase PostgreSQL)

```sql
countries (
  id          SERIAL PRIMARY KEY,
  iso2        VARCHAR(2) UNIQUE NOT NULL,
  name        VARCHAR(100) NOT NULL,
  common_name VARCHAR(100),
  aliases     TEXT[],           -- e.g. ["USA", "United States", "America"]
  continent   VARCHAR(50),
  capital     VARCHAR(100),
  lat         FLOAT,
  lon         FLOAT
)

game_sessions (
  id                SERIAL PRIMARY KEY,
  user_id           BIGINT NOT NULL,     -- Telegram user ID
  chat_id           BIGINT NOT NULL,
  mode              VARCHAR(10),         -- 'daily' | 'random'
  target_country_id INTEGER REFERENCES countries(id),
  status            VARCHAR(10) DEFAULT 'active', -- 'active' | 'won' | 'lost'
  guesses_used      INTEGER DEFAULT 0,
  created_at        TIMESTAMP DEFAULT NOW(),
  completed_at      TIMESTAMP,
  UNIQUE (user_id, mode, DATE(created_at))  -- one daily game per user per day
)

guesses (
  id           SERIAL PRIMARY KEY,
  game_id      INTEGER REFERENCES game_sessions(id),
  guess_number INTEGER NOT NULL,         -- 1–6
  country_id   INTEGER REFERENCES countries(id),
  is_correct   BOOLEAN NOT NULL,
  guessed_at   TIMESTAMP DEFAULT NOW()
)

user_stats (
  user_id        BIGINT PRIMARY KEY,     -- Telegram user ID
  username       VARCHAR(100),
  total_games    INTEGER DEFAULT 0,
  total_wins     INTEGER DEFAULT 0,
  current_streak INTEGER DEFAULT 0,
  max_streak     INTEGER DEFAULT 0,
  sum_guesses_on_win INTEGER DEFAULT 0,  -- for avg guesses calculation
  last_daily_date DATE
)
```

---

## Bot Conversation Flow

| Command / Input | Behavior |
|---|---|
| `/start` | Welcome message, explain rules |
| `/daily` | Start or resume today's daily game; send current revealed state |
| `/play` | Start a new random game |
| `/stats` | Show win rate, current streak, max streak, avg guesses |
| Text during active game | Fuzzy-match input → process as guess → send new revealed image |
| "Give Up" inline button | End game, reveal answer |

**Guess flow (per message):**
1. Fuzzy-match user text against `countries.name`, `common_name`, `aliases` using rapidfuzz (score ≥ 85)
2. If no match → reply "Country not found, try again"
3. If already guessed → reply "Already guessed"
4. Load all prior guesses + new guess from DB
5. Download target flag + all guessed flags (cached in memory)
6. Compute pixel-overlap revelation image via `image.py`
7. Send image to Telegram as photo with caption showing guess count
8. If correct → congratulate, update `user_stats`, mark game won
9. If 6th wrong guess → reveal full flag, update stats, mark game lost

---

## Daily Challenge Selection

No cron job needed — purely deterministic:

```python
# game/daily.py
def daily_country(date: date, countries: list[Country]) -> Country:
    seed = int(date.strftime("%Y%m%d"))
    idx = seed % len(countries)
    return countries[idx]
```

---

## One-Time Setup Scripts

**`scripts/fetch_countries.py`**
1. Fetch all countries from `https://restcountries.com/v3.1/all`
2. Extract iso2, name, common_name, aliases, continent, capital, lat, lon
3. Write to `data/countries.json` (sorted by name for stable daily selection)

**`scripts/download_flags.py`**
1. Read `data/countries.json` for iso2 codes
2. Download each flag PNG from `https://flagpedia.net/data/flags/w1600/{iso2}.webp`
3. Resize to 800×534 with Pillow, save as PNG
4. Upload to R2 at key `flags/{iso2}.png`

**`scripts/seed_db.py`**
1. Load `data/countries.json`
2. Upsert all rows into `countries` table

---

## Deployment

**Fly.io setup:**
```toml
# fly.toml
[http_service]
  internal_port = 8000
  min_machines_running = 1  # keep always-on for webhook

[env]
  PORT = "8000"
```

**Telegram webhook registration (automatic on startup):**
```
POST https://api.telegram.org/bot{TOKEN}/setWebhook
  url = https://{fly-app}.fly.dev/webhook
```

**Environment variables:**
```
BOT_TOKEN=
DATABASE_URL=postgresql+asyncpg://...  # Supabase connection string
R2_ENDPOINT_URL=https://{account}.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=flagle-flags
WEBHOOK_URL=https://{fly-app}.fly.dev/webhook
```

---

## Key Dependencies

```
fastapi
uvicorn[standard]
python-telegram-bot[webhooks]>=20.0
sqlalchemy[asyncio]
asyncpg
pillow
numpy
boto3
pydantic-settings
rapidfuzz
httpx
alembic
```

---

## Verification

1. **Unit test image logic**: Write a test that loads two known flags, runs `build_revealed_image()`, and asserts non-black pixels appear only where the guessed flag was colored
2. **Seed + query test**: Run `seed_db.py`, then query countries table to confirm ~250 rows
3. **Bot smoke test**: Run with `BOT_MODE=polling` locally (no webhook needed), play a full game to win and a full game to loss, verify stats update correctly with `/stats`
4. **Daily determinism**: Call `daily_country(date.today())` multiple times, confirm same result; call for 7 consecutive dates, confirm different countries
5. **Deploy to Fly.io**: Set webhook, send `/daily` from a real Telegram account, play through 6 guesses
