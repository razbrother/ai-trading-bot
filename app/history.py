from __future__ import annotations
from datetime import datetime, timedelta
from app.settings import settings
from app.context_data import DataProvenance, HistoricalContext
from app import groww_limits

class NoHistoryProvider:
    async def get(self, symbol: str) -> HistoricalContext:
        return HistoricalContext(symbol=symbol,provenance=DataProvenance(
            source="none",observed_at=datetime.now(settings.tz),is_verified=False))

class GrowwHistoryProvider:
    """Uses official get_historical_candles when available.
    Response parsing is deliberately defensive and must be integration-tested on AWS.
    """
    def __init__(self, api): self.api=api
    async def get(self, symbol: str) -> HistoricalContext:
        end=datetime.now(settings.tz); start=end-timedelta(days=30)
        def call():
            if not hasattr(self.api,"get_historical_candles"):
                raise RuntimeError("Installed Groww SDK lacks get_historical_candles")
            return self.api.get_historical_candles(
                exchange=self.api.EXCHANGE_NSE,
                segment=self.api.SEGMENT_CASH,
                groww_symbol=f"NSE-{symbol}",
                start_time=start.strftime("%Y-%m-%d %H:%M:%S"),
                end_time=end.strftime("%Y-%m-%d %H:%M:%S"),
                candle_interval="5minute",
            )
        raw=await groww_limits.call(groww_limits.nontrading,call)
        rows=raw.get("candles",raw.get("data",[])) if isinstance(raw,dict) else []
        # Rows are [timestamp, open, high, low, close, volume, ...]; leading/thin
        # candles around session open can carry nulls, so only count clean ones.
        clean=[r for r in rows if len(r)>=5 and None not in r[1:5]]
        return HistoricalContext(symbol=symbol,candle_count=len(clean),
          provenance=DataProvenance(source="groww-historical",
          observed_at=datetime.now(settings.tz),is_verified=len(clean)>0,
          details="Official Groww historical candle response"))
