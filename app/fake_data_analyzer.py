from app.models import Snapshot

SUSPICIOUS_SOURCES = {"MOCK", "FAKE", "SIMULATED", "TEST", "UNKNOWN"}

def analyze_snapshot(snapshot: Snapshot) -> list[str]:
    errors = []
    if snapshot.source.upper() in SUSPICIOUS_SOURCES:
        errors.append(f"NON_LIVE_SOURCE:{snapshot.source}")
    if not (snapshot.low <= snapshot.ltp <= snapshot.high):
        errors.append("LTP_OUTSIDE_DAY_RANGE")
    if snapshot.bid and snapshot.ask and snapshot.bid > snapshot.ask:
        errors.append("CROSSED_BOOK")
    if snapshot.volume_ratio < 0:
        errors.append("NEGATIVE_VOLUME_RATIO")
    if snapshot.atr <= 0:
        errors.append("NON_POSITIVE_ATR")
    if snapshot.ema9 <= 0 or snapshot.ema21 <= 0 or snapshot.vwap <= 0:
        errors.append("INVALID_INDICATOR")
    return errors
