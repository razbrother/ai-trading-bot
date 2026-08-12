import pytest
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

class FakeApi:
    EXCHANGE_NSE="NSE";SEGMENT_CASH="CASH"
    def __init__(self,quote):self.quote=quote
    def get_quote(self,**k):return dict(self.quote)

@pytest.mark.asyncio
async def test_snapshot_reads_nested_ohlc_and_depth():
    m=GrowwMarket(FakeApi(REAL_QUOTE))
    with pytest.raises(RuntimeError,match="indicators"):
        await m.snapshot(Instrument(symbol="WIPRO",exchange_token="3787"))

@pytest.mark.asyncio
async def test_snapshot_produces_correct_values_once_indicators_present():
    q=dict(REAL_QUOTE)
    q["_computed_indicators"]={"volume_ratio":1.2,"vwap":183,"ema9":183,"ema21":182,
      "rsi":55,"atr":2,"index_change":0,"sector_change":0}
    m=GrowwMarket(FakeApi(q))
    s=await m.snapshot(Instrument(symbol="WIPRO",exchange_token="3787"))
    assert s.high==185.0 and s.low==182.12 and s.open==184.51
    assert s.bid==182.6 and s.ask==182.62
    assert s.ltp==182.58

@pytest.mark.asyncio
async def test_snapshot_raises_on_missing_ohlc():
    q={'last_price':100}
    m=GrowwMarket(FakeApi(q))
    with pytest.raises(RuntimeError,match="missing required field"):
        await m.snapshot(Instrument(symbol="WIPRO",exchange_token="3787"))
