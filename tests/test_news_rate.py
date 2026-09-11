import pytest
from datetime import datetime
from app.rate_limit import RollingRateLimiter,DailyCallLimiter
from app.gdelt_news import GDELTNewsProvider
from app.context_data import NewsContext,DataProvenance
from app.settings import settings
@pytest.mark.asyncio
async def test_limiter():
    r=RollingRateLimiter(2,10);await r.acquire();await r.acquire()
    assert len(r.s)==2 and len(r.m)==2
@pytest.mark.asyncio
async def test_daily_call_limiter_caps():
    lim=DailyCallLimiter(2,settings.tz);await lim.acquire();await lim.acquire()
    with pytest.raises(RuntimeError):await lim.acquire()
@pytest.mark.asyncio
async def test_daily_call_limiter_warns_once_at_threshold():
    warnings=[]
    async def notify(t):warnings.append(t)
    lim=DailyCallLimiter(10,settings.tz,notify,warn_at=.8)
    for _ in range(7):await lim.acquire()
    assert not warnings
    await lim.acquire()  # 8/10 = 80%, crosses threshold
    assert len(warnings)==1 and "8/10" in warnings[0]
    await lim.acquire();await lim.acquire()
    assert len(warnings)==1  # doesn't re-warn every call after crossing
@pytest.mark.asyncio
async def test_daily_call_limiter_warning_resets_next_day(monkeypatch):
    warnings=[]
    async def notify(t):warnings.append(t)
    lim=DailyCallLimiter(2,settings.tz,notify,warn_at=.5)
    await lim.acquire()
    assert len(warnings)==1
    lim.day=None  # simulate day rollover
    await lim.acquire()
    assert len(warnings)==2
def test_news_terms():
    assert settings.news_term_map["SBIN"]=="State Bank of India"
@pytest.mark.asyncio
async def test_cache(monkeypatch):
    p=GDELTNewsProvider();calls=0
    async def fake(symbol):
        nonlocal calls;calls+=1
        return NewsContext(items=[],risk="UNKNOWN",provenance=DataProvenance(
            source="test",observed_at=datetime.now(settings.tz),is_verified=False))
    monkeypatch.setattr(p,"fetch",fake)
    await p.get("SBIN");await p.get("SBIN")
    assert calls==1
