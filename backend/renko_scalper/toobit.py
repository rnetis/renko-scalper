"""Minimal read-only Toobit USDT-M futures market-data client (public endpoints, no API key).

Endpoints (per api-docs.toobit.com, USDT-M market data):
  GET /api/v1/exchangeInfo                    contracts[]: symbol, status, inverse, filters
  GET /quote/v1/contract/ticker/24hr          all symbols (weight 40): s, c, qv, pcp
  GET /quote/v1/contract/ticker/bookTicker    all symbols: s, b, a
  GET /quote/v1/klines                        [openTime, o, h, l, c, vol, _, quoteVol, ...]
Futures symbols look like BTC-SWAP-USDT.
"""
from __future__ import annotations

import time
from typing import Optional

import requests

from .config import INTERVAL_MS
from .models import Candle, MarketInfo


def _f(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


class ToobitClient:
    RETRY_STATUS = (429, 500, 502, 503, 504)

    def __init__(self, base_url: str = "https://api.toobit.com", proxy: Optional[str] = None, timeout: float = 10.0,
                 retries: int = 2):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "renko-scalper/1.0"
        if proxy:
            self.s.proxies = {"http": proxy, "https": proxy}

    def _get(self, path: str, params: Optional[dict] = None):
        """GET with retry/backoff on 429/5xx/timeouts (honours Retry-After). Raises the last error."""
        last: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            delay = 0.5 * 2 ** attempt
            try:
                r = self.s.get(self.base + path, params=params, timeout=self.timeout)
                if r.status_code in self.RETRY_STATUS and attempt < self.retries:
                    ra = r.headers.get("Retry-After", "")
                    delay = float(ra) if ra.replace(".", "", 1).isdigit() else delay
                    last = requests.HTTPError(f"{r.status_code} from {path}", response=r)
                else:
                    r.raise_for_status()
                    return r.json()
            except (requests.ConnectionError, requests.Timeout) as e:
                last = e
                if attempt >= self.retries:
                    raise
            time.sleep(min(delay, 10.0))
        raise last  # pragma: no cover

    def server_time(self) -> Optional[int]:
        data = self._get("/api/v1/time")
        v = data.get("serverTime") if isinstance(data, dict) else None
        return int(v) if v else None

    # ------------------------------------------------------------------ metadata
    def contracts(self) -> dict:
        """Linear USDT-M contracts that are currently tradable -> MarketInfo (tick/step/min filters)."""
        data = self._get("/api/v1/exchangeInfo")
        out: dict = {}
        for c in data.get("contracts", []):
            sym = c.get("symbol", "")
            if not sym.endswith("-SWAP-USDT") or c.get("inverse") or c.get("status") != "TRADING":
                continue
            m = MarketInfo(symbol=sym)
            for f in c.get("filters", []):
                ft = f.get("filterType")
                if ft == "PRICE_FILTER":
                    m.tick = _f(f.get("tickSize"))
                elif ft == "LOT_SIZE":
                    m.step = _f(f.get("stepSize"))
                    m.min_qty = _f(f.get("minQty"))
                elif ft == "MIN_NOTIONAL":
                    m.min_notional = _f(f.get("minNotional"))
            out[sym] = m
        return out

    def tickers_24h(self) -> dict:
        data = self._get("/quote/v1/contract/ticker/24hr")
        if isinstance(data, dict):
            data = data.get("data", [data])
        return {t["s"]: {"qv": _f(t.get("qv")), "last": _f(t.get("c")), "pcp": _f(t.get("pcp"))}
                for t in data if isinstance(t, dict) and "s" in t}

    def book_tickers(self) -> dict:
        data = self._get("/quote/v1/contract/ticker/bookTicker")
        if isinstance(data, dict):
            data = data.get("data", [data])
        return {t["s"]: (_f(t.get("b")), _f(t.get("a"))) for t in data if isinstance(t, dict) and "s" in t}

    # ------------------------------------------------------------------ candles
    def klines(self, symbol: str, interval: str, limit: int = 600,
               start_ms: Optional[int] = None, end_ms: Optional[int] = None) -> list:
        """Latest `limit` candles (oldest first). Docs: without startTime/endTime only the latest bar is
        returned, so a window is always sent."""
        ms = INTERVAL_MS[interval]
        end = end_ms if end_ms is not None else int(time.time() * 1000)
        start = start_ms if start_ms is not None else end - limit * ms
        params = {"symbol": symbol, "interval": interval, "startTime": start, "endTime": end,
                  "limit": min(limit, 1000)}
        try:
            rows = self._get("/quote/v1/klines", params)
        except requests.HTTPError as e:
            # some Toobit kline endpoints name the window from/to instead of startTime/endTime
            if getattr(e.response, "status_code", 0) != 400:
                raise
            alt = {k: v for k, v in params.items() if k not in ("startTime", "endTime")}
            alt.update({"from": start, "to": end})
            rows = self._get("/quote/v1/klines", alt)
        return parse_klines(rows)


def parse_klines(rows) -> list:
    out: dict = {}
    for r in rows or []:
        if isinstance(r, (list, tuple)) and len(r) >= 6:
            ts, o, h, l, c, v = r[0], r[1], r[2], r[3], r[4], r[5]
        elif isinstance(r, dict):
            ts = r.get("t") or r.get("openTime")
            o, h, l, c, v = r.get("o"), r.get("h"), r.get("l"), r.get("c"), r.get("v")
        else:
            continue
        cd = Candle(int(ts), _f(o), _f(h), _f(l), _f(c), _f(v))
        if cd.c > 0:
            out[cd.ts] = cd
    return [out[k] for k in sorted(out)]


def closed_only(candles: list, interval_ms: int, now_ms: Optional[int] = None) -> list:
    """Drop the still-forming last candle."""
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    return [c for c in candles if c.ts + interval_ms <= now_ms]
