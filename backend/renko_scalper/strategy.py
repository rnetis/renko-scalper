"""Signal engine: Renko trigger + Miner dual-timeframe momentum + Wyckoff volume logic + cost filter.

Hard gates (a setup is discarded if any fails):
  tradable liquidity/spread, a fresh LTF Renko reversal trigger, the Miner momentum table permits the
  side, a structural stop within max_stop_bricks, and the TP1 distance clears round-trip costs.
Everything else adds to a 0-100 score used for ranking.
"""
from __future__ import annotations

from typing import Optional

from .indicators import atr, momentum
from .models import Candle, MarketInfo, Profile, Setup
from .renko import StableSizes, build_renko, last_run, prior_run
from .wyckoff import effort_result, shake, significant_bar


def grade(score: int) -> str:
    return "A" if score >= 80 else "B" if score >= 70 else "C"


def momentum_permit(h: dict, side: int) -> Optional[str]:
    """Miner's Dual Time Frame Momentum table (higher TF decides which side may be traded)."""
    if side > 0:
        if h["bull"] and not h["ob"]:
            return "trend"
        if (not h["bull"]) and h["os"]:
            return "reversal"
    else:
        if (not h["bull"]) and not h["os"]:
            return "trend"
        if h["bull"] and h["ob"]:
            return "reversal"
    return None


def infer_tick(price: float) -> float:
    if price <= 0:
        return 0.0
    if price >= 1000:
        return 0.1
    if price >= 100:
        return 0.01
    if price >= 10:
        return 0.001
    if price >= 1:
        return 0.0001
    return price / 10000.0


