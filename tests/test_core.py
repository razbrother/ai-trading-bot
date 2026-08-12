from datetime import datetime
import pytest
from app.settings import settings
from app.models import Snapshot,Candidate,Decision,ValidOrder
from app.risk import Risk,Reject
from app.broker import PaperBroker
settings.entry_start="00:00";settings.last_entry="23:59"

def cand():
    s=Snapshot(symbol="SBIN",timestamp=datetime.now(settings.tz),ltp=100,open=98,high=102,low=97,
      volume_ratio=2,bid=99.99,ask=100.01,vwap=99,ema9=100,ema21=98,rsi=60,atr=2,
      index_change=.5,sector_change=.5,news_risk="LOW",source="test")
    return Candidate(snapshot=s,score=90,reasons=[])

def test_risk_accepts():
    d=Decision(action="BUY",symbol="SBIN",entry=100,stop=98,target=104,confidence=.9)
    o=Risk().validate(cand(),d,[],0,0);assert o.qty>0 and o.rr==2

def test_risk_rejects_bad_stop():
    d=Decision(action="BUY",symbol="SBIN",entry=100,stop=101,target=104,confidence=.9)
    with pytest.raises(Reject):Risk().validate(cand(),d,[],0,0)

@pytest.mark.asyncio
async def test_paper_lifecycle():
    b=PaperBroker();o=ValidOrder(symbol="SBIN",action="BUY",qty=5,entry=100,stop=98,target=104,
      risk=10,rr=2,confidence=.9,score=90,signal_time=datetime.now(settings.tz))
    x=await b.enter(o);assert x.status.value=="FILLED";p=(await b.positions())[0]
    y=await b.exit(p,104,"TARGET");assert y.status.value=="FILLED" and not await b.positions()
