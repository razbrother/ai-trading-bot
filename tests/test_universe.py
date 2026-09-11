import pytest
from app.universe import scan

def make_instrument_master(symbols):
    import pandas as pd
    columns = ["exchange", "segment", "series", "trading_symbol", "exchange_token", "is_intraday", "buy_allowed"]
    rows = [
        {"exchange": "NSE", "segment": "CASH", "series": "EQ", "trading_symbol": s,
         "exchange_token": str(1000 + i), "is_intraday": "1", "buy_allowed": "1"}
        for i, s in enumerate(symbols)
    ]
    return pd.DataFrame(rows, columns=columns)

class FakeApi:
    EXCHANGE_NSE = "NSE"
    SEGMENT_CASH = "CASH"

    def __init__(self, quotes, instruments):
        self.quotes = quotes
        self.instruments = instruments

    def get_all_instruments(self):
        return self.instruments

    def get_quote(self, trading_symbol, **k):
        return self.quotes[trading_symbol]

@pytest.mark.asyncio
async def test_scan_filters_by_price_and_ranks_by_volume():
    quotes = {
        "A": {"last_price": 100, "volume": 500},
        "B": {"last_price": 200, "volume": 2000},
        "C": {"last_price": 2000, "volume": 9999},  # too expensive
    }
    api = FakeApi(quotes, make_instrument_master(["A", "B", "C"]))
    symbols, report = await scan(api, max_price=1500, count=45, candidates=["A", "B", "C"])
    assert symbols == "B:1001,A:1000"

@pytest.mark.asyncio
async def test_scan_skips_symbol_not_in_instrument_master():
    quotes = {"A": {"last_price": 100, "volume": 500}}
    api = FakeApi(quotes, make_instrument_master(["A"]))
    symbols, report = await scan(api, candidates=["A", "NOTLISTED"])
    assert symbols == "A:1000"
    assert any("NOTLISTED" in line and "SKIP" in line for line in report)

@pytest.mark.asyncio
async def test_scan_skips_symbol_when_quote_fails():
    class FlakyApi(FakeApi):
        def get_quote(self, trading_symbol, **k):
            if trading_symbol == "B":
                raise RuntimeError("quote unavailable")
            return super().get_quote(trading_symbol, **k)
    quotes = {"A": {"last_price": 100, "volume": 500}, "B": {"last_price": 100, "volume": 999}}
    api = FlakyApi(quotes, make_instrument_master(["A", "B"]))
    symbols, report = await scan(api, candidates=["A", "B"])
    assert symbols == "A:1000"
    assert any("B" in line and "SKIP" in line for line in report)

@pytest.mark.asyncio
async def test_scan_respects_count_limit():
    quotes = {s: {"last_price": 100, "volume": i} for i, s in enumerate(["A", "B", "C", "D"])}
    api = FakeApi(quotes, make_instrument_master(["A", "B", "C", "D"]))
    symbols, report = await scan(api, count=2, candidates=["A", "B", "C", "D"])
    assert symbols == "D:1003,C:1002"

@pytest.mark.asyncio
async def test_scan_returns_none_when_nothing_qualifies():
    api = FakeApi({}, make_instrument_master([]))
    symbols, report = await scan(api, candidates=["NOTLISTED"])
    assert symbols is None
