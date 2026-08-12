import argparse
import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot
from telegram.ext import Application, CommandHandler

from app.ai import DualConsensus, GeminiAI, HeuristicAI, OpenAITrader
from app.broker import GrowwBroker, PaperBroker
from app.db import DB
from app.engine import Engine
from app.health import HealthService
from app.models import Mode
from app.risk import Risk
from app.runtime import RuntimeOptions, build_sources
from app.settings import settings
from app.singleton import SingletonLock
from app.telegram_console import Confirmations, settings_text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# Telegram's HTTP URLs contain the bot token. Do not expose them in normal logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["paper", "live"],
        default=settings.trading_mode.value.lower(),
    )
    parser.add_argument(
        "--market-source",
        choices=["mock", "groww"],
        default=settings.market_source,
    )
    parser.add_argument(
        "--news-source",
        choices=["none", "json", "gdelt"],
        default=settings.news_source,
    )
    parser.add_argument(
        "--history-source",
        choices=["none", "groww"],
        default=settings.history_source,
    )
    return parser.parse_args()


def build_ai() -> DualConsensus:
    primary = GeminiAI() if settings.gemini_api_key else HeuristicAI("gemini-test")
    if settings.openai_api_key:
        secondary = OpenAITrader()
    elif settings.gemini_api_key:
        # No second real provider configured yet. Both slots run Gemini so the
        # pipeline is usable while testing, but this weakens the dual-AI
        # agreement check - the same model evaluates the same data twice, so
        # "both models agreed" is not independent validation until a real
        # second provider (Groq, OpenAI, etc.) replaces this.
        logging.warning(
            "OPENAI_API_KEY not set: running dual-AI consensus with Gemini on "
            "both sides. Agreement score no longer reflects independent "
            "model validation."
        )
        secondary = GeminiAI()
    else:
        secondary = HeuristicAI("openai-test")
    return DualConsensus(primary, secondary)


