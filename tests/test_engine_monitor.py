import pytest
from datetime import datetime,timedelta
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

class SteppedMarket:
    """Replays a fixed sequence of ticks, one per monitor() call. Each tick is
    (price,atr) or (price,atr,ema9,ema21,volume_ratio) to control momentum
    favorability explicitly - defaults (ema9==ema21, volume_ratio=1) count as
    NOT favorable under _momentum_favorable's strict inequality."""
    def __init__(self,ticks):self.ticks=list(ticks);self.i=-1
    async def snapshot(self,instrument):
        self.i=min(self.i+1,len(self.ticks)-1);tick=self.ticks[self.i]
        ltp,atr=tick[0],tick[1]
        ema9=tick[2] if len(tick)>2 else ltp
        ema21=tick[3] if len(tick)>3 else ltp
        volume_ratio=tick[4] if len(tick)>4 else 1
        return Snapshot(symbol=instrument.symbol,timestamp=datetime.now(settings.tz),ltp=ltp,
          open=ltp,high=ltp+5,low=ltp-5,volume_ratio=volume_ratio,bid=ltp-.01,ask=ltp+.01,
          vwap=ltp,ema9=ema9,ema21=ema21,rsi=55,atr=atr,source="test")

def favorable_buy_tick(ltp,atr):return (ltp,atr,ltp+1,ltp,1.5)
def favorable_sell_tick(ltp,atr):return (ltp,atr,ltp,ltp+1,1.5)

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

class FakeBroker:
    def __init__(self,positions):self._positions=positions
    async def positions(self):return self._positions

def bp(symbol,qty,side=Action.BUY,avg=100):
    return Position(symbol=symbol,qty=qty,side=side,avg_price=avg,stop=0,target=0,
      opened_at=datetime.now(settings.tz))

