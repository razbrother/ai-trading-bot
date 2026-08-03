from app.broker import PaperBroker
from app.models import Mode
from app.runtime import RuntimeOptions, build_sources


def test_mock_paper_sources_do_not_require_groww():
    opts = RuntimeOptions(
        mode=Mode.PAPER,
        market_source="mock",
        news_source="none",
        history_source="none",
    )
    market, news, history = build_sources(opts, PaperBroker())
    assert market is not None
    assert news is not None
    assert history is not None
