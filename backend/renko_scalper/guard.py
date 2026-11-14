"""Account-level circuit breakers. They only ever REMOVE alerts, never add them.

A scanner that keeps firing during a losing streak or a correlated crash is how small accounts die.
"""
from __future__ import annotations

from typing import Optional


class RiskGuard:
    def __init__(self, cfg):
        self.cfg = cfg

    def blocked(self, store, side: int, now_ms: int) -> Optional[str]:
        g = self.cfg
        if not getattr(g, "enabled", True):
            return None
        active = store.list(limit=200, status="active")
        if len(active) >= g.max_active:
            return f"{len(active)} signals already open (max {g.max_active})"
        same = sum(1 for r in active if r["payload"].get("side") == side)
        if same >= g.max_same_side:
            return f"{same} {'long' if side > 0 else 'short'} signals already open (max {g.max_same_side}; correlated risk)"

        closed = store.closed(limit=200)
        day_start = now_ms - now_ms % 86_400_000
        day_r = sum((r["trade"].get("result_r") or 0.0) for r in closed if r["trade"].get("last_ts", 0) >= day_start)
        if day_r <= -g.daily_loss_limit_r:
            return f"daily loss limit hit ({day_r:.1f}R today) - done for the day"

        closed.sort(key=lambda r: r["trade"].get("last_ts", 0), reverse=True)
        streak = 0
        for r in closed:
            if (r["trade"].get("result_r") or 0.0) < 0:
                streak += 1
            else:
                break
        if streak >= g.consecutive_losses:
            last = closed[0]["trade"].get("last_ts", 0)
            if now_ms - last < g.pause_min * 60_000:
                return f"{streak} losses in a row - paused {g.pause_min} min"
        return None
