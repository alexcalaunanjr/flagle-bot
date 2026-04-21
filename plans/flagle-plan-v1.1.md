# Flagle Telegram Bot — Revised Plan

## Context

The codebase at `/Users/alexcalaunanjr/Desktop/PROJECTS/flagle-bot/` is ~85% built (FastAPI + python-telegram-bot + Supabase + Cloudflare R2 + Fly.io) per [plans/architecture.md](../../Desktop/PROJECTS/flagle-bot/plans/architecture.md). Re-planning against your stated requirements surfaced four divergences worth fixing before further work:

1. **Guess UX** — current code uses free-text + rapidfuzz; you want an inline-keyboard country picker.
2. **Overlap feedback** — current captions don't show the % of the target flag revealed; you want that.
3. **Group chats** — current schema scopes games per user; you want shared games (one per chat, anyone can contribute a guess).
4. **Flag storage** — current code uses Cloudflare R2 via boto3; 250 flags × ~100KB = ~25MB bundles trivially into the Docker image, removing an external dep, a secret, and cost.

Distance/direction/temperature hints are explicitly **not** wanted — pixel reveal + overlap % only. Two further decisions from this round of clarification:

5. **Hosting** — Fly.io no longer has a free tier (as of Oct 2024). Switching recommendation to **Koyeb free tier** (always-on, no sleep, no credit card) with **GCP e2-micro Always Free** as a robust fallback. See the comparison table below.
6. **Group-game timer** — shared group games run on a time-pressure variant: **first guess = 45 s** on the clock, **each subsequent guess adds +10 s**, **10 combined guesses max**. DMs keep the 6-guess, no-timer model. This requires a tiny background watchdog task — another reason the hosting choice must be always-on, not scale-to-zero.

Everything else (FastAPI webhook, Supabase Postgres, deterministic daily selection, pixel-mask mechanic) stays.

## Stack (after changes)

| Concern | Choice | Cost |
|---|---|---|
| Bot framework | python-telegram-bot v21 (async) | $0 |
| Web framework | FastAPI + uvicorn | $0 |
| Database | Supabase Postgres (free tier, 500MB) | $0 |
| ORM | SQLAlchemy 2.0 async + asyncpg | $0 |
| Flag storage | **Local PNG bundle in Docker image** | $0 |
| Image processing | Pillow + NumPy | $0 |
| Hosting | **Koyeb free tier** (primary) — see below | $0 |

**Removed:** `boto3`, `rapidfuzz`, all R2 secrets, Fly.io.

### Hosting: why not Fly.io

Fly.io removed its free tier in Oct 2024. New accounts now get a 2-VM-hour / 7-day trial, then pay ~$5/month minimum for a small always-on app (plus $2/month for an IPv4 if needed). Only pre-Oct-2024 accounts retain a hobby allowance.

### Hosting comparison (for this bot's needs: always-on HTTPS + ~256MB RAM + a background timer loop)

| Option | Free-tier fit | Setup | Notes |
|---|---|---|---|
| **Koyeb** (Recommended) | ✅ Always-on, no sleep, no CC required | Git/Docker push → auto HTTPS | 1 service + 512MB on free tier; closest DX to Fly.io; fits the always-on timer watchdog we need. |
| **GCP e2-micro** (Always Free) | ✅ 1 VM × 720 hrs/month forever, us-central/west/east-1 only | SSH in, install Docker + Caddy for TLS | 1 GB RAM is tight but sufficient. Most robust long-term (can also host SQLite on the disk), but more setup. |
| **Cloud Run** | ✅ 1 GiB egress + 180K vCPU-seconds/month | `gcloud run deploy` | Scales to zero → cold starts on webhook (1–2s) **and** cannot host the timer watchdog. Needs Cloud Scheduler to poll a `/tick` endpoint every 5s (free tier covers 3 schedulers). Extra complexity; avoid unless hard $0 ceiling is critical. |
| **Oracle Cloud Always Free** | ✅ 4 ARM cores + 24GB RAM | VM setup | Most generous tier, but account approval is notoriously flaky and instances can be reclaimed. |
| **Fly.io** | ❌ No more free tier for new accounts | — | ~$5/month minimum. |

**Recommended: Koyeb** — smoothest path from the existing Dockerfile to a running bot with no hosting cost. If you want ultimate robustness, **GCP e2-micro** is the fallback (and lets you drop Supabase for SQLite too, shrinking the stack further). Supabase stays as the Postgres backend regardless.

---

## Change 1 — Country picker (replaces fuzzy text)

