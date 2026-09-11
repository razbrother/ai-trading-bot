import pytest
from datetime import datetime
from app.settings import settings
from app.models import Snapshot,Decision
from app.ai import Selection,DualConsensus
from app.broker import PaperBroker
from app.risk import Risk
from app.db import DB
from app.engine import Engine
from app.news import NoNewsProvider
from app.history import NoHistoryProvider

settings.entry_start="00:00";settings.last_entry="23:59";settings.require_history_for_entry=False

class FixedMarket:
    def __init__(self,ltp=100,atr=2):self.ltp=ltp;self.atr=atr
    async def snapshot(self,instrument):
        return Snapshot(symbol=instrument.symbol,timestamp=datetime.now(settings.tz),ltp=self.ltp,
          open=self.ltp,high=self.ltp+5,low=self.ltp-5,volume_ratio=1,bid=self.ltp-.01,ask=self.ltp+.01,
          vwap=self.ltp,ema9=self.ltp,ema21=self.ltp,rsi=55,atr=self.atr,source="test")

class F:
    def __init__(self,x):self.x=x
    async def select(self,c,ctx):return self.x

class ResolvingMarket(FixedMarket):
    """A market double simulating GrowwMarket.resolve() against an instrument
    master, for symbols not pre-configured in SYMBOLS."""
    def __init__(self,known,ltp=100,atr=2):
        super().__init__(ltp,atr);self.known=known
    async def resolve(self,symbol):
        if symbol.upper() not in self.known:return None
        from app.models import Instrument
        return Instrument(symbol=symbol.upper(),exchange_token="999")

def buy_selection(confidence,rank=1,symbol="SBIN"):
    return Selection(selected_rank=rank,decision=Decision(action="BUY",symbol=symbol,entry=100,
      stop=98,target=104,confidence=confidence))

def sell_selection(confidence,rank=1):
    return Selection(selected_rank=rank,decision=Decision(action="SELL",symbol="SBIN",entry=100,
      stop=102,target=96,confidence=confidence))

def make_engine(tmp_path,ai,name,ltp=100,atr=2):
    db=DB(path=str(tmp_path/name))
    async def notify(t):pass
    return Engine(FixedMarket(ltp,atr),NoNewsProvider(),NoHistoryProvider(),ai,Risk(),
      PaperBroker(),db,notify)

