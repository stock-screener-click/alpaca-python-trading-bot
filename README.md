# Build a Daily Trading Bot with the Stock Screener API and Alpaca

This tutorial walks through building a daily-rebalancing trading bot that:

1. Pulls fresh stock picks from the [Stock Screener API](https://rapidapi.com/stock-screener-stock-screener-default/api/stock-screener6) each morning.
2. Routes those picks into [Alpaca's commission-free brokerage](https://docs.alpaca.markets/docs/trading-api) on paper-trading mode.
3. Sells positions that are no longer in the screener and buys equal-weighted positions in new picks.

By the end you'll have a working bot you can schedule to run before market open every day. We use **paper trading** throughout so no real money is at risk.

---

## What You'll Build

```
   Stock Screener API           Alpaca paper-trading
   ┌──────────────────┐          ┌──────────────────┐
   │ /tickers/latest  │  picks   │  GET /v2/account │
   │ /stock-screeners │─────────▶│  GET /v2/positions│
   │   /performance   │          │  POST /v2/orders │
   └──────────────────┘          └──────────────────┘
              ▲                            ▲
              └────── your daily cron ─────┘
```

The bot's daily logic:

1. Fetch the screener's latest picks (e.g. "Quality / Compounder").
2. Fetch your current paper-trading positions.
3. Sell any holding that is no longer in today's picks.
4. Buy the new picks with equal-weight allocation across your portfolio.

---

## Prerequisites

| Tool | Purpose | Cost |
|---|---|---|
| [RapidAPI account](https://rapidapi.com/) with Stock Screener subscription | Source of daily picks | Free tier available |
| [Alpaca account](https://alpaca.markets/) (paper trading enabled) | Brokerage execution | Free |
| Python 3.10 or newer | Runtime | Free |

You'll need three credentials:

- `RAPIDAPI_KEY` - from the RapidAPI dashboard after subscribing.
- `RAPIDAPI_HOST` - shown in your subscription page (e.g. `stock-screener5.p.rapidapi.com`).
- `ALPACA_API_KEY_ID` and `ALPACA_API_SECRET_KEY` - from the Alpaca paper-trading dashboard at https://app.alpaca.markets/paper/dashboard/overview.

Set them as environment variables before running anything below:

```bash
export RAPIDAPI_KEY="..."
export RAPIDAPI_HOST="..."
export ALPACA_API_KEY_ID="..."
export ALPACA_API_SECRET_KEY="..."
```

---

## Step 1: Install Dependencies

```bash
pip install alpaca-py requests
```

`alpaca-py` is the official Python SDK; `requests` we use for the screener calls.

---

## Step 2: Fetch Screener Picks

Create `bot.py` and start with a function to grab the latest picks for one screener.

```python
import os
import requests

RAPIDAPI_KEY = os.environ["RAPIDAPI_KEY"]
RAPIDAPI_HOST = os.environ["RAPIDAPI_HOST"]

SCREENER_HEADERS = {
    "X-RapidAPI-Key": RAPIDAPI_KEY,
    "X-RapidAPI-Host": RAPIDAPI_HOST,
}


def fetch_picks(screener_id: str) -> list[str]:
    """Return today's tickers for a given screener."""
    url = f"https://{RAPIDAPI_HOST}/tickers/latest"
    resp = requests.get(url, headers=SCREENER_HEADERS,
                        params={"screener_id": screener_id}, timeout=15)
    resp.raise_for_status()
    return [row["ticker"] for row in resp.json()]


if __name__ == "__main__":
    picks = fetch_picks("quality-compounder")
    print(f"Today's picks: {picks}")
```

Run it:

```bash
python bot.py
# Today's picks: ['AAPL', 'MSFT', 'GOOG', ...]
```

Browse all available screener IDs at `GET /stock-screeners` or in the [API README](../../RAPIDAPI_README.md).

---

## Step 3: Connect to Alpaca Paper Trading

Add an Alpaca client and confirm it works by printing your buying power.

```python
from alpaca.trading.client import TradingClient

trading_client = TradingClient(
    api_key=os.environ["ALPACA_API_KEY_ID"],
    secret_key=os.environ["ALPACA_API_SECRET_KEY"],
    paper=True,            # set to False once you're ready for real money
)

account = trading_client.get_account()
print(f"Buying power: ${float(account.buying_power):,.2f}")
print(f"Portfolio value: ${float(account.portfolio_value):,.2f}")
```

A fresh paper account starts with $100,000 of simulated buying power.

---

## Step 4: Place Your First Paper Trade

Buy a single share of AAPL to confirm the connection.

```python
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

order = trading_client.submit_order(
    order_data=MarketOrderRequest(
        symbol="AAPL",
        qty=1,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
    )
)
print(f"Submitted order {order.id} for {order.qty} shares of {order.symbol}")
```

If the market is closed, the order queues and fills at the next open. Verify in your [Alpaca dashboard](https://app.alpaca.markets/paper/dashboard/overview).

---

## Step 5: Daily Rebalance from a Screener

Now wire it together. Each morning the bot will:

1. Fetch picks for a chosen screener.
2. Compute equal-weight target allocation.
3. Sell positions no longer in the picks.
4. Buy any new picks using fractional shares (so equal weighting works at any price).

```python
from alpaca.trading.requests import MarketOrderRequest, ClosePositionRequest
from alpaca.trading.enums import OrderSide, TimeInForce


def rebalance(screener_id: str):
    picks = set(fetch_picks(screener_id))
    if not picks:
        print("No picks today, skipping.")
        return

    account = trading_client.get_account()
    portfolio_value = float(account.portfolio_value)
    target_per_position = portfolio_value / len(picks)

    # 1. Close positions that fell out of the screener
    current_positions = {p.symbol: p for p in trading_client.get_all_positions()}
    for symbol, position in current_positions.items():
        if symbol not in picks:
            print(f"SELL {symbol} (no longer in screener)")
            trading_client.close_position(symbol)

    # 2. Buy new picks with notional dollar amounts (fractional shares)
    held = set(current_positions) & picks
    new_picks = picks - held
    for symbol in new_picks:
        print(f"BUY ${target_per_position:,.0f} of {symbol}")
        trading_client.submit_order(
            order_data=MarketOrderRequest(
                symbol=symbol,
                notional=round(target_per_position, 2),
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            )
        )

    print(f"Rebalance complete. Holding {len(picks)} positions.")


if __name__ == "__main__":
    rebalance("quality-compounder")
```

Alpaca supports notional (dollar-amount) orders for fractional shares so you don't have to compute share counts.

---

## Step 6: Pick the Best Performing Screener Automatically

Instead of hard-coding a screener, let the performance endpoint choose the best 1-month performer for you.

```python
def best_screener(window: str = "1m") -> str:
    url = f"https://{RAPIDAPI_HOST}/stock-screeners/performance"
    resp = requests.get(url, headers=SCREENER_HEADERS,
                        params={"window": window}, timeout=15)
    resp.raise_for_status()
    screeners = resp.json()["screeners"]
    # Already sorted by avg_return_pct desc
    top = next(s for s in screeners if s.get("avg_return_pct") is not None)
    print(f"Best {window} screener: {top['short_name']} "
          f"({top['avg_return_pct']:.2f}%)")
    return top["screener_id"]


if __name__ == "__main__":
    rebalance(best_screener("1m"))
```

This rotates strategies based on what's actually been working. Be careful: chasing recent performance is its own well-known failure mode. Consider longer windows (`3m`, `6m`) or blending several screeners.

---

## Step 7: Schedule the Bot

Run the rebalance once per trading day, after market open so prices are live.

### Option A: Local cron (Linux / macOS)

```bash
crontab -e
# 35 9 * * 1-5 cd /path/to/bot && /usr/bin/python3 bot.py >> bot.log 2>&1
```

That fires at 9:35 AM local time, Monday through Friday.

### Option B: GitHub Actions

Create `.github/workflows/trade.yml`:

```yaml
name: Daily rebalance
on:
  schedule:
    - cron: "35 13 * * 1-5"   # 9:35 AM ET
  workflow_dispatch:

jobs:
  trade:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install alpaca-py requests
      - run: python bot.py
        env:
          RAPIDAPI_KEY: ${{ secrets.RAPIDAPI_KEY }}
          RAPIDAPI_HOST: ${{ secrets.RAPIDAPI_HOST }}
          ALPACA_API_KEY_ID: ${{ secrets.ALPACA_API_KEY_ID }}
          ALPACA_API_SECRET_KEY: ${{ secrets.ALPACA_API_SECRET_KEY }}
```

Add the four secrets in your repo's Settings -> Secrets and Variables -> Actions.

### Option C: AWS Lambda + EventBridge

Same idea as the screener API itself in this repo. Package the script as a Lambda, schedule via EventBridge with `cron(35 13 ? * MON-FRI *)`.

---

## Safeguards Before Going Live

Paper trading is forgiving. Real money is not. Before flipping `paper=False`:

- **Position cap**: refuse to trade if `len(picks) > MAX_POSITIONS` to avoid over-diversifying into illiquid names.
- **Min price filter**: skip tickers under $5 to avoid penny-stock spreads.
- **Max trade size as % of ADV**: don't submit orders larger than 1% of average daily volume.
- **Pre-trade balance check**: bail if `buying_power < portfolio_value * 0.95` (something is off).
- **Kill switch**: keep an `if os.environ.get("BOT_DISABLED"): return` early-exit so you can pause via env var.
- **Logging**: write every order to a file or database so you can reconcile against Alpaca's history.
- **Start small**: when you do go live, fund the account with a small amount and watch a full week of behavior.

---

## Full Script

```python
"""Daily screener-driven rebalancing bot for Alpaca paper trading."""

import os
import requests
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

RAPIDAPI_KEY = os.environ["RAPIDAPI_KEY"]
RAPIDAPI_HOST = os.environ["RAPIDAPI_HOST"]
SCREENER_HEADERS = {
    "X-RapidAPI-Key": RAPIDAPI_KEY,
    "X-RapidAPI-Host": RAPIDAPI_HOST,
}

trading_client = TradingClient(
    api_key=os.environ["ALPACA_API_KEY_ID"],
    secret_key=os.environ["ALPACA_API_SECRET_KEY"],
    paper=True,
)


def fetch_picks(screener_id: str) -> list[str]:
    url = f"https://{RAPIDAPI_HOST}/tickers/latest"
    resp = requests.get(url, headers=SCREENER_HEADERS,
                        params={"screener_id": screener_id}, timeout=15)
    resp.raise_for_status()
    return [row["ticker"] for row in resp.json()]


def best_screener(window: str = "1m") -> str:
    url = f"https://{RAPIDAPI_HOST}/stock-screeners/performance"
    resp = requests.get(url, headers=SCREENER_HEADERS,
                        params={"window": window}, timeout=15)
    resp.raise_for_status()
    screeners = resp.json()["screeners"]
    top = next(s for s in screeners if s.get("avg_return_pct") is not None)
    print(f"Best {window} screener: {top['short_name']} ({top['avg_return_pct']:.2f}%)")
    return top["screener_id"]


def rebalance(screener_id: str):
    picks = set(fetch_picks(screener_id))
    if not picks:
        print("No picks today, skipping.")
        return

    account = trading_client.get_account()
    target_per_position = float(account.portfolio_value) / len(picks)

    current_positions = {p.symbol: p for p in trading_client.get_all_positions()}
    for symbol in current_positions:
        if symbol not in picks:
            print(f"SELL {symbol}")
            trading_client.close_position(symbol)

    new_picks = picks - set(current_positions)
    for symbol in new_picks:
        print(f"BUY ${target_per_position:,.0f} of {symbol}")
        trading_client.submit_order(
            order_data=MarketOrderRequest(
                symbol=symbol,
                notional=round(target_per_position, 2),
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            )
        )

    print(f"Rebalance complete. Holding {len(picks)} positions.")


if __name__ == "__main__":
    rebalance(best_screener("1m"))
```

---

## Where to Go Next

- **Multi-screener portfolios**: blend 3-4 screeners with their own weight allocations rather than picking one winner.
- **Stop-loss orders**: instead of `MarketOrderRequest`, use `LimitOrderRequest` with bracket orders to set a stop loss and take profit on entry.
- **Performance tracking**: log every rebalance and compare your bot's actual returns against the screener's `avg_return_pct` from the API. Are you matching, beating, or trailing the equal-weight benchmark?
- **Drift management**: rebalance only when allocations drift more than 5% from target instead of every day, to reduce churn.
- **Live trading**: when ready, switch `paper=True` to `paper=False` and update the API endpoint - and make sure every safeguard above is in place first.

---

## Resources

- Stock Screener API reference: [RAPIDAPI_README.md](../../RAPIDAPI_README.md)
- Alpaca Trading API docs: https://docs.alpaca.markets/docs/trading-api
- Alpaca Python SDK: https://github.com/alpacahq/alpaca-py
- Alpaca paper-trading dashboard: https://app.alpaca.markets/paper/dashboard/overview

---

## Disclaimer

This tutorial is for educational purposes only. It is not investment advice. Past performance of any screener does not guarantee future results. Always test thoroughly in paper mode and understand the strategy before risking real capital.