async def run() -> None:
    cli = args()
    mode = Mode(cli.mode.upper())
    settings.trading_mode = mode

    lock = SingletonLock(settings.single_instance_lock)
    lock.acquire()

    opts = RuntimeOptions(
        mode=mode,
        market_source=cli.market_source,
        news_source=cli.news_source,
        history_source=cli.history_source,
    )

    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN missing")

    # Keep execution and data access independent. This permits real Groww data
    # with simulated PaperBroker execution.
    execution_broker = PaperBroker() if mode == Mode.PAPER else GrowwBroker()
    data_broker = execution_broker
    if mode == Mode.PAPER and (
        cli.market_source == "groww" or cli.history_source == "groww"
    ):
        data_broker = GrowwBroker()

    market, news, history = build_sources(opts, data_broker)

    ai = build_ai()

    bot = Bot(settings.telegram_bot_token)

    async def notify(text: str) -> None:
        if settings.telegram_allowed_user_id:
            try:
                await bot.send_message(
                    settings.telegram_allowed_user_id,
                    text[:4000],
                )
            except Exception:
                logging.exception("Telegram notification failed")
        else:
            logging.info("NOTIFY %s", text)

    engine = Engine(
        market,
        news,
        history,
        ai,
        Risk(),
        execution_broker,
        DB(),
        notify,
    )
    health = HealthService(engine, opts)
    confirmations = Confirmations()

    if mode == Mode.LIVE:
        if settings.require_telegram_user_lock_in_live and settings.telegram_allowed_user_id is None:
            raise SystemExit("LIVE blocked: TELEGRAM_ALLOWED_USER_ID must be set")
        if settings.require_live_health_pass:
            snapshot = await health.snapshot()
            if not snapshot["live_ready"]:
                raise SystemExit(f"LIVE blocked: health checks failed {snapshot['checks']}")
        if settings.live_require_startup_reconciliation:
            await engine.reconcile()

    app = Application.builder().token(settings.telegram_bot_token).build()

    def authorized(update) -> bool:
        return bool(
            update.effective_user
            and (
                settings.telegram_allowed_user_id is None
                or update.effective_user.id == settings.telegram_allowed_user_id
            )
        )

    async def reject(update) -> None:
        if update.message:
            await update.message.reply_text("Not authorized")

    async def start(update, context) -> None:
        if not authorized(update):
            await reject(update)
            return
        await update.message.reply_text(
            f"AI bot | mode={mode.value} market={cli.market_source} "
            f"news={cli.news_source} history={cli.history_source}"
        )

    async def whoami(update, context) -> None:
        await update.message.reply_text(str(update.effective_user.id))

    async def status(update, context) -> None:
        if not authorized(update):
            await reject(update)
            return
        await update.message.reply_text(
            f"Mode={mode.value} Market={cli.market_source} "
            f"News={cli.news_source} History={cli.history_source}\n"
            f"Auto={engine.auto} Paused={engine.paused} "
            f"Reason={engine.reason or '-'}\n{engine.context()}"
        )

    async def start_auto(update, context) -> None:
        if not authorized(update):
            await reject(update)
            return
        code = confirmations.create(update.effective_user.id, "START")
        await update.message.reply_text(
            f"Reply /confirm {code} within "
            f"{settings.telegram_confirm_timeout_seconds} seconds"
        )

    async def stop_auto(update, context) -> None:
        if not authorized(update):
            await reject(update)
            return
        engine.auto = False
        await update.message.reply_text(
            "New entries stopped; existing positions remain monitored"
        )

    async def emergency(update, context) -> None:
        if not authorized(update):
            await reject(update)
            return
        code = confirmations.create(update.effective_user.id, "EMERGENCY")
        await update.message.reply_text(
            f"Reply /confirm {code} within "
            f"{settings.telegram_confirm_timeout_seconds} seconds"
        )

    async def confirm(update, context) -> None:
        if not authorized(update):
            await reject(update)
            return
        action = confirmations.consume(
            update.effective_user.id,
            " ".join(context.args),
        )
        if action == "START":
            engine.auto = True
            engine.paused = False
            engine.reason = ""
            await update.message.reply_text("Auto trading enabled")
        elif action == "EMERGENCY":
            engine.auto = False
            engine.paused = True
            engine.reason = "manual emergency"
            try:
                closed = await engine.close_all("EMERGENCY")
                text = (
                    f"Emergency pause active. Closed: {', '.join(closed)}."
                    if closed
                    else "Emergency pause active. No open positions to close."
                )
            except Exception as exc:
                text = (
                    "Emergency pause active, but closing positions failed: "
                    f"{exc}. Verify broker positions manually."
                )
            await update.message.reply_text(text)
        else:
            await update.message.reply_text("Invalid or expired confirmation")

    async def resume(update, context) -> None:
        if not authorized(update):
            await reject(update)
            return
        try:
            await engine.reconcile()
            engine.paused = False
            engine.reason = ""
            await update.message.reply_text("Resumed")
        except Exception as exc:
            await update.message.reply_text("Blocked: " + str(exc))

    async def positions(update, context) -> None:
        if not authorized(update):
            await reject(update)
            return
        payload = [x.model_dump(mode="json") for x in engine.db.positions()]
        await update.message.reply_text(str(payload)[:4000])

    async def report(update, context) -> None:
        if authorized(update):
            await update.message.reply_text(str(engine.db.report()))
        else:
            await reject(update)

    async def decision(update, context) -> None:
        if authorized(update):
            await update.message.reply_text(engine.last)
        else:
            await reject(update)

    async def reconcile(update, context) -> None:
        if not authorized(update):
            await reject(update)
            return
        try:
            text = await engine.reconcile()
        except Exception as exc:
            text = "FAILED " + str(exc)
        await update.message.reply_text(text)

    async def settings_cmd(update, context) -> None:
        if authorized(update):
            await update.message.reply_text(settings_text(opts))
        else:
            await reject(update)

    async def health_cmd(update, context) -> None:
        if authorized(update):
            await update.message.reply_text(str(await health.snapshot()))
        else:
            await reject(update)

    async def watchlist(update, context) -> None:
        if not authorized(update):
            await reject(update)
            return
        text = "\n".join(
            f"{index + 1}. {candidate.snapshot.symbol} "
            f"score={candidate.score} source={candidate.snapshot.source}"
            for index, candidate in enumerate(engine.last_candidates)
        )
        await update.message.reply_text(text or "No scan yet")

    handlers = {
        "start": start,
        "whoami": whoami,
        "status": status,
        "settings": settings_cmd,
        "health": health_cmd,
        "watchlist": watchlist,
        "start_auto": start_auto,
        "stop_auto": stop_auto,
        "pause": stop_auto,
        "emergency": emergency,
        "confirm": confirm,
        "resume": resume,
        "positions": positions,
        "report": report,
        "decision": decision,
        "reconcile": reconcile,
    }
    for name, handler in handlers.items():
        app.add_handler(CommandHandler(name, handler))

    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(
        engine.scan,
        "interval",
        seconds=settings.scan_interval_seconds,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        engine.monitor,
        "interval",
        seconds=settings.position_check_seconds,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        engine.reconcile,
        "interval",
        seconds=settings.reconcile_interval_seconds,
        max_instances=1,
        coalesce=True,
    )

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    scheduler.start()
    logging.info(
        "Bot started: mode=%s market=%s news=%s history=%s",
        mode.value,
        cli.market_source,
        cli.news_source,
        cli.history_source,
    )
    try:
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown(False)
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        lock.release()


if __name__ == "__main__":
    asyncio.run(run())
