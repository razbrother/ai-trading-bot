from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field
from app.settings import settings

class DataProvenance(BaseModel):
    source: str
    observed_at: datetime
    is_simulated: bool = False
    is_verified: bool = False
    details: str = ""

    def age_seconds(self) -> float:
        now = datetime.now(settings.tz)
        return max(0.0, (now - self.observed_at.astimezone(settings.tz)).total_seconds())

class NewsItem(BaseModel):
    symbol: str
    headline: str
    published_at: datetime
    source_name: str
    source_url: str | None = None
    sentiment: str = "UNKNOWN"
    relevance: float = Field(default=0, ge=0, le=1)

class NewsContext(BaseModel):
    items: list[NewsItem] = []
    risk: str = "UNKNOWN"
    provenance: DataProvenance

class HistoricalContext(BaseModel):
    symbol: str
    candle_count: int = 0
    similar_setup_count: int = 0
    observed_win_rate: float | None = None
    average_net_return: float | None = None
    provenance: DataProvenance
