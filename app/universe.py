"""Build a curated SYMBOLS list of liquid, affordable NSE stocks from Groww's
own instrument master and live quotes - never guesses exchange tokens.

Shared by scripts/build_symbol_universe.py (manual, one-off CLI use) and the
scheduled daily refresh in app/main.py (DAILY_UNIVERSE_SCAN_ENABLED=true).
"""
from app import groww_limits

# Well-known, actively-traded NSE large/mid-cap names. This is a starting
# candidate pool, not a source of truth - every symbol here still gets its
# exchange_token resolved from Groww's own instrument master, and any name
# not found there (wrong symbol, delisted, not intraday-tradeable) is
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

async def scan(api, max_price=1500, count=45, candidates=CANDIDATES):
    """Returns (symbols_string, report_lines). symbols_string is None if
    nothing qualified (caller should keep the existing SYMBOLS unchanged)."""
    df = api.get_all_instruments()
    eq = df[(df["exchange"] == "NSE") & (df["segment"] == "CASH") &
            (df["series"] == "EQ") & (df["is_intraday"] == "1") &
            (df["buy_allowed"] == "1")]
    tokens = dict(zip(eq["trading_symbol"], eq["exchange_token"]))

    results = []
    report = []
    for sym in candidates:
        token = tokens.get(sym)
        if token is None:
            report.append(f"SKIP {sym}: not in NSE EQ intraday-tradeable instrument master")
            continue
        try:
            def call(s=sym):
                return api.get_quote(exchange=api.EXCHANGE_NSE, segment=api.SEGMENT_CASH, trading_symbol=s)
            q = await groww_limits.call(groww_limits.live, call)
        except Exception as e:
            report.append(f"SKIP {sym}: quote failed {type(e).__name__} {str(e)[:120]}")
            continue
        ltp = q.get("last_price")
        volume = q.get("volume") or 0
        if ltp is None or ltp <= 0 or ltp >= max_price:
            continue
        results.append({"symbol": sym, "token": token, "ltp": ltp, "volume": volume})
        report.append(f"OK {sym}: token={token} ltp={ltp} volume={volume}")

    results.sort(key=lambda r: -r["volume"])
    top = results[:count]
    if not top:
        return None, report
    return ",".join(f'{r["symbol"]}:{r["token"]}' for r in top), report
