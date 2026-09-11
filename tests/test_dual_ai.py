import pytest
from datetime import datetime
from app.settings import settings
from app.models import Snapshot,Candidate,Decision,Action
from pydantic import ValidationError
from app.ai import DualConsensus,PortfolioAssistant,Selection,RULES,_select_with_retry
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
def test_selection_rejects_buy_sell_without_rank():
    # A structured-output response that picks BUY/SELL but omits selected_rank
    # (exactly what an LLM following only the field's optionality, not the
    # business rule, would produce) must fail validation rather than silently
    # pass through with no candidate identified.
    with pytest.raises(ValidationError,match="rank required"):
        Selection(decision=Decision(action='BUY',symbol='SBIN',entry=100,stop=98,target=104,confidence=.9))
def test_rules_prompt_tells_model_rank_is_required_for_buy_sell():
    # Regression guard: this requirement must be stated in the prompt, not just
    # enforced after the fact - otherwise the provider has no way to know to
    # supply it, and every real BUY/SELL selection fails validation.
    assert "selected_rank" in RULES and "REQUIRED" in RULES
@pytest.mark.asyncio
async def test_select_with_retry_falls_back_to_hold_after_exhausting_attempts(monkeypatch):
    # Simulates a structured-output call that keeps returning truncated/invalid
    # JSON (e.g. a degenerate repetition loop cut off mid-object) - must degrade
    # to a safe HOLD instead of crashing the scan/pick or a caller seeing a raw
    # parser traceback as the "trade decision".
    monkeypatch.setattr(settings,"ai_parse_retry_attempts",2)
    calls=[0]
    def always_fails():
        calls[0]+=1
        raise ValueError("Invalid JSON: EOF while parsing an object")
    result=await _select_with_retry(always_fails,[c()],'Gemini')
    assert calls[0]==2
    assert result.decision.action==Action.HOLD
    assert "unparseable" in result.decision.rationale
@pytest.mark.asyncio
async def test_select_with_retry_succeeds_after_transient_failure(monkeypatch):
    monkeypatch.setattr(settings,"ai_parse_retry_attempts",2)
    calls=[0]
    def flaky():
        calls[0]+=1
        if calls[0]==1:raise ValueError("Invalid JSON: EOF while parsing an object")
        return Selection(selected_rank=1,decision=Decision(action='BUY',symbol='SBIN',entry=100,stop=98,target=104,confidence=.9))
    result=await _select_with_retry(flaky,[c()],'Gemini')
    assert calls[0]==2
    assert result.decision.action==Action.BUY
