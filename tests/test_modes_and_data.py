import pytest
from datetime import datetime
from app.models import Mode,Snapshot
from app.settings import settings
from app.data_policy import validate_runtime_sources,DataPolicyError
from app.fake_data_analyzer import analyze_snapshot

def snap(source):
    return Snapshot(symbol="SBIN",timestamp=datetime.now(settings.tz),ltp=100,open=99,high=101,low=98,
      volume_ratio=1.5,bid=99.9,ask=100.1,vwap=99.5,ema9=100,ema21=99,rsi=60,atr=2,
      index_change=.2,sector_change=.3,news_risk="LOW",source=source)

def test_live_rejects_mock():
    with pytest.raises(DataPolicyError):
        validate_runtime_sources(Mode.LIVE,"mock","none","groww")

def test_paper_accepts_mock():
    validate_runtime_sources(Mode.PAPER,"mock","none","groww")

def test_fake_analyzer_flags_mock():
    assert any("NON_LIVE_SOURCE" in x for x in analyze_snapshot(snap("MOCK")))

def test_fake_analyzer_accepts_groww_source():
    assert not any("NON_LIVE_SOURCE" in x for x in analyze_snapshot(snap("GROWW_LIVE")))
