import pytest
from datetime import datetime, timedelta
from app.settings import settings
from app.groww_market import GrowwMarket
from app.models import Instrument

# Shape captured from a real Groww account response - OHLC nests under "ohlc",
# best bid/ask come from "depth", not flat top-level fields.
REAL_QUOTE={
    'last_price':182.58,
    'ohlc':{'open':184.51,'high':185.0,'low':182.12,'close':184.6},
    'depth':{'buy':[{'price':182.6,'quantity':160}],'sell':[{'price':182.62,'quantity':159}]},
    'volume':3047697,
}
NIFTY_QUOTE={'last_price':24290.65,'day_change_perc':-0.74}

def make_candles(n=40):
    now=datetime.now(settings.tz)
    rows=[]
    for i in range(n):
        ts=(now-timedelta(minutes=5*(n-i))).strftime("%Y-%m-%dT%H:%M:%S")
        p=180.0+i*0.1
        rows.append([ts,p,p+0.5,p-0.5,p+0.2,1000+i,None])
    return rows

class FakeApi:
    EXCHANGE_NSE="NSE";SEGMENT_CASH="CASH"
    def __init__(self,quote,candles,nifty=NIFTY_QUOTE):
        self.quote=quote;self.candles=candles;self.nifty=nifty
    def get_quote(self,trading_symbol,**k):
        return dict(self.nifty) if trading_symbol=="NIFTY" else dict(self.quote)
    def get_historical_candles(self,**k):
        return {"candles":self.candles}

@pytest.mark.asyncio
async def test_snapshot_raises_when_no_clean_candles():
    m=GrowwMarket(FakeApi(REAL_QUOTE,[]))
    with pytest.raises(RuntimeError,match="indicators"):
        await m.snapshot(Instrument(symbol="WIPRO",exchange_token="3787"))

@pytest.mark.asyncio
async def test_snapshot_computes_real_indicators_end_to_end():
    m=GrowwMarket(FakeApi(REAL_QUOTE,make_candles()))
    s=await m.snapshot(Instrument(symbol="WIPRO",exchange_token="3787"))
    assert s.high==185.0 and s.low==182.12 and s.open==184.51
    assert s.bid==182.6 and s.ask==182.62
    assert s.ema9>0 and s.ema21>0 and 0<=s.rsi<=100 and s.atr>0
    assert s.index_change==pytest.approx(-0.74) and s.sector_change==pytest.approx(-0.74)
    assert s.source=="GROWW_LIVE"

@pytest.mark.asyncio
async def test_snapshot_raises_on_missing_ohlc():
    m=GrowwMarket(FakeApi({'last_price':100},make_candles()))
    with pytest.raises(RuntimeError,match="missing required field"):
        await m.snapshot(Instrument(symbol="WIPRO",exchange_token="3787"))

@pytest.mark.asyncio
async def test_indicators_are_cached_between_calls():
    api=FakeApi(REAL_QUOTE,make_candles())
    calls=[0]
    orig=api.get_historical_candles
    def counting(**k):calls[0]+=1;return orig(**k)
    api.get_historical_candles=counting
    m=GrowwMarket(api)
    i=Instrument(symbol="WIPRO",exchange_token="3787")
    await m.snapshot(i);await m.snapshot(i)
    assert calls[0]==1
