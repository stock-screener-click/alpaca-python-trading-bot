"""Daily screener-driven rebalancing bot for Alpaca paper trading.

Reads today's picks from the Stock Screener API and rebalances an Alpaca
paper-trading account to hold an equal-weight basket of those picks.

See README.md for setup, scheduling, and safeguards.
"""

import os

import requests
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

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
    """Return today's tickers for a given screener."""
    url = f"https://{RAPIDAPI_HOST}/tickers/latest"
    resp = requests.get(
        url,
        headers=SCREENER_HEADERS,
        params={"screener_id": screener_id},
        timeout=15,
    )
    resp.raise_for_status()
    return [row["ticker"] for row in resp.json()]


def best_screener(window: str = "1m") -> str:
    """Return the screener_id with the best avg_return_pct over `window`."""
    url = f"https://{RAPIDAPI_HOST}/stock-screeners/performance"
    resp = requests.get(
        url,
        headers=SCREENER_HEADERS,
        params={"window": window},
        timeout=15,
    )
    resp.raise_for_status()
    screeners = resp.json()["screeners"]
    top = next(s for s in screeners if s.get("avg_return_pct") is not None)
    print(
        f"Best {window} screener: {top['short_name']} "
        f"({top['avg_return_pct']:.2f}%)"
    )
    return top["screener_id"]


def rebalance(screener_id: str) -> None:
    """Hold an equal-weight basket of today's picks for `screener_id`."""
    picks = set(fetch_picks(screener_id))
    if not picks:
        print("No picks today, skipping.")
        return

    account = trading_client.get_account()
    target_per_position = float(account.portfolio_value) / len(picks)

    current_positions = {p.symbol: p for p in trading_client.get_all_positions()}
    for symbol in current_positions:
        if symbol not in picks:
            print(f"SELL {symbol} (no longer in screener)")
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
    if os.environ.get("BOT_DISABLED"):
        print("BOT_DISABLED is set, exiting.")
        raise SystemExit(0)
    rebalance(best_screener("1m"))
