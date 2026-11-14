"""Walk-forward backtest of the exact live logic (strategy.evaluate + trade.advance) on historical klines.

No look-ahead: at every closed candle only data up to that candle is visible. The entry is filled at
the NEXT candle's open (skipped if it is already >0.3R beyond the signal price); stops are assumed hit
before targets within one candle; fees are charged taker-both-ways on each unit.
"""
from __future__ import annotations

import csv
import math
import time
from typing import Optional

from .config import INTERVAL_MS
from .indicators import resample
from .models import MarketInfo, Profile
from .renko import StableSizes
from .strategy import evaluate
from .trade import advance, new_trade


def fetch_history(client, symbol: str, interval: str, days: float) -> list:
    ms = INTERVAL_MS[interval]
    end = int(time.time() * 1000)
    start = end - int(days * 86_400_000)
    out: dict = {}
    cur = start
    while cur < end:
        nxt = min(end, cur + 1000 * ms)
        for c in client.klines(symbol, interval, 1000, start_ms=cur, end_ms=nxt):
            out[c.ts] = c
        cur = nxt
        time.sleep(0.15)
    cs = [out[k] for k in sorted(out)]
    return [c for c in cs if c.ts + ms <= end]


def run_backtest(symbol: str, candles: list, prof: Profile, mkt: MarketInfo, cfg, warmup: int = 300,
                 window: int = 600) -> list:
    sizes = StableSizes()
    trades: list = []
    i = warmup
    n = len(candles)
    fee = cfg.fees.taker_pct
    while i < n - 2:
        ltf = candles[max(0, i + 1 - window): i + 1]
        htf = resample(ltf, prof.htf_ms)
        s = evaluate(symbol, ltf, htf, prof, mkt, cfg, sizes)
        if s is None or s.score < cfg.alerts.min_score:
            i += 1
            continue
        nxt = candles[i + 1]
        slip = (nxt.o - s.price) * s.side / s.risk_dist
        if slip > 0.3 or (s.side > 0 and nxt.o <= s.stop) or (s.side < 0 and nxt.o >= s.stop):
            i += 1
            continue
        st = new_trade(s.side, nxt.o, s.stop, s.tp1 + (nxt.o - s.price), s.brick_ltf, fee)
        st.last_ts = nxt.ts
        j = i + 1
        while j < n and st.status != "closed":
            advance(st, candles[j])
            if st.status != "closed" and st.bars >= prof.max_hold_candles:
                px = candles[j].c
                r_unit = st._unit_r(px)
                st.result_r = (0.5 * st.unit1_r + 0.5 * r_unit) if st.tp1_hit else r_unit
                st.status, st.exit_reason = "closed", "time_exit"
            j += 1
        if st.status != "closed":
            break  # data ended mid-trade
        trades.append({"symbol": symbol, "style": prof.name, "side": s.side_name, "ts": nxt.ts, "score": s.score,
                       "r": st.result_r, "bars": st.bars, "reason": st.exit_reason, "tp1": st.tp1_hit})
        i = max(j, i + 1)
    return trades


def summarize(trades: list, days: float) -> dict:
    if not trades:
        return {"trades": 0}
    rs = [t["r"] for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    eq, peak, mdd = 0.0, 0.0, 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    gp, gl = sum(wins), -sum(losses)
    return {
        "trades": len(rs), "per_day": round(len(rs) / max(days, 1e-9), 2),
        "win_rate_pct": round(100 * len(wins) / len(rs), 1),
        "avg_r": round(sum(rs) / len(rs), 3), "total_r": round(sum(rs), 2),
        "profit_factor": round(gp / gl, 2) if gl > 0 else math.inf,
        "max_drawdown_r": round(mdd, 2), "tp1_hit_pct": round(100 * sum(1 for t in trades if t["tp1"]) / len(rs), 1),
    }


def write_csv(path: str, trades: list) -> None:
    if not trades:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(trades[0].keys()))
        w.writeheader()
        w.writerows(trades)
