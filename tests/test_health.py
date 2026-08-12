import pytest
from dataclasses import dataclass
from app.settings import settings
from app.models import Mode
from app.health import HealthService

@dataclass
class Opts:
    mode:Mode;market_source:str;news_source:str;history_source:str

@pytest.mark.asyncio
async def test_paper_mode_only_requires_database(monkeypatch):
    monkeypatch.setattr(settings,"telegram_allowed_user_id",None)
    monkeypatch.setattr(settings,"gemini_api_key","")
    monkeypatch.setattr(settings,"openai_api_key","")
    monkeypatch.setattr(settings,"groww_totp_token","");monkeypatch.setattr(settings,"groww_totp_secret","")
    monkeypatch.setattr(settings,"groww_api_key","");monkeypatch.setattr(settings,"groww_api_secret","")
    h=HealthService(None,Opts(Mode.PAPER,"mock","none","none"))
    snap=await h.snapshot()
    assert snap["live_ready"] is True

@pytest.mark.asyncio
async def test_live_mode_ready_without_openai_key_when_gemini_only(monkeypatch):
    monkeypatch.setattr(settings,"telegram_allowed_user_id",123)
    monkeypatch.setattr(settings,"gemini_api_key","g")
    monkeypatch.setattr(settings,"openai_api_key","")
    monkeypatch.setattr(settings,"groww_totp_token","t");monkeypatch.setattr(settings,"groww_totp_secret","s")
    h=HealthService(None,Opts(Mode.LIVE,"groww","none","groww"))
    snap=await h.snapshot()
    assert snap["checks"]["openai_key"] is False
    assert snap["live_ready"] is True

@pytest.mark.asyncio
async def test_live_mode_blocked_without_gemini_key(monkeypatch):
    monkeypatch.setattr(settings,"telegram_allowed_user_id",123)
    monkeypatch.setattr(settings,"gemini_api_key","")
    monkeypatch.setattr(settings,"openai_api_key","")
    monkeypatch.setattr(settings,"groww_totp_token","t");monkeypatch.setattr(settings,"groww_totp_secret","s")
    h=HealthService(None,Opts(Mode.LIVE,"groww","none","groww"))
    snap=await h.snapshot()
    assert snap["live_ready"] is False

@pytest.mark.asyncio
async def test_live_mode_blocked_without_groww_credentials(monkeypatch):
    monkeypatch.setattr(settings,"telegram_allowed_user_id",123)
    monkeypatch.setattr(settings,"gemini_api_key","g")
    monkeypatch.setattr(settings,"openai_api_key","")
    monkeypatch.setattr(settings,"groww_totp_token","");monkeypatch.setattr(settings,"groww_totp_secret","")
    monkeypatch.setattr(settings,"groww_api_key","");monkeypatch.setattr(settings,"groww_api_secret","")
    h=HealthService(None,Opts(Mode.LIVE,"groww","none","groww"))
    snap=await h.snapshot()
    assert snap["live_ready"] is False

@pytest.mark.asyncio
async def test_live_mode_blocked_on_mock_market_source(monkeypatch):
    monkeypatch.setattr(settings,"telegram_allowed_user_id",123)
    monkeypatch.setattr(settings,"gemini_api_key","g")
    monkeypatch.setattr(settings,"groww_totp_token","t");monkeypatch.setattr(settings,"groww_totp_secret","s")
    h=HealthService(None,Opts(Mode.LIVE,"mock","none","groww"))
    snap=await h.snapshot()
    assert snap["live_ready"] is False
