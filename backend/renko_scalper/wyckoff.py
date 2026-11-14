"""Wyckoff price/volume reading on closed candles.

Implements the pieces that can be made objective:
  * significant bar  (wide range, higher volume, close in the direction half, beyond prior level)
  * shake            (Spring / Upthrust: sweep of a range extreme that is reclaimed)
  * effort vs result (volume that does or does not produce price progress)
"""
from __future__ import annotations

from typing import Optional, Sequence

from .models import Candle


def _avg(vals) -> float:
    vals = list(vals)
    return sum(vals) / len(vals) if vals else 0.0


def significant_bar(
    cs: Sequence[Candle],
    side: int,
    look: int = 3,
    base: int = 20,
    brk: int = 10,
    range_mult: float = 1.3,
    vol_mult: float = 1.2,
) -> Optional[dict]:
    n = len(cs)
    if n < base + look + brk:
        return None
    for off in range(1, look + 1):
        i = n - off
        prev = cs[i - base : i]
        avg_rng = _avg(p.h - p.l for p in prev)
        avg_vol = _avg(p.v for p in prev)
        b = cs[i]
        rng = b.h - b.l
        if avg_rng <= 0 or rng < range_mult * avg_rng:
            continue
        if avg_vol > 0 and b.v < vol_mult * avg_vol:
            continue
        mid = (b.h + b.l) / 2
        if side > 0:
            level = max(p.h for p in cs[i - brk : i])
            if b.c > mid and b.c > level:
                return {"bars_ago": off - 1, "range_x": rng / avg_rng, "vol_x": b.v / avg_vol if avg_vol else 0.0}
        else:
            level = min(p.l for p in cs[i - brk : i])
            if b.c < mid and b.c < level:
                return {"bars_ago": off - 1, "range_x": rng / avg_rng, "vol_x": b.v / avg_vol if avg_vol else 0.0}
    return None


def shake(
    cs: Sequence[Candle],
    side: int,
    atr_val: float,
    range_lb: int = 40,
    recent: int = 4,
    base_vol: int = 20,
) -> Optional[dict]:
    """Spring (side>0) / Upthrust (side<0): a recent bar pierces the range extreme, price is back inside."""
    n = len(cs)
    if n < range_lb + recent + 1 or atr_val <= 0:
        return None
    rng_bars = cs[-(range_lb + recent) : -recent]
    hi = max(b.h for b in rng_bars)
    lo = min(b.l for b in rng_bars)
    height = hi - lo
    if not (1.5 * atr_val <= height <= 12 * atr_val):
        return None
    rec = cs[-recent:]
    avg_vol = _avg(b.v for b in cs[-(base_vol + recent) : -recent])
    if side > 0:
        under = [b for b in rec if b.l < lo]
        if not under or cs[-1].c <= lo:
            return None
        vr = max(b.v for b in under) / avg_vol if avg_vol > 0 else 1.0
        return {"kind": "spring", "level": lo, "extreme": min(b.l for b in under), "vol_ratio": vr, "low_volume": vr <= 1.0}
    over = [b for b in rec if b.h > hi]
    if not over or cs[-1].c >= hi:
        return None
    vr = max(b.v for b in over) / avg_vol if avg_vol > 0 else 1.0
    return {"kind": "upthrust", "level": hi, "extreme": max(b.h for b in over), "vol_ratio": vr, "low_volume": vr <= 1.0}


def effort_result(cs: Sequence[Candle], atr_val: float, look: int = 5, base: int = 20) -> tuple:
    """Return (bias, info). bias: +1 bullish, -1 bearish, 0 neutral.

    Harmony: high effort with real progress confirms the move direction.
    Absorption: high effort with little progress after a drift means the drift is being absorbed
    (selling absorbed after a decline = bullish; buying absorbed after a rally = bearish).
    """
    n = len(cs)
    if n < base + 2 * look + 1 or atr_val <= 0:
        return 0, {}
    recent = cs[-look:]
    prev = cs[-(base + look) : -look]
    avg_v = _avg(b.v for b in prev)
    if avg_v <= 0:
        return 0, {}
    effort = _avg(b.v for b in recent) / avg_v
    move = recent[-1].c - recent[0].o
    result = abs(move) / (2.0 * atr_val)
    prior_move = cs[-look - 1].c - cs[-2 * look - 1].c
    info = {"effort": effort, "result": result}
    if effort >= 1.5 and result < 0.5:
        if prior_move < 0:
            return 1, {**info, "kind": "absorption_of_selling"}
        if prior_move > 0:
            return -1, {**info, "kind": "absorption_of_buying"}
        return 0, info
    if effort >= 1.2 and result >= 1.0:
        return (1 if move > 0 else -1), {**info, "kind": "harmony"}
    return 0, info
