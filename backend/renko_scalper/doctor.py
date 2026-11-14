"""`doctor`: verifies, against the LIVE exchange, every assumption the scanner makes about Toobit's API.

The repo was written without being able to reach Toobit, so this is the first thing to run on your server.
"""
from __future__ import annotations

import time
from typing import Callable


def run_doctor(client, cfg, symbol: str = "BTC-SWAP-USDT", notify: bool = False, dispatcher=None) -> list:
    results: list = []

    def check(name: str, fn: Callable) -> None:
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"{type(e).__name__}: {e}"
        results.append((name, bool(ok), detail))

    def clock():
        st = client.server_time()
        if st is None:
            return False, "no serverTime in /api/v1/time response"
        skew = abs(time.time() * 1000 - st) / 1000.0
        return skew < 5, f"clock skew {skew:.1f}s (candle freshness checks need < 5s)"

    def contracts():
        c = client.contracts()
        bad = [s for s, m in c.items() if m.tick <= 0]
        return len(c) > 20 and not bad[:1], f"{len(c)} USDT-M contracts; {len(bad)} without tick size"

    def tickers():
        t = client.tickers_24h()
        live = sum(1 for v in t.values() if v["qv"] > 0)
        return live > 20, f"{len(t)} tickers, {live} with 24h quote volume"

    def books():
        b = client.book_tickers()
        good = sum(1 for bid, ask in b.values() if bid > 0 and ask >= bid)
        return good > 20, f"{len(b)} books, {good} valid bid/ask pairs"

    def klines():
        cs = client.klines(symbol, "1m", 200)
        if len(cs) < 100:
            return False, f"only {len(cs)} candles returned for 200 requested"
        ts = [c.ts for c in cs]
        if ts != sorted(set(ts)):
            return False, "candles not strictly increasing"
        if any(c.h < max(c.o, c.c) or c.l > min(c.o, c.c) for c in cs):
            return False, "OHLC invariants violated (high/low do not bound open/close)"
        zero_v = sum(1 for c in cs if c.v <= 0)
        age = (time.time() * 1000 - cs[-1].ts) / 60_000
        return age < 3 and zero_v < len(cs) * 0.2, f"{len(cs)} candles, last opened {age:.1f} min ago, {zero_v} zero-volume bars"

    def history():
        end = int(time.time() * 1000)
        cs = client.klines(symbol, "1m", 1000, start_ms=end - 2_000 * 60_000, end_ms=end - 1_000 * 60_000)
        return len(cs) > 500, f"historical window returned {len(cs)} candles (backtests need > 500 per page)"

    check("clock sync", clock)
    check("exchangeInfo (contracts, tick/lot filters)", contracts)
    check("24h tickers (liquidity filter)", tickers)
    check("bookTicker (spread filter)", books)
    check(f"klines live ({symbol})", klines)
    check("klines historical window (backtest/validate)", history)
    if notify and dispatcher is not None:
        check("notifications", lambda: (dispatcher.send("Renko Scalper doctor", "Test alert - if you can read this, alerts work.") or True, "sent; confirm it arrived on your phone"))
    return results
