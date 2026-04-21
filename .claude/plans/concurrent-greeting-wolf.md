# Plan: Sovereignty split and /play mode selection

## Context
The user wants to split the 245 flags into sovereign countries vs territories/dependencies. The `/play` command should first ask users to choose between "Countries only" (sovereign only) or "All (including territories)" (all 245). The game mode stored in `game_sessions.mode` should reflect this choice as `"random:countries"` or `"random:all"`.

---

## Critical Constraints
- `GameSession.mode` is currently `String(10)`. `"random:countries"` is 16 chars — must expand to `String(20)`.
- No Alembic — migration is a raw SQL script following the `migrate_uq_daily.py` pattern.
- The `play:*` callback handler uses `data.split(":")[1]`, which silently drops the third segment — must fix.
- `get_active_game` does exact string match on mode — will work correctly with new mode strings once column is wide enough.
- `start_random_game` hardcodes `"random"` in two places — must accept a `mode` parameter.

---

## Non-sovereign territories (47 ISO2 codes to mark `is_sovereign=false`)
AI, AS, AW, AX, BL, BM, BQ, CC, CK, CW, CX, EH, FK, FO, GF, GG, GI, GL, GP, GS, GU, HK, IM, IO, JE, KY, MF, MO, MP, MQ, MS, NC, NF, NU, PM, PN, PR, RE, SH, SJ, SX, TC, TK, VG, VI, WF, YT

Special cases treated as sovereign: TW (Taiwan), PS (Palestine), XK (Kosovo)

---

## Files to Change

### 1. `data/countries.json`
Add `"is_sovereign": true/false` to each entry based on the list above.

### 2. `app/db/models.py`
- `Country` model: add `is_sovereign: Mapped[bool] = mapped_column(Boolean, default=True)`
- `GameSession.mode`: change `String(10)` → `String(20)` and update comment to include new modes

### 3. `scripts/migrate_sovereignty.py` (new file)
Raw SQL migration following the `migrate_uq_daily.py` pattern:
```sql
ALTER TABLE countries ADD COLUMN IF NOT EXISTS is_sovereign BOOLEAN DEFAULT TRUE;
ALTER TABLE game_sessions ALTER COLUMN mode TYPE VARCHAR(20);
```

### 4. `scripts/seed_db.py`
Add `is_sovereign=c.get("is_sovereign", True)` to both `insert().values(...)` and `on_conflict_do_update set_` blocks.

### 5. `app/db/crud.py`
- Add `get_sovereign_countries(db)` → filters `Country.is_sovereign == True`
- Modify `get_active_game` to abandon any active random game (both modes): add helper or adjust logic so that `start_random_game` can look for games where `mode.startswith("random")` — OR just call it twice for both modes.
  - Actually simpler: add a new `get_active_random_game(db, chat_id)` that uses `GameSession.mode.like("random%")`.

### 6. `app/game/engine.py`
- `start_random_game`: add `mode: str` parameter (replaces hardcoded `"random"`). Change:
  - `get_active_game(db, chat_id, "random", today)` → `get_active_random_game(db, chat_id)` (abandon any active random game)
  - `crud.create_game(db, ..., "random", ...)` → `crud.create_game(db, ..., mode, ...)`
  - signature receives `mode` as `"random:countries"` or `"random:all"`

### 7. `app/bot/keyboards.py`
- Add `play_mode_keyboard()` → inline keyboard with two buttons:
  - "🌍 Countries only" → `play:random:countries`
  - "🌐 All (including territories)" → `play:random:all`
- Update `play_again_keyboard()` to show mode selection instead of going straight to random. The "🎲 Random game" button → `play:random` which triggers the mode picker.

### 8. `app/bot/handlers.py`
- `cmd_play`: Instead of immediately starting a random game, send a message with `play_mode_keyboard()` to let user choose.
- `handle_callback` — `play:*` block:
  - `play:daily` → `cmd_daily` (unchanged)
  - `play:random` → edit message to show `play_mode_keyboard()` (new: show mode picker)
  - `play:random:countries` → start game with mode `"random:countries"`, filtered countries (sovereign only)
  - `play:random:all` → start game with mode `"random:all"`, all countries
  - Fix the callback parser from `data.split(":")[1]` to handle 3-segment data properly

---

## UX Flow

```
/play command
  → Bot replies: "Choose your flag set:" + [🌍 Countries only] [🌐 All (inc. territories)]

User taps "Countries only"
  → callback: play:random:countries
  → Bot starts game with ~198 sovereign country flags
  → mode stored: "random:countries"

User taps "All (including territories)"
  → callback: play:random:all
  → Bot starts game with all 245 flags
  → mode stored: "random:all"
```

---

## Verification
1. Run migration: `python -m scripts.migrate_sovereignty`
2. Update countries.json manually (script or inline edit)
3. Re-seed: `python -m scripts.seed_db`
4. Start bot with `BOT_MODE=polling python -m app.main`
5. Send `/play` → confirm mode picker appears
6. Tap "Countries only" → confirm game starts with a sovereign country flag
7. Tap "All (including territories)" → confirm game starts with any flag
8. Verify `game_sessions.mode` values in DB are `"random:countries"` or `"random:all"`
9. Run existing test suite: `pytest`
