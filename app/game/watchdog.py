import asyncio
import io
import logging

from telegram.constants import ParseMode

from app.db import crud
from app.db.session import AsyncSessionLocal
from app.game.image import build_full_flag_image

logger = logging.getLogger(__name__)


async def timer_watchdog(app) -> None:
    """Poll every 5 s for expired group games and auto-announce timeout."""
    from datetime import datetime
    from app.bot import messages

    while True:
        try:
            async with AsyncSessionLocal() as db:
                expired = await crud.get_expired_active_games(db, datetime.utcnow())
                for game in expired:
                    target = await crud.get_country_by_id(db, game.target_country_id)
                    await crud.end_game(db, game, "timed_out", winner_user_id=None)
                    img_bytes, _ = build_full_flag_image(target.iso2)
                    country_name = target.common_name or target.name
                    await app.bot.send_photo(
                        chat_id=game.chat_id,
                        photo=io.BytesIO(img_bytes),
                        caption=messages.timed_out(country_name),
                        parse_mode=ParseMode.MARKDOWN,
                    )
        except Exception:
            logger.exception("timer_watchdog tick failed")
        await asyncio.sleep(5)
