from __future__ import annotations

from typing import Optional, Sequence

from .models import Candle


def atr(candles: Sequence[Candle], n: int = 14) -> float:
    """Wilder ATR of the whole series; 0.0 when there is not enough data."""
    if len(candles) < n + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        c, p = candles[i], candles[i - 1]
        trs.append(max(c.h - c.l, abs(c.h - p.c), abs(c.l - p.c)))
    a = sum(trs[:n]) / n
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
    return a


def _sma(vals: list, n: int) -> list:
    out: list = [None] * len(vals)
    for i in range(len(vals)):
        if i < n - 1:
            continue
        win = vals[i - n + 1 : i + 1]
        if any(v is None for v in win):
            continue
        out[i] = sum(win) / n
    return out


def stochastic(candles: Sequence[Candle], k: int = 14, smooth: int = 3, d: int = 3):
    """Slow stochastic. Returns (fast_line, slow_line) aligned to candles (None = undefined)."""
    raw: list = [None] * len(candles)
    for i in range(k - 1, len(candles)):
        win = candles[i - k + 1 : i + 1]
        hh = max(c.h for c in win)
        ll = min(c.l for c in win)
        raw[i] = 100.0 * (candles[i].c - ll) / (hh - ll) if hh > ll else 50.0
    fast = _sma(raw, smooth)
    slow = _sma(fast, d)
    return fast, slow


def momentum(candles: Sequence[Candle], ob: float = 75.0, os_: float = 25.0, scan: int = 6) -> Optional[dict]:
    """Miner-style momentum state: direction (fast vs slow line), OB/OS zone and the latest reversal.

    A momentum *reversal* is a fast/slow line cross. `rev_dir` is +1 (bullish cross),
    -1 (bearish cross) or 0 if none within the last `scan` bars; `rev_age` counts bars back.
    """
    fast, slow = stochastic(candles)
    n = len(candles)
    if n < 25 or fast[-1] is None or slow[-1] is None:
        return None
    k, dd = fast[-1], slow[-1]
    rev_dir, rev_age, rev_in_ob, rev_in_os = 0, None, False, False
    for back in range(0, scan):
        i = n - 1 - back
        if i < 1 or fast[i] is None or slow[i] is None or fast[i - 1] is None or slow[i - 1] is None:
            break
        if fast[i - 1] <= slow[i - 1] and fast[i] > slow[i]:
            rev_dir, rev_age = 1, back
            rev_in_ob = max(fast[i], slow[i]) >= ob
            break
        if fast[i - 1] >= slow[i - 1] and fast[i] < slow[i]:
            rev_dir, rev_age = -1, back
            rev_in_os = min(fast[i], slow[i]) <= os_
            break
    return {
        "k": k,
        "d": dd,
        "bull": k > dd,
        "ob": k >= ob and dd >= ob,
        "os": k <= os_ and dd <= os_,
        "rev_dir": rev_dir,
        "rev_age": rev_age,
        "rev_in_ob": rev_in_ob,
        "rev_in_os": rev_in_os,
    }


def resample(candles: Sequence[Candle], tf_ms: int, last_closed_end_ms: Optional[int] = None) -> list:
    """Aggregate candles into larger buckets aligned to the epoch; incomplete last bucket is dropped."""
    out: list = []
    cur = None
    for c in candles:
        b = c.ts - (c.ts % tf_ms)
        if cur is None or cur["ts"] != b:
            if cur is not None:
                out.append(cur)
            cur = {"ts": b, "o": c.o, "h": c.h, "l": c.l, "c": c.c, "v": c.v, "last": c.ts}
        else:
            cur["h"] = max(cur["h"], c.h)
            cur["l"] = min(cur["l"], c.l)
            cur["c"] = c.c
            cur["v"] += c.v
            cur["last"] = c.ts
    if cur is not None:
        out.append(cur)
    if not out or not candles:
        return []
    # estimate base candle length to decide whether the final bucket is complete
    base_ms = candles[-1].ts - candles[-2].ts if len(candles) > 1 else tf_ms
    end_ms = last_closed_end_ms if last_closed_end_ms is not None else candles[-1].ts + base_ms
    res = []
    for b in out:
        if b["ts"] + tf_ms <= end_ms:
            res.append(Candle(b["ts"], b["o"], b["h"], b["l"], b["c"], b["v"]))
    return res
