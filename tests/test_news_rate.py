import pytest
from datetime import datetime
from app.rate_limit import RollingRateLimiter
from app.gdelt_news import GDELTNewsProvider
from app.context_data import NewsContext,DataProvenance
from app.settings import settings
@pytest.mark.asyncio
async def test_limiter():
    r=RollingRateLimiter(2,10);await r.acquire();await r.acquire()
    assert len(r.s)==2 and len(r.m)==2
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
