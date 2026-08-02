# AI Trading Bot

A paper-first Telegram-controlled AI trading framework using Gemini, OpenAI and a Groww adapter.

## Important

The delivered build defaults to `PAPER` and uses a simulated market feed. The Groww live adapter deliberately blocks live position reconciliation and exits until those account-specific SDK responses are verified. Therefore **this package cannot accidentally become an unattended live bot by changing one flag**.

## Setup

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/doctor.py
python -m app.main
```

Send `/whoami`, add the number to `TELEGRAM_ALLOWED_USER_ID`, restart, then use `/start_auto`.

## Flow

```text
Configured universe
 -> simulated/verified market snapshots
 -> deterministic technical score
 -> Gemini structured proposal
 -> OpenAI structured critique
 -> consensus
 -> hard risk validation
 -> quantity calculation
 -> paper broker
 -> status verification
 -> position monitoring
 -> SL/target/force exit
 -> exit verification
 -> reconciliation
 -> SQLite audit and performance report
 -> Telegram alerts
```

## Hard controls

AI cannot change capital, quantity, risk per trade, daily loss, trade count, trading window, universe, live unlock or emergency state.

## Live integration checklist

1. Replace `MockMarket` with a GrowwFeed/historical-candle provider.
2. Verify instrument exchange tokens from Groww's current instrument CSV.
3. Map the installed Groww SDK's current order-detail and positions responses.
4. Implement and test MIS exit/reconciliation with one-share controlled tests.
5. Paper trade at least 30 market days and preferably 150+ completed trades.
6. Include real charges and slippage in evaluation.
7. Keep broker-side protection wherever supported.
8. Enable live only after code review and recovery drills.


## Dual-AI policy

Gemini and OpenAI independently choose BUY, SELL or HOLD, plus entry, stop, target and confidence. A trade is eligible only when symbol/action match, both confidence scores pass, agreement score is at least 85/100, entry difference is <=0.20% of verified LTP, stop difference is <=0.30 ATR, target difference is <=0.50 ATR, and deterministic risk validation passes.

The first trade of each day requires both model scores >=0.85. Later trades start at >=0.80. These are bootstrap thresholds, not proven probabilities; recalibrate them after sufficient paper trades.


## Mode and source arguments

Paper mode with simulated prices:

```bash
python -m app.main --mode paper --market-source mock --news-source none --history-source none
```

Paper execution using real Groww market/history data:

```bash
python -m app.main --mode paper --market-source groww --news-source json --history-source groww
```

Live mode:

```bash
python -m app.main --mode live --market-source groww --news-source json --history-source groww
```

Live mode is rejected when `--market-source mock` is supplied.

## Data coverage status

- Live Groww quote adapter: framework included; live indicators must be computed from verified completed candles.
- Historical Groww adapter: framework included using `get_historical_candles`; verify the installed SDK signature.
- Own previous trades: stored in SQLite and available for reporting.
- Similar-setup retrieval/ML probability: not yet implemented.
- News: no broker news API is assumed. A verified JSON ingestion interface is included. LLMs are not allowed to invent news.
- Fake-data analyzer: flags mock/test sources, inconsistent day range, crossed bid/ask, and invalid indicators.


## Production candidate
Both models independently select from top candidates. Telegram supports status/settings/health/watchlist. Own trade evidence is supplied but is not treated as probability. Live order exits/positions remain intentionally blocked until account-level Groww integration tests are completed.


## Groww live verification layer

Implemented against the official SDK methods:

- place order
- status by Groww order ID
- status by reference ID
- executed-trade list
- cancel order
- cash positions
- available and required margin
- MIS market exit
- SL and SL-M protective orders

Use the read-only probe first:

```bash
python scripts/groww_live_probe.py
```

It reads margin, positions and a quote; it does not place an order.

The live quantity cap defaults to one share. Keep the production strategy disabled until
the read-only probe and controlled one-share lifecycle tests match the Groww app.

## Free news provider

Use GDELT:

```bash
python -m app.main --mode paper --market-source groww --news-source gdelt --history-source groww
```

GDELT requests are cached for 5 minutes per symbol and spaced by at least 10 seconds.
Recommended Groww internal targets: orders 2/s and 30/min; live REST 6/s and 180/min;
non-trading 8/s and 300/min.
