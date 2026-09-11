import pytest
from datetime import datetime
from app.settings import settings
from app.models import Snapshot,Candidate,Decision
from app.ai import DualConsensus,PortfolioAssistant
class Fixed:
    def __init__(self,d):self.d=d
    async def decide(self,c,ctx):return self.d
class Broken:
    async def decide(self,c,ctx):raise RuntimeError("provider unavailable")
def c():
    s=Snapshot(symbol='SBIN',timestamp=datetime.now(settings.tz),ltp=100,open=98,high=102,low=97,volume_ratio=2,bid=99.99,ask=100.01,vwap=99,ema9=100,ema21=98,rsi=60,atr=2,index_change=.5,sector_change=.5,news_risk='LOW',source='test')
    return Candidate(snapshot=s,score=90,reasons=[])
@pytest.mark.asyncio
async def test_first_trade_requires_stricter_confidence(monkeypatch):
    below_first_trade_bar=settings.ai_first_trade_min_confidence-.01
    g=Decision(action='BUY',symbol='SBIN',entry=100,stop=98,target=104,confidence=below_first_trade_bar);o=Decision(action='BUY',symbol='SBIN',entry=100,stop=98,target=104,confidence=.90)
    r=await DualConsensus(Fixed(g),Fixed(o)).run(c(),{'trades_today':0});assert not r.approved
@pytest.mark.asyncio
async def test_both_agree_and_pass():
    g=Decision(action='BUY',symbol='SBIN',entry=100,stop=98,target=104,confidence=.90);o=Decision(action='BUY',symbol='SBIN',entry=100.1,stop=98.1,target=103.8,confidence=.88)
    r=await DualConsensus(Fixed(g),Fixed(o)).run(c(),{'trades_today':0});assert r.approved and r.score>=settings.ai_min_agreement_score
@pytest.mark.asyncio
async def test_secondary_provider_failure_falls_back_to_primary_only():
    g=Decision(action='BUY',symbol='SBIN',entry=100,stop=98,target=104,confidence=.90)
    r=await DualConsensus(Fixed(g),Broken()).run(c(),{'trades_today':0})
    assert r.approved and r.score>=settings.ai_min_agreement_score and r.final.confidence==.90
@pytest.mark.asyncio
async def test_primary_provider_failure_still_raises():
    g=Decision(action='BUY',symbol='SBIN',entry=100,stop=98,target=104,confidence=.90)
    with pytest.raises(RuntimeError):
        await DualConsensus(Broken(),Fixed(g)).run(c(),{'trades_today':0})
@pytest.mark.asyncio
async def test_portfolio_assistant_reports_when_gemini_not_configured(monkeypatch):
    monkeypatch.setattr(settings,"gemini_api_key","")
    result=await PortfolioAssistant().answer("what is my pnl",{})
    assert "not configured" in result
