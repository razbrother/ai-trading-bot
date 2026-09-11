"""Build a curated SYMBOLS list of liquid, affordable NSE stocks from Groww's
own instrument master and live quotes - never guesses exchange tokens.

Usage:
    python scripts/build_symbol_universe.py [--max-price 1500] [--count 45]

Prints a ready-to-paste SYMBOLS=... line. Requires live Groww credentials
(same as scripts/groww_live_probe.py) since it needs real quotes to filter
by price and rank by volume.

The scanning/scoring logic lives in app/universe.py, shared with the bot's
own scheduled daily refresh (DAILY_UNIVERSE_SCAN_ENABLED=true in .env).
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.settings import settings
from app.broker import GrowwBroker
from app.universe import scan

def args():
    p = argparse.ArgumentParser()
    p.add_argument("--max-price", type=float, default=1500)
    p.add_argument("--count", type=int, default=45)
    return p.parse_args()

async def main():
    opts = args()
    settings.validate_live()
    broker = GrowwBroker()

    symbols, report = await scan(broker.g, max_price=opts.max_price, count=opts.count)
    for line in report:
        print(line)
    if symbols is None:
        print("\nNo candidates qualified - keeping existing SYMBOLS unchanged.")
        return
    print(f"\n--- SYMBOLS (price < {opts.max_price}, top {opts.count} by volume) ---")
    print(symbols)

if __name__ == "__main__":
    asyncio.run(main())
