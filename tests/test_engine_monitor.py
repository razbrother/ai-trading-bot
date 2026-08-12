import pytest
from datetime import datetime
from app.settings import settings
from app.models import Mode,Action,Position,Snapshot
from app.broker import PaperBroker
from app.db import DB
from app.engine import Engine

class FixedMarket:
    def __init__(self,ltp):self.ltp=ltp
    async def snapshot(self,instrument):
        return Snapshot(symbol=instrument.symbol,timestamp=datetime.now(settings.tz),ltp=self.ltp,
          open=self.ltp,high=self.ltp+5,low=self.ltp-5,volume_ratio=1,bid=self.ltp-.01,ask=self.ltp+.01,
          vwap=self.ltp,ema9=self.ltp,ema21=self.ltp,rsi=55,atr=2,source="test")

@pytest.mark.asyncio
async def test_monitor_pauses_on_unknown_symbol(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    db=DB(path=str(tmp_path/"t.db"))
    db.save_pos(Position(symbol="NOTLISTED",qty=1,side=Action.BUY,avg_price=100,stop=98,target=104,
      opened_at=datetime.now(settings.tz)))
    notes=[]
    async def notify(t):notes.append(t)
    engine=Engine(FixedMarket(100),None,None,None,None,PaperBroker(),db,notify)
    await engine.monitor()
    assert engine.paused
    assert any("EMERGENCY PAUSE" in n for n in notes)
    assert db.positions()

@pytest.mark.asyncio
async def test_monitor_uses_live_cost_bps_in_live_mode(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    monkeypatch.setattr(settings,"trading_mode",Mode.LIVE)
    monkeypatch.setattr(settings,"live_cost_bps",999)
    monkeypatch.setattr(settings,"paper_cost_bps",1)
    db=DB(path=str(tmp_path/"t2.db"))
    db.save_pos(Position(symbol="SBIN",qty=1,side=Action.BUY,avg_price=100,stop=98,target=104,
      opened_at=datetime.now(settings.tz)))
    async def notify(t):pass
    engine=Engine(FixedMarket(110),None,None,None,None,PaperBroker(),db,notify)
    await engine.monitor()
    assert db.report()["net"]<0
