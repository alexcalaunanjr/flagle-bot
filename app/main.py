"""FastAPI application entry point.

Webhook mode (production):
  - Telegram sends POST requests to /webhook
  - The FastAPI app forwards them to the PTB Application

Polling mode (local dev):
  - Set BOT_MODE=polling in .env
  - Run: python -m app.main
  - No public URL needed
"""

import asyncio
import logging

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, Response
from telegram import Update
from telegram.ext import Application

from app.bot.handlers import register_handlers
from app.config import settings
from app.db.session import Base, engine
from app.game.image import VALID_VIS_MODES, visualize_comparison
from app.game.watchdog import timer_watchdog

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Build the Telegram Application (PTB)
ptb_app: Application = (
    Application.builder()
    .token(settings.bot_token)
    .build()
)
register_handlers(ptb_app)

# Build the FastAPI app
app = FastAPI(title="Flagle Bot")

_watchdog_task = None


@app.on_event("startup")
async def startup() -> None:
    global _watchdog_task

    # Create all DB tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if settings.bot_mode == "webhook":
        await ptb_app.initialize()
        await ptb_app.bot.set_webhook(
            url=settings.webhook_url,
            allowed_updates=Update.ALL_TYPES,
        )
        logger.info("Webhook set to %s", settings.webhook_url)
    else:
        logger.info("Running in polling mode (webhook not set)")

    _watchdog_task = asyncio.create_task(timer_watchdog(ptb_app))
    logger.info("Timer watchdog started")


@app.on_event("shutdown")
async def shutdown() -> None:
    global _watchdog_task
    if _watchdog_task:
        _watchdog_task.cancel()
    if settings.bot_mode == "webhook":
        await ptb_app.shutdown()


@app.post("/webhook")
async def webhook(request: Request) -> Response:
    data = await request.json()
    update = Update.de_json(data, ptb_app.bot)
    await ptb_app.process_update(update)
    return Response(status_code=200)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/compare/{target}/{guess}")
async def compare(
    target: str,
    guess: str,
    mode: str = Query("heatmap", description=f"one of {list(VALID_VIS_MODES)}"),
) -> Response:
    if mode not in VALID_VIS_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"mode must be one of {list(VALID_VIS_MODES)}",
        )
    try:
        png, score, similarity_pct = visualize_comparison(target, guess, mode)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="unknown iso2 code")

    return Response(
        content=png,
        media_type="image/png",
        headers={
            "X-SSIM-Score": f"{score:.6f}",
            "X-Similarity-Percentage": f"{similarity_pct:.2f}",
        },
    )


# ── Polling entry point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    from app.db.session import Base, engine as db_engine

    async def run_polling():
        async with db_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with ptb_app:
            await ptb_app.start()
            await ptb_app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
            watchdog = asyncio.create_task(timer_watchdog(ptb_app))
            logger.info("Bot is polling for updates. Press Ctrl+C to stop.")
            try:
                await asyncio.Event().wait()
            finally:
                watchdog.cancel()
                await ptb_app.updater.stop()
                await ptb_app.stop()

    asyncio.run(run_polling())
