from __future__ import annotations

import math
from typing import Optional

from .models import MarketInfo


def floor_to_step(x: float, step: float) -> float:
    if step <= 0:
        return x
    return math.floor(x / step + 1e-9) * step


def size_position(
    equity: float,
    risk_pct: float,
    entry: float,
    stop: float,
    taker_pct: float,
    mkt: Optional[MarketInfo] = None,
    max_leverage: float = 20.0,
) -> Optional[dict]:
    """Maximum position size such that a stop-out (incl. taker fees both ways) costs `risk_pct` of equity.

    Capital preservation first: per-trade risk is hard-capped at 3% (Miner's maximum).
    Returns None when the size is below the exchange minimums.
    """
    risk_pct = min(max(risk_pct, 0.0), 3.0)
    dist = abs(entry - stop)
    if equity <= 0 or dist <= 0 or entry <= 0:
        return None
    fee_per_unit = (entry + stop) * taker_pct / 100.0
    loss_per_unit = dist + fee_per_unit
    budget = equity * risk_pct / 100.0
    qty = budget / loss_per_unit
    step = mkt.step if mkt and mkt.step > 0 else 0.0
    qty = floor_to_step(qty, step) if step else qty
    if qty <= 0:
        return None
    if mkt and mkt.min_qty and qty < mkt.min_qty:
        return None
    notional = qty * entry
    if mkt and mkt.min_notional and notional < mkt.min_notional:
        return None
    stop_pct = dist / entry * 100.0
    # keep liquidation far beyond the stop: isolated-margin liquidation is ~100/L % away
    liq_safe = max(1, int(50.0 / stop_pct)) if stop_pct > 0 else 1
    lev = int(max(1, min(max_leverage, liq_safe)))
    return {
        "qty": qty,
        "notional": notional,
        "risk_usdt": qty * loss_per_unit,
        "leverage_hint": lev,
        "margin_usdt": notional / lev,
        "stop_pct": stop_pct,
    }
