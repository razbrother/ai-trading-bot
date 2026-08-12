"""Build a curated SYMBOLS list of liquid, affordable NSE stocks from Groww's
own instrument master and live quotes - never guesses exchange tokens.

Usage:
    python scripts/build_symbol_universe.py [--max-price 1500] [--count 45]

Prints a ready-to-paste SYMBOLS=... line. Requires live Groww credentials
(same as scripts/groww_live_probe.py) since it needs real quotes to filter
by price and rank by volume.
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.settings import settings
from app.broker import GrowwBroker
from app import groww_limits

# Well-known, actively-traded NSE large/mid-cap names. This is a starting
# candidate pool, not a source of truth - every symbol here still gets its
# exchange_token resolved from Groww's own instrument master below, and any
# name not found there (wrong symbol, delisted, not intraday-tradeable) is
# dropped rather than guessed.
CANDIDATES = [
    "ITC","TATASTEEL","TATAPOWER","ONGC","NTPC","COALINDIA","HINDALCO","VEDL",
    "IDFCFIRSTB","BANKBARODA","PNB","CANBK","IOC","GAIL","BHEL","SAIL","NMDC",
    "ZOMATO","PAYTM","IRCTC","BEL","IRFC","RVNL","YESBANK","IDEA","SUZLON",
    "NATIONALUM","ASHOKLEY","MOTHERSON","GMRINFRA","RECLTD","PFC","LICHSGFIN",
    "UNIONBANK","FEDERALBNK","AUBANK","TATAMOTORS","ADANIPOWER","APOLLOTYRE",
    "BATAINDIA","VOLTAS","HDFCLIFE","DLF","OBEROIRLTY","JSWENERGY","TRENT",
    "PETRONET","INDIANB","MARICO","COLPAL","GODREJCP","BERGEPAINT","ESCORTS",
    "BHARTIARTL","POWERGRID","HEROMOTOCO","CIPLA","DRREDDY","SUNPHARMA",
    "WIPRO","HCLTECH","LTIM","BAJFINANCE","BAJAJFINSV","TITAN","ADANIENT",
    "ADANIPORTS","AMBUJACEM","ACC","GRASIM","UPL","EICHERMOT","BPCL","HDFCAMC",
    "RELIANCE","TCS","INFY","SBIN","ICICIBANK",
]

def args():
    p = argparse.ArgumentParser()
    p.add_argument("--max-price", type=float, default=1500)
    p.add_argument("--count", type=int, default=45)
    return p.parse_args()

async def main():
    opts = args()
    settings.validate_live()
    broker = GrowwBroker()
    g = broker.g

    df = g.get_all_instruments()
    eq = df[(df["exchange"] == "NSE") & (df["segment"] == "CASH") &
            (df["series"] == "EQ") & (df["is_intraday"] == "1") &
            (df["buy_allowed"] == "1")]
    tokens = dict(zip(eq["trading_symbol"], eq["exchange_token"]))

    results = []
    for sym in CANDIDATES:
        token = tokens.get(sym)
        if token is None:
            print(f"SKIP {sym}: not found in NSE EQ intraday-tradeable instrument master")
            continue
        try:
            def call(s=sym):
                return g.get_quote(exchange=g.EXCHANGE_NSE, segment=g.SEGMENT_CASH, trading_symbol=s)
            q = await groww_limits.call(groww_limits.live, call)
        except Exception as e:
            print(f"SKIP {sym}: quote failed {type(e).__name__} {str(e)[:120]}")
            continue
        ltp = q.get("last_price")
        volume = q.get("volume") or 0
        if ltp is None or ltp <= 0 or ltp >= opts.max_price:
            continue
        results.append({"symbol": sym, "token": token, "ltp": ltp, "volume": volume})
        print(f"OK {sym}: token={token} ltp={ltp} volume={volume}")

    results.sort(key=lambda r: -r["volume"])
    top = results[:opts.count]
    print(f"\n--- top {len(top)} by volume (price < {opts.max_price}) ---")
    for r in top:
        print(r)
    print("\n--- SYMBOLS ---")
    print(",".join(f'{r["symbol"]}:{r["token"]}' for r in top))

if __name__ == "__main__":
    asyncio.run(main())
