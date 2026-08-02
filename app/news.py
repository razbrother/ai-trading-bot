from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from app.settings import settings
from app.context_data import DataProvenance, NewsContext, NewsItem

class NoNewsProvider:
    async def get(self, symbol: str) -> NewsContext:
        return NewsContext(items=[], risk="UNKNOWN", provenance=DataProvenance(
            source="none", observed_at=datetime.now(settings.tz),
            is_simulated=False, is_verified=False, details="No news provider configured"))

class JsonNewsProvider:
    """Reads news collected by a separate verified ingestion process.
    This avoids allowing an LLM to invent or browse news inside the execution loop.
    """
    def __init__(self, path="data/news.json"): self.path=Path(path)
    async def get(self, symbol: str) -> NewsContext:
        if not self.path.exists():
            return NewsContext(items=[], risk="UNKNOWN", provenance=DataProvenance(
                source="json-file", observed_at=datetime.now(settings.tz), is_verified=False,
                details="News file missing"))
        raw=json.loads(self.path.read_text())
        items=[NewsItem.model_validate(x) for x in raw.get("items",[]) if x.get("symbol")==symbol]
        observed=datetime.fromisoformat(raw["observed_at"])
        return NewsContext(items=items,risk=raw.get("risk_by_symbol",{}).get(symbol,"UNKNOWN"),
          provenance=DataProvenance(source=raw.get("source","json-file"),observed_at=observed,
          is_verified=bool(raw.get("verified",False)),details=raw.get("details","")))