def evaluate(
    symbol: str,
    ltf: list,
    htf: list,
    profile: Profile,
    mkt: MarketInfo,
    cfg,
    sizes: StableSizes,
) -> Optional[Setup]:
    if len(ltf) < 120 or len(htf) < 60:
        return None
    price = ltf[-1].c
    if price <= 0:
        return None

    # ---- tradability gates -------------------------------------------------
    if mkt.qv24h < cfg.universe.min_quote_volume_usdt:
        return None
    spread = mkt.spread_pct
    spread_known = spread is not None
    if spread is None:
        spread = cfg.filters.default_spread_pct
    if spread > cfg.filters.max_spread_pct:
        return None

    tick = mkt.tick if mkt.tick > 0 else infer_tick(price)
    atr_l, atr_h = atr(ltf), atr(htf)
    if atr_l <= 0 or atr_h <= 0:
        return None
    size_l = sizes.get((symbol, profile.name, "ltf"), atr_l * profile.ltf_atr_mult, tick)
    size_h = sizes.get((symbol, profile.name, "htf"), atr_h * profile.htf_atr_mult, tick)
    if size_l <= 0 or size_h <= 0:
        return None

    bl = build_renko(ltf, size_l)
    bh = build_renko(htf, size_h)
    if len(bl) < 5 or len(bh) < 3:
        return None

    # ---- LTF Renko trigger: reversal brick (run of 1-2) after a counter run ----
    last = bl[-1]
    side = last.dir
    run_dir, run_len = last_run(bl)
    prior = prior_run(bl)
    if prior is None or run_len > 2 or prior[0] == side:
        return None
    age = (ltf[-1].ts - last.ts) / profile.ltf_ms
    if age > profile.max_age_candles:
        return None
    ext = (price - last.c) * side / size_l
    if ext > 1.0:
        return None  # price already ran a full brick beyond the trigger - do not chase

    # ---- momentum (Miner) ----------------------------------------------------
    mh, ml = momentum(htf), momentum(ltf)
    if mh is None or ml is None:
        return None
    permit = momentum_permit(mh, side)
    h_dir, h_run = last_run(bh)
    if permit is None:
        # Miner: HTF overbought/oversold limits further travel. Stochastics can stay pinned in a
        # strong trend, so optionally allow a (lower-scored, flagged) entry with the HTF Renko trend.
        if getattr(cfg.filters, "allow_extended_trend", True) and h_dir == side and h_run >= 3:
            permit = "extended"
        else:
            return None

    # ---- Wyckoff -------------------------------------------------------------
    sig = significant_bar(ltf, side)
    shk = shake(ltf, side, atr_l)
    er_bias, er_info = effort_result(ltf, atr_l)
    if permit == "reversal" and not (sig or shk):
        return None

    # ---- structure-based stop (one tick beyond the swing made before entry) ------
    prior_last = bl[prior[3]]
    recent = [c for c in ltf if c.ts >= prior_last.ts - 2 * profile.ltf_ms]
    if side > 0:
        swing = min(min(c.l for c in recent), prior_last.c)
        stop = swing - tick
        risk_dist = price - stop
    else:
        swing = max(max(c.h for c in recent), prior_last.c)
        stop = swing + tick
        risk_dist = stop - price
    if risk_dist < 0.5 * size_l or risk_dist > profile.max_stop_bricks * size_l:
        return None
    tp1 = price + side * profile.tp1_r * risk_dist

    # ---- cost filter (Day Trader's Bible: expenses must be small vs expected move) ----
    rt_cost_pct = 2.0 * cfg.fees.taker_pct + spread
    tp1_pct = abs(tp1 - price) / price * 100.0
    cost_mult = tp1_pct / rt_cost_pct if rt_cost_pct > 0 else 99.0
    if cost_mult < cfg.filters.min_move_cost_multiple:
        return None
    cost_price = price * rt_cost_pct / 100.0
    net_rr1 = max(0.0, (abs(tp1 - price) - cost_price) / (risk_dist + cost_price))

    # ---- scoring -----------------------------------------------------------------
    score = 0
    why: list = []
    warn: list = []
    if h_dir == side and h_run >= 2:
        score += 20
        why.append(f"HTF Renko {'up' if side > 0 else 'down'} x{h_run}")
    elif h_dir == side:
        score += 12
        why.append("HTF Renko just turned with the trade")
    else:
        warn.append("HTF Renko still against the trade")

    if permit == "trend":
        score += 15
        why.append("HTF momentum " + ("bull, not overbought" if side > 0 else "bear, not oversold"))
    elif permit == "extended":
        score += 4
        warn.append("HTF momentum already extreme - trend extended, expect limited travel")
    else:
        score += 8
        why.append("HTF momentum " + ("oversold - reversal long" if side > 0 else "overbought - reversal short"))

    if ml["rev_dir"] == side and ml["rev_age"] is not None and ml["rev_age"] <= 3:
        zone_bad = ml["rev_in_ob"] if side > 0 else ml["rev_in_os"]
        if zone_bad:
            warn.append("LTF momentum reversal made in extreme zone")
        else:
            score += 15
            why.append("LTF momentum reversal in trade direction")
    else:
        warn.append("no fresh LTF momentum reversal")

    if run_len == 2:
        score += 5
        why.append("Renko reversal confirmed by 2nd brick")
    else:
        why.append("first Renko reversal brick (earlier, less confirmed)")

    if sig:
        score += 10
        why.append(f"Wyckoff significant bar ({sig['range_x']:.1f}x range, {sig['vol_x']:.1f}x vol)")
    if shk:
        if shk["low_volume"]:
            score += 10
            why.append(f"{shk['kind']} on low volume")
        else:
            score += 4
            warn.append(f"{shk['kind']} on high volume - a test of it is safer")
    if er_bias == side:
        score += 5
        why.append("effort/result " + er_info.get("kind", "supports move").replace("_", " "))
    elif er_bias == -side:
        score -= 5
        warn.append("effort/result disagrees (" + er_info.get("kind", "").replace("_", " ") + ")")

    vols = [b.vol for b in bl[-11:-1] if b.vol > 0]
    if vols:
        med = sorted(vols)[len(vols) // 2]
        if med > 0 and last.vol >= 1.2 * med:
            score += 5
            why.append("reversal brick formed on above-median volume")

    if cost_mult >= 6:
        score += 10
    elif cost_mult >= cfg.filters.min_move_cost_multiple:
        score += 5
    why.append(f"TP1 = {cost_mult:.1f}x round-trip cost")

    if mkt.qv24h >= 5 * cfg.universe.min_quote_volume_usdt and spread <= 0.02:
        score += 5
    if not spread_known:
        warn.append("spread unknown - used default")
    if ext > 0.5:
        warn.append("price already extended past the trigger - prefer a pullback entry")

    score = int(max(0, min(100, score)))
    key = f"{symbol}|{profile.name}|{side}|{last.ts}"
    return Setup(
        key=key, symbol=symbol, style=profile.name, side=side, score=score, grade=grade(score),
        ts=ltf[-1].ts, price=price, entry=price, stop=stop, tp1=tp1,
        brick_ltf=size_l, brick_htf=size_h, risk_dist=risk_dist,
        cost_multiple=cost_mult, net_rr1=net_rr1, reasons=why, warnings=warn,
        ltf_ms=profile.ltf_ms, max_hold_candles=profile.max_hold_candles,
    )
