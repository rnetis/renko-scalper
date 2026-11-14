from __future__ import annotations

import logging
from typing import Optional

import requests

log = logging.getLogger("renko.notify")


class Dispatcher:
    """Fan-out to the configured channels. Failures never break the scanner."""

    def __init__(self, cfg):
        self.console = bool(cfg.console)
        tg, nt = cfg.telegram, cfg.ntfy
        self.tg = tg if tg.token and tg.chat_id else None
        self.nt = nt if nt.topic else None

    def send(self, title: str, body: str, priority: str = "default") -> None:
        if self.console:
            print(f"\n=== {title} ===\n{body}\n", flush=True)
        if self.tg:
            try:
                px = {"https": self.tg.proxy, "http": self.tg.proxy} if self.tg.proxy else None
                requests.post(
                    f"https://api.telegram.org/bot{self.tg.token}/sendMessage",
                    json={"chat_id": self.tg.chat_id, "text": f"{title}\n{body}", "disable_web_page_preview": True},
                    proxies=px, timeout=15,
                ).raise_for_status()
            except Exception as e:  # noqa: BLE001
                log.warning("telegram failed: %s", e)
        if self.nt:
            try:
                headers = {"Title": title.encode("utf-8"), "Priority": {"high": "4", "urgent": "5"}.get(priority, "3")}
                if self.nt.token:
                    headers["Authorization"] = f"Bearer {self.nt.token}"
                requests.post(f"{self.nt.server.rstrip('/')}/{self.nt.topic}", data=body.encode("utf-8"),
                              headers=headers, timeout=15).raise_for_status()
            except Exception as e:  # noqa: BLE001
                log.warning("ntfy failed: %s", e)


def fmt(x: float) -> str:
    if x >= 1000:
        return f"{x:,.2f}"
    if x >= 1:
        return f"{x:.4f}".rstrip("0").rstrip(".")
    return f"{x:.6f}".rstrip("0").rstrip(".")


def signal_message(p: dict) -> tuple:
    """(title, body) for a new signal payload."""
    icon = "🟢" if p["side"] > 0 else "🔴"
    title = f"{icon} {p['side_name']} {p['symbol']} [{p['style'].upper()}] score {p['score']} ({p['grade']})"
    stop_pct = abs(p["entry"] - p["stop"]) / p["entry"] * 100
    tp_pct = abs(p["tp1"] - p["entry"]) / p["entry"] * 100
    lines = [
        f"Entry ≈ {fmt(p['entry'])}   Stop {fmt(p['stop'])} (−{stop_pct:.2f}%)",
        f"TP1 {fmt(p['tp1'])} (+{tp_pct:.2f}%): close half, then stop to breakeven",
        f"Runner: trail {fmt(2 * p['brick_ltf'])} (2 Renko bricks) behind the best price; exit when taken out",
    ]
    sz = p.get("sizing")
    if sz:
        lines.append(f"Size @ risk {fmt(sz['risk_usdt'])} USDT: {fmt(sz['qty'])} units ≈ {fmt(sz['notional'])} USDT "
                     f"(isolated, ≤{sz['leverage_hint']}x, margin ≈ {fmt(sz['margin_usdt'])})")
    else:
        lines.append("Size: below exchange minimum for your risk budget")
    lines.append(f"Costs: TP1 = {p['cost_multiple']:.1f}x round-trip fees+spread; net R at TP1 ≈ {p['net_rr1']:.2f}")
    lines.append("Why: " + " · ".join(p["reasons"]))
    if p["warnings"]:
        lines.append("⚠ " + " · ".join(p["warnings"]))
    lines.append("Place the STOP as a real exchange order the moment you enter - this tool only tracks, it cannot protect you.")
    lines.append("Valid for ~3 candles. Decision support, not advice - you own the trade.")
    return title, "\n".join(lines)


def event_message(p: dict, ev: str, trade: dict) -> Optional[tuple]:
    sym = f"{p['side_name']} {p['symbol']}"
    if ev == "tp1":
        return (f"🎯 TP1 hit: {sym}",
                f"Close half now. Move stop to {fmt(trade['stop'])} (breakeven + fees). Runner trails 2 bricks.")
    if ev == "stopped":
        return (f"🛑 Stopped: {sym}", f"Result ≈ {trade['result_r']:.2f}R. Do not revenge-trade; wait for the next setup.")
    if ev == "runner_exit":
        return (f"🏁 Runner closed: {sym}", f"Blended result ≈ {trade['result_r']:.2f}R.")
    if ev == "expired":
        r = trade.get("result_r")
        tail = f" Marked at ≈ {r:.2f}R." if r is not None else ""
        return (f"⌛ Expired: {sym}", "Max holding time reached - exit or reassess." + tail)
    return None
