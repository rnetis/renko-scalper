"""Deterministic synthetic OHLCV generator with trending/ranging regimes (for tests and offline demos)."""
from __future__ import annotations

import math
import random

from renko_scalper.models import Candle


def gen_candles(n: int, start_price: float = 100.0, tf_ms: int = 60_000, seed: int = 1,
                vol_pct: float = 0.002, t0: int = 1_700_000_000_000) -> list:
    rnd = random.Random(seed)
    out = []
    price = start_price
    drift = 0.0
    regime_left = 0
    for i in range(n):
        if regime_left <= 0:
            regime_left = rnd.randint(40, 160)
            drift = rnd.choice([-1, 0, 1]) * vol_pct * rnd.uniform(0.15, 0.5)
        regime_left -= 1
        o = price
        # pullback-rich walk: slow mean reversion around the drift path
        ret = drift + rnd.gauss(0, vol_pct)
        c = max(0.0001, o * (1 + ret))
        wick = abs(rnd.gauss(0, vol_pct * 0.6)) * o
        h = max(o, c) + wick * rnd.random()
        l = min(o, c) - wick * rnd.random()
        move = abs(c - o) / o
        v = 1000 * (1 + 40 * move / max(vol_pct, 1e-9) * 0.2) * rnd.uniform(0.6, 1.4)
        out.append(Candle(t0 + i * tf_ms, o, h, l, c, v))
        price = c
    return out


def trending(n: int, up: bool = True, start: float = 100.0, tf_ms: int = 60_000, step_pct: float = 0.0015,
             pullback_every: int = 25, pullback_len: int = 6, noise: float = 0.0006, seed: int = 3,
             t0: int = 1_700_000_000_000) -> list:
    """Staircase trend: impulse legs separated by short pullbacks (the structure Renko reversals key on)."""
    rnd = random.Random(seed)
    out, price = [], start
    sign = 1 if up else -1
    for i in range(n):
        in_pb = (i % pullback_every) >= (pullback_every - pullback_len)
        d = (-sign if in_pb else sign) * step_pct * (1.8 if in_pb else 1.0)
        o = price
        c = o * (1 + d + rnd.gauss(0, noise))
        h = max(o, c) * (1 + abs(rnd.gauss(0, noise)) * 0.5)
        l = min(o, c) * (1 - abs(rnd.gauss(0, noise)) * 0.5)
        v = 1000 * rnd.uniform(0.8, 1.3) * (1.6 if (i % pullback_every) == (pullback_every - pullback_len - 1) else 1.0)
        out.append(Candle(t0 + i * tf_ms, o, h, l, c, v))
        price = c
    return out
