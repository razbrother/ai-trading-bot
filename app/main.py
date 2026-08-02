import argparse, asyncio, logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot
from telegram.ext import Application,CommandHandler
from app.settings import settings
from app.db import DB
from app.ai import GeminiAI,OpenAITrader,HeuristicAI,DualConsensus
from app.risk import Risk
from app.broker import PaperBroker,GrowwBroker
from app.engine import Engine
from app.models import Mode
from app.runtime import RuntimeOptions,build_sources
from app.health import HealthService
from app.telegram_console import Confirmations,settings_text

logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(name)s: %(message)s")

def args():
    p=argparse.ArgumentParser()
    p.add_argument("--mode",choices=["paper","live"],default=settings.trading_mode.value.lower())
    p.add_argument("--market-source",choices=["mock","groww"],default=settings.market_source)
    p.add_argument("--news-source",choices=["none","json","gdelt"],default=settings.news_source)
    p.add_argument("--history-source",choices=["none","groww"],default=settings.history_source)
    return p.parse_args()

async def run():
    a=args();mode=Mode(a.mode.upper());settings.trading_mode=mode
    if not settings.telegram_bot_token:raise SystemExit("TELEGRAM_BOT_TOKEN missing")
    broker=PaperBroker() if mode==Mode.PAPER else GrowwBroker()
    market,news,history=build_sources(RuntimeOptions(mode,a.market_source,a.news_source,a.history_source),broker)
    ai=DualConsensus(GeminiAI(),OpenAITrader()) if settings.gemini_api_key and settings.openai_api_key \
       else DualConsensus(HeuristicAI("gemini-test"),HeuristicAI("openai-test"))
    bot=Bot(settings.telegram_bot_token)
    async def notify(t):
        if settings.telegram_allowed_user_id:
            try:await bot.send_message(settings.telegram_allowed_user_id,t[:4000])
            except Exception:logging.exception("notify")
        else:logging.info("NOTIFY %s",t)
    e=Engine(market,news,history,ai,Risk(),broker,DB(),notify)
    health=HealthService(e,opts);confirm=Confirmations()
    app=Application.builder().token(settings.telegram_bot_token).build()
    def auth(u):return u.effective_user and (settings.telegram_allowed_user_id is None or
      u.effective_user.id==settings.telegram_allowed_user_id)
    async def start(u,c):
        if auth(u):await u.message.reply_text(
          f"AI bot | mode={mode.value} market={a.market_source} news={a.news_source} history={a.history_source}")
    async def whoami(u,c):await u.message.reply_text(str(u.effective_user.id))
    async def status(u,c):
        if auth(u):await u.message.reply_text(
          f"Mode={mode.value} Market={a.market_source} News={a.news_source} History={a.history_source}\n"
          f"Auto={e.auto} Paused={e.paused} Reason={e.reason or '-'}\n{e.context()}")
    async def start_auto(u,c):
        if auth(u):e.auto=True;await u.message.reply_text("Auto enabled")
    async def stop_auto(u,c):
        if auth(u):e.auto=False;await u.message.reply_text("New entries stopped")
    async def emergency(u,c):
        if auth(u):e.auto=False;e.paused=True;e.reason="manual emergency";await u.message.reply_text("Emergency stop")
    async def resume(u,c):
        if auth(u):
            try:await e.reconcile();e.paused=False;e.reason="";await u.message.reply_text("Resumed")
            except Exception as x:await u.message.reply_text("Blocked: "+str(x))
    async def positions(u,c):
        if auth(u):await u.message.reply_text(str([x.model_dump(mode="json") for x in e.db.positions()])[:4000])
    async def report(u,c):
        if auth(u):await u.message.reply_text(str(e.db.report()))
    async def decision(u,c):
        if auth(u):await u.message.reply_text(e.last)
    async def reconcile(u,c):
        if auth(u):
            try:t=await e.reconcile()
            except Exception as x:t="FAILED "+str(x)
            await u.message.reply_text(t)
    async def settings_cmd(u,c):
        if auth(u):await u.message.reply_text(settings_text(opts))
    async def health_cmd(u,c):
        if auth(u):await u.message.reply_text(str(await health.snapshot()))
    async def watchlist(u,c):
        if auth(u):await u.message.reply_text("\n".join(f"{i+1}. {x.snapshot.symbol} score={x.score} source={x.snapshot.source}" for i,x in enumerate(e.last_candidates)) or "No scan yet")
    handlers={"start":start,"whoami":whoami,"status":status,"settings":settings_cmd,"health":health_cmd,"watchlist":watchlist,"start_auto":start_auto,
      "stop_auto":stop_auto,"emergency":emergency,"resume":resume,"positions":positions,
      "report":report,"decision":decision,"reconcile":reconcile}
    for n,f in handlers.items():app.add_handler(CommandHandler(n,f))
    sch=AsyncIOScheduler(timezone=settings.timezone)
    sch.add_job(e.scan,"interval",seconds=settings.scan_interval_seconds,max_instances=1,coalesce=True)
    sch.add_job(e.monitor,"interval",seconds=settings.position_check_seconds,max_instances=1,coalesce=True)
    sch.add_job(e.reconcile,"interval",seconds=settings.reconcile_interval_seconds,max_instances=1,coalesce=True)
    await app.initialize();await app.start();await app.updater.start_polling(drop_pending_updates=True);sch.start()
    try:await asyncio.Event().wait()
    finally:sch.shutdown(False);await app.updater.stop();await app.stop();await app.shutdown()
if __name__=="__main__":asyncio.run(run())
