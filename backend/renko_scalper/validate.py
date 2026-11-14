"""Go / no-go validation: is there evidence this strategy survives costs, out of sample?

Answers one question honestly: "should real money follow these alerts?". It never says GO on thin data.
Pipeline: backtest (walk-forward, no look-ahead) -> pool symbols -> time split in-sample/out-of-sample ->
fee x multiplier + slippage stress -> bootstrap confidence on expectancy -> Monte-Carlo drawdown risk.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .backtest import run_backtest


@dataclass
class Criteria:
    min_trades: int = 100
    min_oos_trades: int = 30
    fee_mult: float = 1.5  # stress: real costs are higher than the model (tiers, spread, funding)
    slippage_r: float = 0.05  # extra R lost per trade to slippage on entry + stop
    min_oos_avg_r: float = 0.05
    min_oos_pf: float = 1.15
    boot_pctl: float = 5.0  # this percentile of bootstrapped avg R must be > 0
    max_dd_r: float = 10.0
    max_dd_prob: float = 0.20  # P(drawdown >= max_dd_r within horizon trades)
    horizon: int = 200
    oos_frac: float = 0.30
    seed: int = 7


@dataclass
class Verdict:
    go: bool
    reasons: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def stressed(trades: list, fee_mult: float, slippage_r: float) -> list:
    out = []
    for t in trades:
        r = t["r"] - (fee_mult - 1.0) * t.get("fee_r", 0.0) - slippage_r
        out.append({**t, "r": r})
    return out


def _stats(rs: list) -> dict:
    if not rs:
        return {"n": 0, "avg_r": 0.0, "pf": 0.0, "win_pct": 0.0, "total_r": 0.0, "max_dd_r": 0.0, "max_losing_streak": 0}
    gp = sum(r for r in rs if r > 0)
    gl = -sum(r for r in rs if r <= 0)
    eq = peak = mdd = 0.0
    streak = worst = 0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
        streak = streak + 1 if r < 0 else 0
        worst = max(worst, streak)
    return {"n": len(rs), "avg_r": sum(rs) / len(rs), "pf": gp / gl if gl > 0 else float("inf"),
            "win_pct": 100.0 * sum(1 for r in rs if r > 0) / len(rs), "total_r": sum(rs), "max_dd_r": mdd,
            "max_losing_streak": worst}


def bootstrap_avg_r(rs: list, pctl: float, n: int = 2000, seed: int = 7) -> float:
    if not rs:
        return 0.0
    rnd = random.Random(seed)
    means = sorted(sum(rnd.choice(rs) for _ in rs) / len(rs) for _ in range(n))
    return means[max(0, min(n - 1, int(n * pctl / 100.0)))]


def dd_probability(rs: list, horizon: int, dd_r: float, n: int = 2000, seed: int = 7) -> float:
    """P(max drawdown >= dd_r) over `horizon` consecutive trades drawn from the stressed trade distribution."""
    if not rs:
        return 1.0
    rnd = random.Random(seed)
    hit = 0
    for _ in range(n):
        eq = peak = 0.0
        for _ in range(horizon):
            eq += rnd.choice(rs)
            peak = max(peak, eq)
            if peak - eq >= dd_r:
                hit += 1
                break
    return hit / n


def evaluate_trades(trades: list, crit: Criteria) -> Verdict:
    trades = sorted(trades, key=lambda t: t["ts"])
    st = stressed(trades, crit.fee_mult, crit.slippage_r)
    base = _stats([t["r"] for t in trades])
    cut = int(len(st) * (1.0 - crit.oos_frac))
    is_, oos = st[:cut], st[cut:]
    s_all, s_is, s_oos = (_stats([t["r"] for t in x]) for x in (st, is_, oos))
    boot = bootstrap_avg_r([t["r"] for t in st], crit.boot_pctl, seed=crit.seed)
    ddp = dd_probability([t["r"] for t in st], crit.horizon, crit.max_dd_r, seed=crit.seed)
    buckets = {}
    for name, lo, hi in (("70-79", 70, 79), ("80+", 80, 101)):
        b = [t["r"] for t in st if lo <= t.get("score", 0) <= hi]
        buckets[name] = _stats(b)

    why = []
    if s_all["n"] < crit.min_trades:
        why.append(f"only {s_all['n']} trades (need >= {crit.min_trades}); the result is statistical noise")
    if s_oos["n"] < crit.min_oos_trades:
        why.append(f"only {s_oos['n']} out-of-sample trades (need >= {crit.min_oos_trades})")
    if s_oos["avg_r"] < crit.min_oos_avg_r:
        why.append(f"out-of-sample expectancy {s_oos['avg_r']:+.3f}R after stress (need >= {crit.min_oos_avg_r:+.2f}R)")
    if s_oos["pf"] < crit.min_oos_pf:
        why.append(f"out-of-sample profit factor {s_oos['pf']:.2f} (need >= {crit.min_oos_pf})")
    if (s_is["avg_r"] > 0) != (s_oos["avg_r"] > 0):
        why.append("in-sample and out-of-sample disagree in sign: the 'edge' did not generalise")
    if boot <= 0:
        why.append(f"{crit.boot_pctl:.0f}th-percentile bootstrapped expectancy is {boot:+.3f}R (<= 0): cannot rule out luck")
    if ddp > crit.max_dd_prob:
        why.append(f"{ddp:.0%} chance of a >= {crit.max_dd_r:.0f}R drawdown within {crit.horizon} trades (max {crit.max_dd_prob:.0%})")
    stats = {"unstressed": base, "stressed_all": s_all, "in_sample": s_is, "out_of_sample": s_oos,
             "bootstrap_avg_r_low": boot, "dd_probability": ddp, "score_buckets": buckets,
             "criteria": crit.__dict__}
    return Verdict(go=not why, reasons=why, stats=stats)


def run_validation(datasets: dict, prof, infos: dict, cfg, crit: Criteria, workers: int = 1) -> tuple:
    """datasets: {symbol: candles}. Returns (all_trades, Verdict). workers>1 backtests symbols in parallel."""
    trades: list = []
    if workers > 1 and len(datasets) > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(run_backtest, sym, cs, prof, infos[sym], cfg) for sym, cs in datasets.items()]
            for f in futs:
                trades += f.result()
    else:
        for sym, cs in datasets.items():
            trades += run_backtest(sym, cs, prof, infos[sym], cfg)
    return trades, evaluate_trades(trades, crit)


def format_report(v: Verdict) -> str:
    s = v.stats
    f = lambda d: (f"n={d['n']:<4} win={d['win_pct']:.0f}%  avgR={d['avg_r']:+.3f}  PF={d['pf']:.2f}  "
                   f"totalR={d['total_r']:+.1f}  maxDD={d['max_dd_r']:.1f}R  worst streak={d['max_losing_streak']}")
    c = s["criteria"]
    lines = [
        "unstressed   " + f(s["unstressed"]),
        f"stressed     {f(s['stressed_all'])}   (fees x{c['fee_mult']}, -{c['slippage_r']}R slippage)",
        "  in-sample  " + f(s["in_sample"]),
        "  out-sample " + f(s["out_of_sample"]),
        f"bootstrap {c['boot_pctl']:.0f}th pct of avg R: {s['bootstrap_avg_r_low']:+.3f}",
        f"P(>= {c['max_dd_r']:.0f}R drawdown in {c['horizon']} trades): {s['dd_probability']:.0%}",
        "by score:    " + "   ".join(f"{k}: n={b['n']} avgR={b['avg_r']:+.3f}" for k, b in s["score_buckets"].items()),
        "",
        "VERDICT: " + ("GO (still start with paper trading, then 0.25-0.5% risk)" if v.go else "NO-GO - do not trade real money on these alerts"),
    ]
    lines += [f"  - {r}" for r in v.reasons]
    return "\n".join(lines)
