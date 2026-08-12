from __future__ import annotations
from datetime import datetime
from app.settings import settings
from app.models import Snapshot
from app.market import score
from app import groww_limits

class GrowwMarket:
    def __init__(self, groww_api): self.api=groww_api

    async def snapshot(self, instrument):
        def call():
            return self.api.get_quote(
                exchange=instrument.exchange,
                segment=instrument.segment,
                trading_symbol=instrument.symbol,
            )
        q=await groww_limits.call(groww_limits.live,call)
        # Common field aliases are accepted, but all essential values remain mandatory.
        def req(*names):
            for n in names:
                if q.get(n) is not None:return float(q[n])
            raise RuntimeError(f"Groww quote missing required field: {names}")
        ltp=req("last_price","ltp","last_traded_price")
        high=req("high","day_high")
        low=req("low","day_low")
        op=req("open","day_open")
        bid=float(q.get("bid_price") or q.get("best_bid_price") or ltp)
        ask=float(q.get("ask_price") or q.get("best_ask_price") or ltp)
        # Indicators require candles; placeholder values are forbidden in live mode.
        indicators=q.get("_computed_indicators")
        if not indicators:
            raise RuntimeError("Live indicators missing; compute from verified completed candles")
        return Snapshot(symbol=instrument.symbol,timestamp=datetime.now(settings.tz),ltp=ltp,
          open=op,high=high,low=low,volume_ratio=float(indicators["volume_ratio"]),
          bid=bid,ask=ask,vwap=float(indicators["vwap"]),ema9=float(indicators["ema9"]),
          ema21=float(indicators["ema21"]),rsi=float(indicators["rsi"]),
          atr=float(indicators["atr"]),index_change=float(indicators["index_change"]),
          sector_change=float(indicators["sector_change"]),
          news_risk=str(indicators.get("news_risk","UNKNOWN")),source="GROWW_LIVE")
    async def snapshots(self,items):
        return [await self.snapshot(i) for i in items]