@pytest.mark.asyncio
async def test_pick_rejects_unknown_symbol(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    ai=DualConsensus(F(buy_selection(.9)),F(buy_selection(.9)))
    engine=make_engine(tmp_path,ai,"unknown.db")
    result=await engine.pick("NOTLISTED")
    assert "not found or not intraday-tradeable" in result
    assert not engine.db.positions()

@pytest.mark.asyncio
async def test_pick_skips_technical_score_gate_but_still_trades(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    # FixedMarket's flat snapshot (ema9==ema21, ltp==vwap, no volume/index/sector edge)
    # scores well under the default min_technical_score=75 gate.
    ai=DualConsensus(F(buy_selection(.9)),F(buy_selection(.9)))
    engine=make_engine(tmp_path,ai,"skip_score.db")
    result=await engine.pick("SBIN")
    assert result=="opened SBIN"
    assert engine.db.positions()[0].symbol=="SBIN"

@pytest.mark.asyncio
async def test_pick_still_enforces_ai_confidence_gate(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    ai=DualConsensus(F(buy_selection(.5)),F(buy_selection(.5)))
    engine=make_engine(tmp_path,ai,"low_conf.db")
    result=await engine.pick("SBIN")
    assert "approved=False" in result
    assert not engine.db.positions()

@pytest.mark.asyncio
async def test_pick_blocked_when_paused(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    ai=DualConsensus(F(buy_selection(.9)),F(buy_selection(.9)))
    engine=make_engine(tmp_path,ai,"paused.db")
    engine.paused=True;engine.reason="market-data anomalies: test"
    result=await engine.pick("SBIN")
    assert result.startswith("paused:")
    assert not engine.db.positions()

@pytest.mark.asyncio
async def test_pick_blocked_when_position_exists(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    ai=DualConsensus(F(buy_selection(.9)),F(buy_selection(.9)))
    engine=make_engine(tmp_path,ai,"has_pos.db")
    first=await engine.pick("SBIN")
    assert first=="opened SBIN"
    second=await engine.pick("SBIN")
    assert second=="position exists"

@pytest.mark.asyncio
async def test_pick_resolves_symbol_not_in_symbols_via_market(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    ai=DualConsensus(F(buy_selection(.9,symbol="MVELECTRO")),F(buy_selection(.9,symbol="MVELECTRO")))
    db=DB(path=str(tmp_path/"dynamic.db"))
    async def notify(t):pass
    engine=Engine(ResolvingMarket({"MVELECTRO"}),NoNewsProvider(),NoHistoryProvider(),ai,Risk(),
      PaperBroker(),db,notify)
    result=await engine.pick("MVELECTRO")
    assert result=="opened MVELECTRO"

@pytest.mark.asyncio
async def test_pick_reports_unresolvable_symbol_from_market(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    ai=DualConsensus(F(buy_selection(.9)),F(buy_selection(.9)))
    db=DB(path=str(tmp_path/"dynamic2.db"))
    async def notify(t):pass
    engine=Engine(ResolvingMarket(set()),NoNewsProvider(),NoHistoryProvider(),ai,Risk(),
      PaperBroker(),db,notify)
    result=await engine.pick("FAKESTOCK")
    assert "not found or not intraday-tradeable" in result

@pytest.mark.asyncio
async def test_ask_delegates_to_assistant_with_context(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    ai=DualConsensus(F(buy_selection(.9)),F(buy_selection(.9)))
    engine=make_engine(tmp_path,ai,"ask1.db")
    seen={}
    async def fake_answer(question,context):
        seen["question"]=question;seen["context"]=context;return "42"
    engine.assistant.answer=fake_answer
    result=await engine.ask("what is my pnl today")
    assert result=="42"
    assert seen["question"]=="what is my pnl today"
    assert "report" in seen["context"] and "today" in seen["context"] and "watchlist" in seen["context"]

@pytest.mark.asyncio
async def test_check_delivery_yes_when_both_buy_and_confident(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    monkeypatch.setattr(settings,"delivery_check_min_confidence",.75)
    ai=DualConsensus(F(buy_selection(.9)),F(buy_selection(.8)))
    engine=make_engine(tmp_path,ai,"delivery_yes.db")
    result=await engine.check_delivery("SBIN")
    assert result.startswith("YES")
    assert not engine.db.positions()

@pytest.mark.asyncio
async def test_check_delivery_no_when_confidence_below_bar(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    monkeypatch.setattr(settings,"delivery_check_min_confidence",.75)
    ai=DualConsensus(F(buy_selection(.9)),F(buy_selection(.7)))
    engine=make_engine(tmp_path,ai,"delivery_no_conf.db")
    result=await engine.check_delivery("SBIN")
    assert result.startswith("NO")

@pytest.mark.asyncio
async def test_check_delivery_no_when_providers_disagree_on_direction(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    ai=DualConsensus(F(buy_selection(.9)),F(sell_selection(.9)))
    engine=make_engine(tmp_path,ai,"delivery_no_dir.db")
    result=await engine.check_delivery("SBIN")
    assert result.startswith("NO")

@pytest.mark.asyncio
async def test_check_delivery_rejects_unknown_symbol(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    ai=DualConsensus(F(buy_selection(.9)),F(buy_selection(.9)))
    engine=make_engine(tmp_path,ai,"delivery_unknown.db")
    result=await engine.check_delivery("NOTLISTED")
    assert "not found or not intraday-tradeable" in result

@pytest.mark.asyncio
async def test_check_delivery_works_even_when_paused_or_position_open(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    ai=DualConsensus(F(buy_selection(.9)),F(buy_selection(.9)))
    engine=make_engine(tmp_path,ai,"delivery_paused.db")
    engine.paused=True;engine.reason="test"
    result=await engine.check_delivery("SBIN")
    assert result.startswith("YES")
