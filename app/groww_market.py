from __future__ import annotations
import time
from datetime import datetime, timedelta
from app.settings import settings
from app.models import Snapshot
from app import groww_limits, indicators

class GrowwMarket:
    def __init__(self, groww_api):
        self.api=groww_api
        self._ind_cache={}   # symbol -> (monotonic_time, indicators dict)
        self._index_cache=(0.0,None)

    async def _candle_indicators(self,symbol):
        cached=self._ind_cache.get(symbol)
        if cached and time.monotonic()-cached[0]<settings.groww_indicator_cache_seconds:
            return cached[1]
        end=datetime.now(settings.tz);start=end-timedelta(days=settings.groww_indicator_candle_days)
        def call():
            return self.api.get_historical_candles(
                exchange=self.api.EXCHANGE_NSE,segment=self.api.SEGMENT_CASH,
                groww_symbol=f"NSE-{symbol}",start_time=start.strftime("%Y-%m-%d %H:%M:%S"),
                end_time=end.strftime("%Y-%m-%d %H:%M:%S"),candle_interval="5minute")
        raw=await groww_limits.call(groww_limits.nontrading,call)
        raw_rows=raw.get("candles",raw.get("data",[])) if isinstance(raw,dict) else []
        rows=[]
        for r in raw_rows:
            if len(r)<6 or None in r[1:6]:continue
            ts=datetime.fromisoformat(r[0])
            if ts.tzinfo is None:ts=ts.replace(tzinfo=settings.tz)
            rows.append({"date":ts.astimezone(settings.tz).date(),"open":float(r[1]),
              "high":float(r[2]),"low":float(r[3]),"close":float(r[4]),"volume":float(r[5])})
        out=indicators.compute(rows,datetime.now(settings.tz).date())
        self._ind_cache[symbol]=(time.monotonic(),out)
        return out

    async def _index_change(self):
        ts,val=self._index_cache
        if val is not None and time.monotonic()-ts<settings.groww_indicator_cache_seconds:
            return val
        def call():
            return self.api.get_quote(exchange=self.api.EXCHANGE_NSE,segment=self.api.SEGMENT_CASH,
              trading_symbol="NIFTY")
        q=await groww_limits.call(groww_limits.live,call)
        val=float(q["day_change_perc"]) if q.get("day_change_perc") is not None else 0.0
        self._index_cache=(time.monotonic(),val)
        return val

    async def snapshot(self, instrument):
        def call():
            return self.api.get_quote(
                exchange=instrument.exchange,
                segment=instrument.segment,
                trading_symbol=instrument.symbol,
            )
        q=await groww_limits.call(groww_limits.live,call)
        # OHLC arrives nested under "ohlc" on the live API; top-level aliases are
        # also accepted for forward/backward SDK compatibility. All essential
        # values remain mandatory - confirmed against a real account response.
        merged={**(q.get("ohlc") or {}),**q}
        def req(*names):
            for n in names:
                if merged.get(n) is not None:return float(merged[n])
            raise RuntimeError(f"Groww quote missing required field: {names}")
        ltp=req("last_price","ltp","last_traded_price")
        high=req("high","day_high")
        low=req("low","day_low")
        op=req("open","day_open")
        depth=q.get("depth") or {}
        buy=(depth.get("buy") or [{}])[0];sell=(depth.get("sell") or [{}])[0]
        bid=float(buy.get("price") or q.get("bid_price") or q.get("best_bid_price") or ltp)
        ask=float(sell.get("price") or q.get("ask_price") or q.get("best_ask_price") or ltp)
        ind=await self._candle_indicators(instrument.symbol)
        if not ind:
            raise RuntimeError("Live indicators missing; not enough clean recent candles")
        idx=await self._index_change()
        # No per-symbol sector index mapping exists yet; sector_change reuses the
        # broad NIFTY move as a conservative proxy rather than inventing one.
        return Snapshot(symbol=instrument.symbol,timestamp=datetime.now(settings.tz),ltp=ltp,
          open=op,high=high,low=low,volume_ratio=ind["volume_ratio"],
          bid=bid,ask=ask,vwap=ind["vwap"],ema9=ind["ema9"],ema21=ind["ema21"],rsi=ind["rsi"],
          atr=ind["atr"],index_change=idx,sector_change=idx,
          news_risk="UNKNOWN",source="GROWW_LIVE")
    async def snapshots(self,items):
        return [await self.snapshot(i) for i in items]
