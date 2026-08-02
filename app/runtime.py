from dataclasses import dataclass
from app.models import Mode
from app.settings import settings
from app.market import MockMarket
from app.groww_market import GrowwMarket
from app.news import NoNewsProvider, JsonNewsProvider
from app.gdelt_news import GDELTNewsProvider
from app.history import NoHistoryProvider, GrowwHistoryProvider
from app.data_policy import validate_runtime_sources

@dataclass
class RuntimeOptions:
    mode: Mode
    market_source: str
    news_source: str
    history_source: str

def build_sources(opts: RuntimeOptions, broker):
    validate_runtime_sources(opts.mode,opts.market_source,opts.news_source,opts.history_source)
    if opts.market_source=="mock":
        market=MockMarket()
    elif opts.market_source=="groww":
        if not hasattr(broker,"g"): raise RuntimeError("Groww market source requires authenticated Groww broker/API")
        market=GrowwMarket(broker.g)
    else: raise RuntimeError(f"Unsupported market source: {opts.market_source}")

    if opts.news_source=="none":news=NoNewsProvider()
    elif opts.news_source=="json":news=JsonNewsProvider()
    elif opts.news_source=="gdelt":news=GDELTNewsProvider()
    else:raise RuntimeError(f"Unsupported news source: {opts.news_source}")
    if opts.history_source=="none": history=NoHistoryProvider()
    elif opts.history_source=="groww":
        if not hasattr(broker,"g"): raise RuntimeError("Groww history requires authenticated Groww API")
        history=GrowwHistoryProvider(broker.g)
    else: raise RuntimeError(f"Unsupported history source: {opts.history_source}")
    return market,news,history