Reuses the existing callback-query pipeline in [app/bot/handlers.py:186](../../Desktop/PROJECTS/flagle-bot/app/bot/handlers.py#L186).

**[app/bot/keyboards.py](../../Desktop/PROJECTS/flagle-bot/app/bot/keyboards.py)** — add:
- `game_keyboard(game_id)` — `[🌍 Guess]  [🏳️ Give Up]` attached to every in-game message.
- `alphabet_keyboard(game_id)` — 26 letter buttons (7 per row) + `✖ Cancel`. Callback: `letter:{game_id}:{A}`.
- `letter_countries_keyboard(game_id, letter, page)` — 2-col country list (≤16/page) with `← A-Z` and page arrows. Callback per country: `pick:{game_id}:{iso2}`.
- Keep `play_again_keyboard()`.

**[app/bot/handlers.py](../../Desktop/PROJECTS/flagle-bot/app/bot/handlers.py) callback routes:**
- `open_picker:{game_id}` → swap reply markup to alphabet.
- `letter:{game_id}:{A}` / `letter_page:{game_id}:{A}:{n}` → swap reply markup to letter page.
- `pick:{game_id}:{iso2}` → call `engine.process_guess`, reply with new game photo.
- `cancel_pick:{game_id}` → restore `game_keyboard`.
- `giveup:{game_id}` → unchanged.

**Delete:**
- `handle_guess` text handler ([handlers.py:122-181](../../Desktop/PROJECTS/flagle-bot/app/bot/handlers.py#L122-L181)).
- `MessageHandler(filters.TEXT ...)` registration ([handlers.py:241](../../Desktop/PROJECTS/flagle-bot/app/bot/handlers.py#L241)).
- `find_country`, `_build_name_map` in [app/game/engine.py:41-71](../../Desktop/PROJECTS/flagle-bot/app/game/engine.py#L41-L71).
- `rapidfuzz` from `requirements.txt`; `fuzzy_match_score` from [app/config.py](../../Desktop/PROJECTS/flagle-bot/app/config.py).

---

## Change 2 — Overlap % in captions

**[app/game/image.py](../../Desktop/PROJECTS/flagle-bot/app/game/image.py):**
- `build_revealed_image()` → return `tuple[bytes, float]`. Compute `overlap_pct = (combined_mask & target_colored_mask).sum() / target_colored_mask.sum() * 100` where `target_colored_mask = _is_colored_mask(target_arr)`. This gives "% of the flag's actual inked area revealed", not "% of the canvas" — correct for flags with white fields.
- `build_black_image()` → return `(bytes, 0.0)` for type consistency.
- `build_full_flag_image()` → return `(bytes, 100.0)`.

**[app/game/engine.py](../../Desktop/PROJECTS/flagle-bot/app/game/engine.py):**
- `GuessResult` and `GameState` gain `overlap_pct: float`.
- All four builder call sites updated.

**[app/bot/messages.py](../../Desktop/PROJECTS/flagle-bot/app/bot/messages.py):**
- `wrong_guess(guessed_name, guesses_used, overlap_pct)` appends `\n🧩 *{pct:.0f}%* of the flag revealed.`
- `game_resumed(guesses_used, guessed_names, overlap_pct)` same suffix.

---

## Change 3 — Shared group games (with timer)

One game per chat per mode per day. Guesses track who made them. Stats remain per-user. **Groups** run under a time-pressure variant:

- **Max guesses**: 10 combined (vs 6 in DMs).
- **Timer**: Starts at the first guess — 45 seconds. Each subsequent guess adds +10 seconds to the remaining time.
- **End conditions**: correct guess → won; 10 wrong guesses → lost (out-of-guesses); timer reaches 0 → lost (timed-out).
- **DMs**: no timer, 6 guesses (unchanged).

### Schema

**[app/db/models.py](../../Desktop/PROJECTS/flagle-bot/app/db/models.py):**
```python
class GameSession(Base):
    chat_id: BIGINT NOT NULL
    creator_user_id: BIGINT                 # nullable
    max_guesses: INTEGER NOT NULL           # 6 for DM, 10 for group
    timer_expires_at: TIMESTAMP             # nullable; null in DMs, null pre-first-guess in groups
    end_reason: VARCHAR(20)                 # nullable: 'won' | 'out_of_guesses' | 'timed_out' | 'abandoned'
    __table_args__ = (UniqueConstraint("chat_id", "mode", func.date("created_at")),)

class Guess(Base):
    guessed_by_user_id: BIGINT NOT NULL     # new
    guessed_by_username: VARCHAR(100)       # new (denormalized for display)
```

`UserStats` unchanged — still keyed by `user_id`.

### CRUD ([app/db/crud.py](../../Desktop/PROJECTS/flagle-bot/app/db/crud.py))

- `get_active_game(db, chat_id, mode, date)` — chat-scoped.
- `get_daily_game_completed(db, chat_id, date)` — chat-scoped.
- `create_game(db, chat_id, creator_user_id, mode, target_country_id, max_guesses, today)`.
- `add_guess(db, game, country_id, is_correct, user_id, username)`.
- `end_game(db, game, end_reason, winner_user_id | None)` — sets `status`, `end_reason`, `completed_at`; calls stats update.
- `update_stats_for_game_end(db, game_id, winner_user_id | None)` — winner gets `+1 win`; all distinct guessers (non-winners) get `+1 loss`; streak math unchanged per user.
- `get_expired_active_games(db, now)` — used by the timer watchdog.

### Engine ([app/game/engine.py](../../Desktop/PROJECTS/flagle-bot/app/game/engine.py))

```python
# app/config.py adds:
#   max_guesses_dm = 6
#   max_guesses_group = 10
#   timer_initial_seconds = 45
#   timer_per_guess_seconds = 10

async def start_daily_game(db, chat_id, creator_user_id, is_group, countries, today):
    max_guesses = settings.max_guesses_group if is_group else settings.max_guesses_dm
    # ... look up by chat_id; if new, create with max_guesses and NO timer yet

async def process_guess(db, game, guessed_country, guesser_user_id, guesser_username, today, now):
    # 1. Guard: if game.timer_expires_at and now >= game.timer_expires_at -> end_game(timed_out); return TimedOutResult
    # 2. Record guess
    # 3. Is correct? -> end_game(won, winner=guesser)
    # 4. Else if game.guesses_used >= game.max_guesses -> end_game(out_of_guesses)
    # 5. Else (still active, group only): extend timer
    #      if game.timer_expires_at is None:
    #          game.timer_expires_at = now + timedelta(seconds=settings.timer_initial_seconds)
    #      else:
    #          game.timer_expires_at += timedelta(seconds=settings.timer_per_guess_seconds)
```

`give_up(db, game, invoker_user_id, invoker_username, today)` → `end_game(reason='abandoned')`; all distinct guessers get `+1 loss`.

### Handlers ([app/bot/handlers.py](../../Desktop/PROJECTS/flagle-bot/app/bot/handlers.py))

- `_is_group(update) -> bool` using `update.effective_chat.type in ("group", "supergroup")`.
- `cmd_daily` / `cmd_play` pass `is_group` through to `engine.start_*_game`; "already done today" is chat-scoped.
- Picker callback (`pick:{game_id}:{iso2}`) uses `update.effective_user.id` as guesser and passes `now=datetime.utcnow()` through.
- In DMs `chat_id == user_id` — behaviour identical to the old single-player flow.

### Background timer watchdog

For time-pressure to feel real, the bot must **auto-announce** when a group's timer runs out (rather than waiting for someone else to poke the bot).

**New `app/game/watchdog.py`:**
```python
async def timer_watchdog(app):
    while True:
        try:
            async with AsyncSessionLocal() as db:
                expired = await crud.get_expired_active_games(db, datetime.utcnow())
                for game in expired:
                    target = await crud.get_country_by_id(db, game.target_country_id)
                    await crud.end_game(db, game, end_reason="timed_out", winner_user_id=None)
                    await app.bot.send_photo(
                        chat_id=game.chat_id,
                        photo=io.BytesIO(build_full_flag_image(target.iso2)),
                        caption=messages.timed_out(target.common_name or target.name),
                        parse_mode=ParseMode.MARKDOWN,
                    )
        except Exception:
            logger.exception("timer_watchdog tick failed")
        await asyncio.sleep(5)
```

Launched from FastAPI's `startup` event in [app/main.py](../../Desktop/PROJECTS/flagle-bot/app/main.py) via `asyncio.create_task(timer_watchdog(application))`. The 5-second poll is cheap, survives transient DB errors, and matches the precision users expect from a "45s" timer.

> ⚠️ This requires an **always-on host** (Koyeb or GCP e2-micro). Cloud Run would need Cloud Scheduler + a `/tick` endpoint instead — another reason the hosting recommendation is Koyeb.

### Captions (timer display)

**[app/bot/messages.py](../../Desktop/PROJECTS/flagle-bot/app/bot/messages.py):**
- `wrong_guess(guessed_name, guesses_used, max_guesses, overlap_pct, seconds_left | None)`:
  ```
  ❌ *{guessed_name}* — wrong!
  🧩 *{pct:.0f}%* of the flag revealed
  🎯 *{guesses_used}/{max_guesses}* guesses
  ⏱ *{seconds_left}s* remaining   ← only when seconds_left is not None
  ```
- `timed_out(country_name)` → `"⏰ *Time's up!* The flag was *{country_name}*."`
- `game_started` in a group → appends "⏱ Timer starts on the first guess (45s base, +10s per guess, max 10 guesses)."

---

## Change 4 — Bundle flags, remove R2

**Delete:**
- [app/storage/r2.py](../../Desktop/PROJECTS/flagle-bot/app/storage/r2.py) and the `app/storage/` folder.
- `R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME` from [app/config.py](../../Desktop/PROJECTS/flagle-bot/app/config.py), `.env.example`, `fly.toml`.
- `boto3` from `requirements.txt`.

**Add** `app/game/flags.py`:
```python
from functools import lru_cache
from pathlib import Path
from PIL import Image

FLAGS_DIR = Path(__file__).resolve().parent.parent / "assets" / "flags"

@lru_cache(maxsize=300)
def get_flag_image(iso2: str) -> Image.Image:
    return Image.open(FLAGS_DIR / f"{iso2.lower()}.png").convert("RGBA")
```

Update [app/game/image.py:19](../../Desktop/PROJECTS/flagle-bot/app/game/image.py#L19) import: `from app.game.flags import get_flag_image`.

**Add** `app/assets/flags/` — 250 pre-resized 800×534 PNGs, checked into the repo. Size impact: ~25MB.

**Modify** [scripts/download_flags.py](../../Desktop/PROJECTS/flagle-bot/scripts/download_flags.py) — keep the fetch + resize, swap the R2 upload for `img.save(FLAGS_DIR / f"{iso2}.png")`. Run once to populate.

**Dockerfile** — already does `COPY . .`, so no change beyond verifying the assets land in the image.

---

## Change 5 — Missing pieces in current code

From the Explore report:
- `get_or_create_stats` is imported in handlers but the function body wasn't seen — verify it exists in [app/db/crud.py](../../Desktop/PROJECTS/flagle-bot/app/db/crud.py); add if missing.
- No migrations — Alembic is in `requirements.txt` but unused. Since the schema is changing meaningfully (chat_id scope, new guess columns), either generate one baseline + one delta migration, **or** drop and recreate tables in dev (only safe because it's not git-tracked yet and likely no real data).

---

## Data Model (final)

```sql
countries                                   -- unchanged
game_sessions (
  id                SERIAL PRIMARY KEY,
  chat_id           BIGINT NOT NULL,        -- changed: was user_id
  creator_user_id   BIGINT,                 -- new
  mode              VARCHAR(10),
  target_country_id INTEGER REFERENCES countries(id),
  status            VARCHAR(10) DEFAULT 'active',
  end_reason        VARCHAR(20),            -- new: 'won' | 'out_of_guesses' | 'timed_out' | 'abandoned'
  guesses_used      INTEGER DEFAULT 0,
  max_guesses       INTEGER NOT NULL,       -- new: 6 (DM) or 10 (group)
  timer_expires_at  TIMESTAMP,              -- new: nullable; set on first group guess, extended on each subsequent
  created_at        TIMESTAMP DEFAULT NOW(),
  completed_at      TIMESTAMP,
  UNIQUE (chat_id, mode, DATE(created_at))  -- changed
)
guesses (
  id                  SERIAL PRIMARY KEY,
  game_id             INTEGER REFERENCES game_sessions(id),
  guess_number        INTEGER NOT NULL,
  country_id          INTEGER REFERENCES countries(id),
  is_correct          BOOLEAN NOT NULL,
  guessed_by_user_id  BIGINT NOT NULL,      -- new
  guessed_by_username VARCHAR(100),         -- new
  guessed_at          TIMESTAMP DEFAULT NOW()
)
user_stats                                  -- unchanged
```

---

## Critical Files to Modify

| File | Action |
|---|---|
| [app/bot/keyboards.py](../../Desktop/PROJECTS/flagle-bot/app/bot/keyboards.py) | Replace with picker keyboards |
| [app/bot/handlers.py](../../Desktop/PROJECTS/flagle-bot/app/bot/handlers.py) | Replace text-guess flow with picker callbacks; chat-scoped lookups |
| [app/bot/messages.py](../../Desktop/PROJECTS/flagle-bot/app/bot/messages.py) | Add overlap_pct to captions; chat-scoped "already done" |
| [app/game/engine.py](../../Desktop/PROJECTS/flagle-bot/app/game/engine.py) | Chat-scoped lookup; drop `find_country`; guesser tracking; overlap_pct; timer check + extend |
| [app/game/image.py](../../Desktop/PROJECTS/flagle-bot/app/game/image.py) | Return `(bytes, overlap_pct)`; target-colored-mask denominator |
| `app/game/flags.py` | **NEW** — local PNG loader with `lru_cache` |
| `app/game/watchdog.py` | **NEW** — async timer watchdog task (polls every 5s, auto-notifies expired chats) |
| [app/main.py](../../Desktop/PROJECTS/flagle-bot/app/main.py) | Launch `timer_watchdog` on FastAPI startup event |
| [app/db/models.py](../../Desktop/PROJECTS/flagle-bot/app/db/models.py) | Rescope game_sessions; add guesser, timer, max_guesses, end_reason columns |
| [app/db/crud.py](../../Desktop/PROJECTS/flagle-bot/app/db/crud.py) | Chat-scoped queries; multi-user stats updater; `end_game`; `get_expired_active_games`; ensure `get_or_create_stats` exists |
| [app/config.py](../../Desktop/PROJECTS/flagle-bot/app/config.py) | Drop R2 + `fuzzy_match_score`; add `max_guesses_dm`, `max_guesses_group`, `timer_initial_seconds`, `timer_per_guess_seconds` |
| [scripts/download_flags.py](../../Desktop/PROJECTS/flagle-bot/scripts/download_flags.py) | Save locally, not to R2 |
| `requirements.txt` | Drop `boto3`, `rapidfuzz` |
| `.env.example`, `fly.toml` | Drop R2 vars |
| `app/storage/r2.py` | **DELETE** (with the folder) |
| `app/assets/flags/` | **NEW** — 250 PNGs (generated by the updated script, committed) |
| `tests/test_image.py` | **NEW** — reveal + overlap_pct assertions |
| `tests/test_engine.py` | **NEW** — DM + shared-group timer + multi-user stats |
| `tests/test_watchdog.py` | **NEW** — expired game is ended and chat is notified |
| `tests/test_daily.py` | **NEW** — deterministic + 7-day variety |

---

## Verification

1. `pytest tests/test_image.py` — two known flags, assert revealed pixels are exactly in the overlap region; assert `overlap_pct` matches a hand-computed value.
2. `pytest tests/test_engine.py` — SQLite in-memory; cover:
   - DM daily: 6-guess limit, no timer column set, wins/losses tracked for one user.
   - Group daily: first guess sets `timer_expires_at = now + 45s`; second wrong guess pushes it to `+55s`; 10th wrong guess triggers `end_reason='out_of_guesses'`.
   - Group timer expiry: mock clock past `timer_expires_at` → next guess returns "timed out" result with `end_reason='timed_out'`.
   - Multi-user stats: user A wrong, user B correct → A gets `+1 loss`, B gets `+1 win`.
3. `pytest tests/test_watchdog.py` — insert a game with `timer_expires_at` in the past, run one watchdog tick, assert game becomes `status='lost', end_reason='timed_out'` and a `send_photo` call was made (mock `app.bot`).
4. `pytest tests/test_daily.py` — `daily_country(date)` stable; 7 consecutive dates produce 7 distinct countries.
5. Flag bundle sanity: after `scripts/download_flags.py`, `ls app/assets/flags | wc -l` ≈ 250 and `docker build` succeeds.
6. Local smoke (`BOT_MODE=polling python -m app.main`):
   - **DM**: `/daily` → tap `🌍 Guess` → `L` → `Luxembourg` → verify photo, overlap %, and no timer line.
   - **Group**: add bot, user A `/daily`, user B picks wrong (watch caption show `⏱ 45s remaining`), wait 10 s, user A picks wrong (caption shows ~`⏱ 45s remaining` again due to +10s extension), stop guessing → watchdog posts `⏰ Time's up!` with full flag within ~5 s of expiry.
   - **Group won**: user A + user B alternate 5 guesses, user A picks correct → win message names user A; `/stats` reflects A `+1 win`, B `+1 loss`.
7. Deploy to **Koyeb** (`git push` with Dockerfile auto-detected, set env secrets for `BOT_TOKEN`, `DATABASE_URL`, `WEBHOOK_URL`), send `/daily` from a real Telegram DM and a real group, play both through to confirm webhook, picker, and watchdog all work against the deployed instance.
