import pytest
from datetime import datetime
from app.settings import settings
from app.models import Action, Snapshot
from app.broker import PaperBroker
from app.risk import Risk
from app.db import DB
from app.engine import Engine
from app.news import NoNewsProvider
from app.history import NoHistoryProvider

settings.entry_start = "00:00"
settings.last_entry = "23:59"
settings.require_history_for_entry = False


class FixedMarket:
    def __init__(self, ltp=100, atr=2):
        self.ltp = ltp
        self.atr = atr

    async def snapshot(self, instrument):
        return Snapshot(symbol=instrument.symbol, timestamp=datetime.now(settings.tz), ltp=self.ltp,
          open=self.ltp, high=self.ltp + 5, low=self.ltp - 5, volume_ratio=1, bid=self.ltp - .01,
          ask=self.ltp + .01, vwap=self.ltp, ema9=self.ltp, ema21=self.ltp, rsi=55, atr=self.atr,
          source="test")


def make_engine(tmp_path, name, ltp=100, atr=2):
    db = DB(path=str(tmp_path / name))

    async def notify(t):
        pass

    return Engine(FixedMarket(ltp, atr), NoNewsProvider(), NoHistoryProvider(), None, Risk(),
      PaperBroker(), db, notify)


@pytest.mark.asyncio
async def test_manual_blocked_when_auto_off(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "symbols", "SBIN:3045")
    engine = make_engine(tmp_path, "auto_off.db")
    result = await engine.manual("SBIN", Action.BUY)
    assert result.startswith("Auto trading is off")
    assert not engine.db.positions()


@pytest.mark.asyncio
async def test_manual_buy_executes_when_auto_on(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "symbols", "SBIN:3045")
    engine = make_engine(tmp_path, "buy_on.db")
    engine.auto = True
    result = await engine.manual("SBIN", Action.BUY)
    assert result.startswith("opened SBIN BUY")
    pos = engine.db.positions()[0]
    assert pos.symbol == "SBIN" and pos.side == Action.BUY
    assert pos.stop < pos.avg_price < pos.target


@pytest.mark.asyncio
async def test_manual_sell_executes_when_auto_on(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "symbols", "SBIN:3045")
    engine = make_engine(tmp_path, "sell_on.db")
    engine.auto = True
    result = await engine.manual("SBIN", Action.SELL)
    assert result.startswith("opened SBIN SELL")
    pos = engine.db.positions()[0]
    assert pos.symbol == "SBIN" and pos.side == Action.SELL
    assert pos.target < pos.avg_price < pos.stop


@pytest.mark.asyncio
async def test_manual_blocked_when_paused(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "symbols", "SBIN:3045")
    engine = make_engine(tmp_path, "paused.db")
    engine.auto = True
    engine.paused = True
    engine.reason = "test"
    result = await engine.manual("SBIN", Action.BUY)
    assert result.startswith("paused:")
    assert not engine.db.positions()


@pytest.mark.asyncio
async def test_manual_blocked_when_position_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "symbols", "SBIN:3045")
    engine = make_engine(tmp_path, "has_pos.db")
    engine.auto = True
    first = await engine.manual("SBIN", Action.BUY)
    assert first.startswith("opened")
    second = await engine.manual("SBIN", Action.SELL)
    assert second == "position exists"


@pytest.mark.asyncio
async def test_manual_rejects_unknown_symbol(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "symbols", "SBIN:3045")
    engine = make_engine(tmp_path, "unknown.db")
    engine.auto = True
    result = await engine.manual("NOTLISTED", Action.BUY)
    assert "not found or not intraday-tradeable" in result
    assert not engine.db.positions()