@pytest.mark.asyncio
async def test_reconcile_ignores_positions_outside_trading_universe(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    db=DB(path=str(tmp_path/"t3.db"))
    broker=FakeBroker([bp("KALYANKJIL",295,Action.SELL),bp("AETHER",90,Action.BUY)])
    async def notify(t):pass
    engine=Engine(None,None,None,None,None,broker,db,notify)
    assert await engine.reconcile()=="reconciliation OK"
    assert not engine.paused

@pytest.mark.asyncio
async def test_reconcile_still_pauses_on_mismatch_within_universe(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    db=DB(path=str(tmp_path/"t4.db"))
    broker=FakeBroker([bp("SBIN",5),bp("KALYANKJIL",295,Action.SELL)])
    notes=[]
    async def notify(t):notes.append(t)
    engine=Engine(None,None,None,None,None,broker,db,notify)
    with pytest.raises(RuntimeError):
        await engine.reconcile()
    assert engine.paused
    assert any("EMERGENCY PAUSE" in n for n in notes)

@pytest.mark.asyncio
async def test_reconcile_ok_when_tracked_positions_match(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    db=DB(path=str(tmp_path/"t5.db"))
    db.save_pos(Position(symbol="SBIN",qty=5,side=Action.BUY,avg_price=100,stop=98,target=104,
      opened_at=datetime.now(settings.tz)))
    broker=FakeBroker([bp("SBIN",5,Action.BUY),bp("AETHER",90,Action.BUY)])
    async def notify(t):pass
    engine=Engine(None,None,None,None,None,broker,db,notify)
    assert await engine.reconcile()=="reconciliation OK"
    assert not engine.paused

@pytest.mark.asyncio
async def test_close_all_closes_every_open_position(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045,TCS:11536")
    db=DB(path=str(tmp_path/"t6.db"))
    db.save_pos(Position(symbol="SBIN",qty=5,side=Action.BUY,avg_price=100,stop=98,target=104,
      opened_at=datetime.now(settings.tz)))
    db.save_pos(Position(symbol="TCS",qty=2,side=Action.SELL,avg_price=200,stop=210,target=190,
      opened_at=datetime.now(settings.tz)))
    notes=[]
    async def notify(t):notes.append(t)
    from app.broker import PaperBroker
    engine=Engine(FixedMarket(100),None,None,None,None,PaperBroker(),db,notify)
    closed=await engine.close_all("EMERGENCY")
    assert set(closed)=={"SBIN","TCS"}
    assert not db.positions()
    with db.conn() as c:
        reasons=[r["reason"] for r in c.execute("SELECT reason FROM trades").fetchall()]
    assert reasons==["EMERGENCY","EMERGENCY"]
    assert any("EXIT SBIN" in n for n in notes) and any("EXIT TCS" in n for n in notes)

@pytest.mark.asyncio
async def test_close_all_skips_position_with_no_instrument_and_warns(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    db=DB(path=str(tmp_path/"t7.db"))
    db.save_pos(Position(symbol="NOTLISTED",qty=1,side=Action.BUY,avg_price=100,stop=98,target=104,
      opened_at=datetime.now(settings.tz)))
    notes=[]
    async def notify(t):notes.append(t)
    from app.broker import PaperBroker
    engine=Engine(FixedMarket(100),None,None,None,None,PaperBroker(),db,notify)
    closed=await engine.close_all("EMERGENCY")
    assert closed==[]
    assert db.positions()
    assert any("WARNING" in n and "NOTLISTED" in n for n in notes)

@pytest.mark.asyncio
async def test_monitor_trails_stop_up_as_price_rises_for_buy(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    monkeypatch.setattr(settings,"force_exit","23:59")
    monkeypatch.setattr(settings,"eod_tighten_minutes",0)
    monkeypatch.setattr(settings,"trailing_atr_multiple",1.5)
    db=DB(path=str(tmp_path/"tr1.db"))
    db.save_pos(Position(symbol="SBIN",qty=1,side=Action.BUY,avg_price=100,stop=95,target=200,
      opened_at=datetime.now(settings.tz)))
    async def notify(t):pass
    engine=Engine(SteppedMarket([favorable_buy_tick(110,2),favorable_buy_tick(112,2)]),
      None,None,None,None,PaperBroker(),db,notify)
    await engine.monitor()
    p=db.positions()[0];assert p.stop==107 and p.peak_price==110
    await engine.monitor()
    p=db.positions()[0];assert p.stop==109 and p.peak_price==112

@pytest.mark.asyncio
async def test_monitor_trailing_stop_never_loosens_when_atr_widens(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    monkeypatch.setattr(settings,"force_exit","23:59")
    monkeypatch.setattr(settings,"eod_tighten_minutes",0)
    monkeypatch.setattr(settings,"trailing_atr_multiple",1.5)
    db=DB(path=str(tmp_path/"tr2.db"))
    db.save_pos(Position(symbol="SBIN",qty=1,side=Action.BUY,avg_price=100,stop=95,target=200,
      opened_at=datetime.now(settings.tz)))
    async def notify(t):pass
    engine=Engine(SteppedMarket([favorable_buy_tick(110,1),favorable_buy_tick(110,5)]),
      None,None,None,None,PaperBroker(),db,notify)
    await engine.monitor()
    p=db.positions()[0];assert p.stop==108.5
    await engine.monitor()  # same price, wider ATR would compute a lower stop -> must not loosen
    p=db.positions()[0];assert p.stop==108.5

@pytest.mark.asyncio
async def test_monitor_trailing_stop_locks_in_profit_on_pullback(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    monkeypatch.setattr(settings,"force_exit","23:59")
    monkeypatch.setattr(settings,"eod_tighten_minutes",0)
    monkeypatch.setattr(settings,"trailing_atr_multiple",1.5)
    db=DB(path=str(tmp_path/"tr3.db"))
    db.save_pos(Position(symbol="SBIN",qty=1,side=Action.BUY,avg_price=100,stop=95,target=200,
      opened_at=datetime.now(settings.tz)))
    async def notify(t):pass
    engine=Engine(SteppedMarket([favorable_buy_tick(110,2),favorable_buy_tick(112,2),favorable_buy_tick(108,2)]),
      None,None,None,None,PaperBroker(),db,notify)
    await engine.monitor();await engine.monitor();await engine.monitor()
    assert not db.positions()
    with db.conn() as c:
        row=c.execute("SELECT reason,net FROM trades").fetchone()
    assert row["reason"]=="STOP" and row["net"]>0

@pytest.mark.asyncio
async def test_monitor_trails_stop_down_as_price_falls_for_sell(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    monkeypatch.setattr(settings,"force_exit","23:59")
    monkeypatch.setattr(settings,"eod_tighten_minutes",0)
    monkeypatch.setattr(settings,"trailing_atr_multiple",1.5)
    db=DB(path=str(tmp_path/"tr4.db"))
    db.save_pos(Position(symbol="SBIN",qty=1,side=Action.SELL,avg_price=100,stop=105,target=80,
      opened_at=datetime.now(settings.tz)))
    async def notify(t):pass
    engine=Engine(SteppedMarket([favorable_sell_tick(90,2),favorable_sell_tick(88,2)]),
      None,None,None,None,PaperBroker(),db,notify)
    await engine.monitor()
    p=db.positions()[0];assert p.stop==93 and p.peak_price==90
    await engine.monitor()
    p=db.positions()[0];assert p.stop==91 and p.peak_price==88

@pytest.mark.asyncio
async def test_monitor_skips_trailing_when_disabled(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    monkeypatch.setattr(settings,"force_exit","23:59")
    monkeypatch.setattr(settings,"trailing_stop_enabled",False)
    db=DB(path=str(tmp_path/"tr5.db"))
    db.save_pos(Position(symbol="SBIN",qty=1,side=Action.BUY,avg_price=100,stop=95,target=200,
      opened_at=datetime.now(settings.tz)))
    async def notify(t):pass
    engine=Engine(SteppedMarket([(110,2)]),None,None,None,None,PaperBroker(),db,notify)
    await engine.monitor()
    p=db.positions()[0];assert p.stop==95 and p.peak_price is None

@pytest.mark.asyncio
async def test_monitor_extends_target_when_near_it_with_favorable_momentum(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    monkeypatch.setattr(settings,"force_exit","23:59")
    monkeypatch.setattr(settings,"eod_tighten_minutes",0)
    monkeypatch.setattr(settings,"trailing_atr_multiple",1.5)
    monkeypatch.setattr(settings,"target_extend_trigger_atr",.5)
    db=DB(path=str(tmp_path/"te1.db"))
    db.save_pos(Position(symbol="SBIN",qty=1,side=Action.BUY,avg_price=100,stop=95,target=110,
      opened_at=datetime.now(settings.tz)))
    async def notify(t):pass
    # ltp=109.5 is within target_extend_trigger_atr(.5)*atr(2)=1 of target(110) -> extends
    engine=Engine(SteppedMarket([favorable_buy_tick(109.5,2)]),None,None,None,None,PaperBroker(),db,notify)
    await engine.monitor()
    p=db.positions()[0];assert p.target==113  # 110 + 1.5*2

@pytest.mark.asyncio
async def test_monitor_target_never_retreats(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    monkeypatch.setattr(settings,"force_exit","23:59")
    monkeypatch.setattr(settings,"eod_tighten_minutes",0)
    db=DB(path=str(tmp_path/"te2.db"))
    db.save_pos(Position(symbol="SBIN",qty=1,side=Action.BUY,avg_price=100,stop=95,target=110,
      opened_at=datetime.now(settings.tz)))
    async def notify(t):pass
    # far from target, momentum favorable -> no extension; target must stay 110
    engine=Engine(SteppedMarket([favorable_buy_tick(101,2)]),None,None,None,None,PaperBroker(),db,notify)
    await engine.monitor()
    p=db.positions()[0];assert p.target==110

@pytest.mark.asyncio
async def test_monitor_tightens_stop_when_momentum_stalls(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    monkeypatch.setattr(settings,"force_exit","23:59")
    monkeypatch.setattr(settings,"eod_tighten_minutes",0)
    monkeypatch.setattr(settings,"trailing_atr_multiple",1.5)
    monkeypatch.setattr(settings,"momentum_stall_tighten_factor",.5)
    monkeypatch.setattr(settings,"breakeven_trigger_r",100)  # keep breakeven floor out of the way
    db=DB(path=str(tmp_path/"te3.db"))
    db.save_pos(Position(symbol="SBIN",qty=1,side=Action.BUY,avg_price=100,stop=95,target=200,
      opened_at=datetime.now(settings.tz)))
    async def notify(t):pass
    # ema9<ema21 -> momentum NOT favorable -> effective multiple is 1.5*.5=.75
    stalled_tick=(110,2,109,111,1.5)
    engine=Engine(SteppedMarket([stalled_tick]),None,None,None,None,PaperBroker(),db,notify)
    await engine.monitor()
    p=db.positions()[0];assert p.stop==round(110-.75*2,2)  # 108.5, tighter than the 107 full-multiple trail

@pytest.mark.asyncio
async def test_monitor_breakeven_floor_kicks_in_at_trigger_r(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    monkeypatch.setattr(settings,"force_exit","23:59")
    monkeypatch.setattr(settings,"eod_tighten_minutes",0)
    monkeypatch.setattr(settings,"trailing_atr_multiple",1.5)
    monkeypatch.setattr(settings,"breakeven_trigger_r",1.0)
    db=DB(path=str(tmp_path/"te4.db"))
    # risk=|100-95|=5 -> breakeven triggers once peak-avg_price>=5, i.e. ltp>=105
    db.save_pos(Position(symbol="SBIN",qty=1,side=Action.BUY,avg_price=100,stop=95,target=200,
      opened_at=datetime.now(settings.tz)))
    async def notify(t):pass
    # plain ATR trail would give 105-1.5*8=93 (below breakeven) - floor must lift it to 100
    engine=Engine(SteppedMarket([favorable_buy_tick(105,8)]),None,None,None,None,PaperBroker(),db,notify)
    await engine.monitor()
    p=db.positions()[0];assert p.stop==100

@pytest.mark.asyncio
async def test_monitor_early_invalidation_exits_on_sharp_adverse_move_with_momentum_against(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    monkeypatch.setattr(settings,"force_exit","23:59")
    monkeypatch.setattr(settings,"trailing_stop_enabled",False)  # isolate early-invalidation from ordinary trail/STOP
    monkeypatch.setattr(settings,"early_invalidation_enabled",True)
    monkeypatch.setattr(settings,"early_invalidation_window_seconds",300)
    monkeypatch.setattr(settings,"early_invalidation_risk_fraction",.5)
    db=DB(path=str(tmp_path/"ei1.db"))
    pos=Position(symbol="SBIN",qty=1,side=Action.BUY,avg_price=100,stop=95,target=200,
      opened_at=datetime.now(settings.tz))
    pos.initial_stop=95
    db.save_pos(pos)
    async def notify(t):pass
    # risk=5, adverse move to 97 gives back 3 (>=.5*5=2.5), momentum against (ema9<ema21)
    engine=Engine(SteppedMarket([(97,2,96,98,1.5)]),None,None,None,None,PaperBroker(),db,notify)
    await engine.monitor()
    assert not db.positions()
    with db.conn() as c:
        row=c.execute("SELECT reason FROM trades").fetchone()
    assert row["reason"]=="EARLY_INVALIDATION"

@pytest.mark.asyncio
async def test_monitor_no_early_invalidation_outside_window(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    monkeypatch.setattr(settings,"force_exit","23:59")
    monkeypatch.setattr(settings,"trailing_stop_enabled",False)  # isolate early-invalidation from ordinary trail/STOP
    monkeypatch.setattr(settings,"early_invalidation_enabled",True)
    monkeypatch.setattr(settings,"early_invalidation_window_seconds",300)
    monkeypatch.setattr(settings,"early_invalidation_risk_fraction",.5)
    db=DB(path=str(tmp_path/"ei2.db"))
    pos=Position(symbol="SBIN",qty=1,side=Action.BUY,avg_price=100,stop=95,target=200,
      opened_at=datetime.now(settings.tz)-timedelta(seconds=400))
    pos.initial_stop=95
    db.save_pos(pos)
    async def notify(t):pass
    engine=Engine(SteppedMarket([(97,2,96,98,1.5)]),None,None,None,None,PaperBroker(),db,notify)
    await engine.monitor()
    assert db.positions()  # too old for early invalidation; still open (stop/target not hit either)

@pytest.mark.asyncio
async def test_monitor_no_early_invalidation_when_momentum_still_favorable(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    monkeypatch.setattr(settings,"force_exit","23:59")
    monkeypatch.setattr(settings,"trailing_stop_enabled",False)  # isolate early-invalidation from ordinary trail/STOP
    monkeypatch.setattr(settings,"early_invalidation_enabled",True)
    monkeypatch.setattr(settings,"early_invalidation_risk_fraction",.5)
    db=DB(path=str(tmp_path/"ei3.db"))
    pos=Position(symbol="SBIN",qty=1,side=Action.BUY,avg_price=100,stop=95,target=200,
      opened_at=datetime.now(settings.tz))
    pos.initial_stop=95
    db.save_pos(pos)
    async def notify(t):pass
    # same adverse move, but momentum still favorable (ema9>ema21) -> no early exit
    engine=Engine(SteppedMarket([favorable_buy_tick(97,2)]),None,None,None,None,PaperBroker(),db,notify)
    await engine.monitor()
    assert db.positions()

@pytest.mark.asyncio
async def test_monitor_tightens_stop_in_eod_window(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"symbols","SBIN:3045")
    monkeypatch.setattr(settings,"trailing_atr_multiple",1.5)
    monkeypatch.setattr(settings,"eod_tighten_minutes",15)
    monkeypatch.setattr(settings,"eod_tighten_factor",.5)
    monkeypatch.setattr(settings,"breakeven_trigger_r",100)  # keep breakeven floor out of the way
    soon=(datetime.now(settings.tz)+timedelta(minutes=5)).strftime("%H:%M")
    monkeypatch.setattr(settings,"force_exit",soon)
    db=DB(path=str(tmp_path/"eod1.db"))
    db.save_pos(Position(symbol="SBIN",qty=1,side=Action.BUY,avg_price=100,stop=95,target=200,
      opened_at=datetime.now(settings.tz)))
    async def notify(t):pass
    engine=Engine(SteppedMarket([favorable_buy_tick(110,2)]),None,None,None,None,PaperBroker(),db,notify)
    await engine.monitor()
    p=db.positions()[0];assert p.stop==round(110-1.5*.5*2,2)  # 108.5, tighter than the normal 107
