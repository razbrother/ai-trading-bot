import pytest
from datetime import datetime
from app.settings import settings
from app.models import Snapshot,Candidate,Decision
from app.ai import Selection,DualConsensus
class F:
 def __init__(self,x):self.x=x
 async def select(self,c,ctx):return self.x
def c(sym='SBIN',price=100):
 s=Snapshot(symbol=sym,timestamp=datetime.now(settings.tz),ltp=price,open=99,high=price+2,low=98,volume_ratio=2,bid=price-.01,ask=price+.01,vwap=99,ema9=100,ema21=98,rsi=60,atr=2,index_change=.5,sector_change=.5,news_risk='LOW',source='GROWW_LIVE');return Candidate(snapshot=s,score=90,reasons=[])
@pytest.mark.asyncio
async def test_symbol_disagreement_rejected():
 g=Selection(selected_rank=1,decision=Decision(action='BUY',symbol='SBIN',entry=100,stop=98,target=104,confidence=.9));o=Selection(selected_rank=2,decision=Decision(action='BUY',symbol='TCS',entry=200,stop=196,target=208,confidence=.9));r=await DualConsensus(F(g),F(o)).run([c(),c('TCS',200)],{'trades_today':0});assert not r.approved
@pytest.mark.asyncio
async def test_same_selection_passes():
 g=Selection(selected_rank=1,decision=Decision(action='BUY',symbol='SBIN',entry=100,stop=98,target=104,confidence=.9));o=Selection(selected_rank=1,decision=Decision(action='BUY',symbol='SBIN',entry=100.1,stop=98.1,target=103.8,confidence=.88));r=await DualConsensus(F(g),F(o)).run([c()],{'trades_today':0});assert r.approved
