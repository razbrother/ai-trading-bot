"""Read-only technical-score report across the full candidate universe, real
Groww data, zero AI calls (immune to the Gemini quota issue). Shows exactly
what would be eligible for AI consideration right now, honestly.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.settings import settings
from app.broker import GrowwBroker
from app.groww_market import GrowwMarket
from app.market import score
from app.universe import CANDIDATES

async def main():
    broker = GrowwBroker()
    market = GrowwMarket(broker.g)
    df = broker.g.get_all_instruments()
    eq = df[(df["exchange"] == "NSE") & (df["segment"] == "CASH") &
            (df["series"] == "EQ") & (df["is_intraday"] == "1") &
            (df["buy_allowed"] == "1")]
    tokens = dict(zip(eq["trading_symbol"], eq["exchange_token"]))

    from app.models import Instrument
    results = []
    skipped = []
    for sym in CANDIDATES:
        token = tokens.get(sym)
        if token is None:
            skipped.append(f"{sym}: not NSE intraday-eligible")
            continue
        try:
            snap = await market.snapshot(Instrument(symbol=sym, exchange_token=str(token)))
            c = score(snap)
            results.append((c.score, sym, snap.ltp, c.reasons))
        except Exception as e:
            skipped.append(f"{sym}: {type(e).__name__} {str(e)[:100]}")

    results.sort(key=lambda r: -r[0])
    print(f"Scored {len(results)}/{len(CANDIDATES)} candidates ({len(skipped)} skipped)")
    print(f"Threshold: min_technical_score={settings.min_technical_score}")
    print()
    passing = [r for r in results if r[0] >= settings.min_technical_score]
    print(f"=== {len(passing)} currently clear the technical bar ===")
    for sc, sym, ltp, reasons in passing:
        print(f"  {sym}: score={sc} ltp={ltp} reasons={reasons}")
    print()
    print("=== top 15 overall (for context) ===")
    for sc, sym, ltp, reasons in results[:15]:
        print(f"  {sym}: score={sc} ltp={ltp} reasons={reasons}")
    if skipped:
        print()
        print(f"=== {len(skipped)} skipped ===")
        for s in skipped[:20]:
            print(" ", s)

if __name__ == "__main__":
    asyncio.run(main())
