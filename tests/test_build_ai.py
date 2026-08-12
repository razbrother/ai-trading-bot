from app.main import build_ai
from app.ai import GeminiAI, HeuristicAI, OpenAITrader
from app.settings import settings

def test_both_keys_use_distinct_real_providers(monkeypatch):
    monkeypatch.setattr(settings,"gemini_api_key","g")
    monkeypatch.setattr(settings,"openai_api_key","o")
    ai=build_ai()
    assert isinstance(ai.g,GeminiAI) and isinstance(ai.o,OpenAITrader)

def test_gemini_only_falls_back_to_gemini_on_both_sides(monkeypatch,caplog):
    monkeypatch.setattr(settings,"gemini_api_key","g")
    monkeypatch.setattr(settings,"openai_api_key","")
    ai=build_ai()
    assert isinstance(ai.g,GeminiAI) and isinstance(ai.o,GeminiAI)
    assert ai.g is not ai.o

def test_no_keys_uses_heuristic_both_sides(monkeypatch):
    monkeypatch.setattr(settings,"gemini_api_key","")
    monkeypatch.setattr(settings,"openai_api_key","")
    ai=build_ai()
    assert isinstance(ai.g,HeuristicAI) and isinstance(ai.o,HeuristicAI)

def test_openai_only_uses_heuristic_gemini_and_real_openai(monkeypatch):
    monkeypatch.setattr(settings,"gemini_api_key","")
    monkeypatch.setattr(settings,"openai_api_key","o")
    ai=build_ai()
    assert isinstance(ai.g,HeuristicAI) and isinstance(ai.o,OpenAITrader)
