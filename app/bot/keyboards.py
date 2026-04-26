from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.models import Country

COUNTRIES_PER_PAGE = 16  # 2 columns × 8 rows


def game_keyboard(game_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🌍 Guess", callback_data=f"open_picker:{game_id}"),
            InlineKeyboardButton("🏳️ Give Up", callback_data=f"giveup:{game_id}"),
        ]
    ])


def alphabet_keyboard(game_id: int) -> InlineKeyboardMarkup:
    letters = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    rows = []
    for i in range(0, len(letters), 7):
        row = [
            InlineKeyboardButton(l, callback_data=f"letter:{game_id}:{l}")
            for l in letters[i:i + 7]
        ]
        rows.append(row)
    rows.append([InlineKeyboardButton("✖ Cancel", callback_data=f"cancel_pick:{game_id}")])
    return InlineKeyboardMarkup(rows)


def letter_countries_keyboard(
    game_id: int,
    letter: str,
    countries: list[Country],
    page: int = 0,
) -> InlineKeyboardMarkup:
    """2-column country list (≤16/page) filtered by starting letter."""
    matching = [
        c for c in countries
        if (c.common_name or c.name).upper().startswith(letter.upper())
    ]
    matching.sort(key=lambda c: (c.common_name or c.name).upper())

    total_pages = max(1, (len(matching) + COUNTRIES_PER_PAGE - 1) // COUNTRIES_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    slice_ = matching[page * COUNTRIES_PER_PAGE:(page + 1) * COUNTRIES_PER_PAGE]

    rows = []
    for i in range(0, len(slice_), 2):
        row = []
        for country in slice_[i:i + 2]:
            label = country.common_name or country.name
            row.append(InlineKeyboardButton(label, callback_data=f"pick:{game_id}:{country.iso2}"))
        rows.append(row)

    # Navigation row
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀", callback_data=f"letter_page:{game_id}:{letter}:{page - 1}"))
    nav.append(InlineKeyboardButton("← A-Z", callback_data=f"open_picker:{game_id}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("▶", callback_data=f"letter_page:{game_id}:{letter}:{page + 1}"))
    rows.append(nav)

    return InlineKeyboardMarkup(rows)


def play_mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🌍 Countries only", callback_data="play:random:countries"),
            InlineKeyboardButton("🌐 All (incl. territories)", callback_data="play:random:all"),
        ]
    ])


def play_again_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎲 Random game", callback_data="play:random"),
            InlineKeyboardButton("📅 Daily", callback_data="play:daily"),
        ]
    ])


def random_game_button_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 Random game", callback_data="play:random")]
    ])


def daily_button_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Daily", callback_data="play:daily")]
    ])
