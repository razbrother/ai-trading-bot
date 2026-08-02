from datetime import datetime
from app.settings import settings
from app.models import Mode, Snapshot
from app.context_data import NewsContext, HistoricalContext

class DataPolicyError(RuntimeError): pass

def validate_runtime_sources(mode: Mode, market_source: str, news_source: str, history_source: str):
    market_source = market_source.lower()
    if mode == Mode.LIVE and market_source in {"mock", "fake", "simulated"}:
        raise DataPolicyError("LIVE mode cannot use simulated/fake market data")
    if settings.allow_mock_paper_only and market_source == "mock" and mode != Mode.PAPER:
        raise DataPolicyError("Mock data is restricted to PAPER mode")
    if mode == Mode.LIVE and history_source == "none" and settings.require_history_for_entry:
        raise DataPolicyError("LIVE mode requires a configured historical-data source")
    if mode == Mode.LIVE and news_source == "none" and settings.require_news_for_entry:
        raise DataPolicyError("LIVE mode requires a configured news source")

def validate_entry_context(snapshot: Snapshot, news: NewsContext, history: HistoricalContext, mode: Mode):
    now = datetime.now(settings.tz)
    market_age = (now - snapshot.timestamp.astimezone(settings.tz)).total_seconds()
    max_age = settings.max_market_data_age_seconds if mode == Mode.LIVE else settings.max_signal_age_seconds
    if market_age > max_age:
        raise DataPolicyError(f"Market snapshot stale: {market_age:.1f}s")
    if mode == Mode.LIVE and snapshot.source.upper() in {"MOCK", "FAKE", "SIMULATED"}:
        raise DataPolicyError("Simulated snapshot reached live entry gate")
    if settings.require_history_for_entry:
        if not history.provenance.is_verified:
            raise DataPolicyError("Historical context is not verified")
        if history.candle_count < settings.min_history_candles:
            raise DataPolicyError("Insufficient historical candles")
    if settings.require_news_for_entry:
        if not news.provenance.is_verified:
            raise DataPolicyError("News context is not verified")
        if news.provenance.age_seconds() > settings.max_news_age_minutes * 60:
            raise DataPolicyError("News context is stale")
