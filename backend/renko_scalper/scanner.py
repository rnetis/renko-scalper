from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from .config import INTERVAL_MS
from .indicators import atr, resample
from .models import MarketInfo, Profile, Setup
from .notify import Dispatcher, event_message, signal_message
from .renko import StableSizes, build_renko
from .risk import size_position
from .store import Store
from .strategy import evaluate, infer_tick
from .toobit import ToobitClient, closed_only
from .trade import TradeState, advance, new_trade

log = logging.getLogger("renko.scanner")

FETCH_LIMIT = {"1m": 720, "5m": 500, "15m": 400}


def build_profiles(cfg) -> dict:
    out = {}
    for name, p in vars(cfg.profiles).items():
        if not p.enabled:
            continue
        out[name] = Profile(
            name=name, base_interval=p.ltf, ltf_ms=INTERVAL_MS[p.ltf], htf_ms=INTERVAL_MS[p.htf],
            ltf_atr_mult=p.ltf_atr_mult, htf_atr_mult=p.htf_atr_mult, max_age_candles=p.max_age_candles,
            max_stop_bricks=p.max_stop_bricks, tp1_r=p.tp1_r, max_hold_candles=p.max_hold_candles,
        )
    return out


class Scanner:
    def __init__(self, cfg, client: Optional[ToobitClient] = None, store: Optional[Store] = None,
                 dispatcher: Optional[Dispatcher] = None):
        self.cfg = cfg
        self.client = client or ToobitClient(cfg.exchange.base_url, cfg.exchange.proxy, cfg.exchange.timeout)
        self.store = store or Store(cfg.storage.db_path)
        self.out = dispatcher or Dispatcher(cfg.notify)
        self.profiles = build_profiles(cfg)
        self.sizes = StableSizes()
        self.info: dict = {}
        self.universe: list = []
        self._universe_at = 0.0
        self._cache: dict = {}
        self._lock = threading.Lock()
        self.watch: list = []
        self.last_scan_ms = 0
        self.last_error = ""
        self.cycles = 0

    # ------------------------------------------------------------------ data
    def refresh_universe(self, force: bool = False) -> None:
        if not force and time.time() - self._universe_at < self.cfg.universe.refresh_sec and self.universe:
            return
        contracts = self.client.contracts()
        tick = self.client.tickers_24h()
        u = self.cfg.universe
        rows = []
        for sym, m in contracts.items():
            if u.include_only and sym not in u.include_only:
                continue
            if sym in u.exclude:
                continue
            qv = tick.get(sym, {}).get("qv", 0.0)
            if qv < u.min_quote_volume_usdt:
                continue
            m.qv24h = qv
            rows.append((qv, sym))
        rows.sort(reverse=True)
        self.universe = [s for _, s in rows[: u.max_symbols]]
        self.info = {s: contracts[s] for s in self.universe}
        self._universe_at = time.time()
        log.info("universe: %d symbols", len(self.universe))

    def _apply_books(self) -> None:
        try:
            books = self.client.book_tickers()
        except Exception as e:  # noqa: BLE001
            log.warning("bookTicker failed: %s", e)
            return
        for sym, m in self.info.items():
            if sym in books:
                m.bid, m.ask = books[sym]

    def candles(self, symbol: str, interval: str) -> list:
        ms = INTERVAL_MS[interval]
        ttl = max(15.0, ms / 1000 / 4)
        key = (symbol, interval)
        with self._lock:
            hit = self._cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        rows = closed_only(self.client.klines(symbol, interval, FETCH_LIMIT.get(interval, 500)), ms)
        with self._lock:
            self._cache[key] = (time.time(), rows)
        return rows

    def series_for(self, symbol: str, prof: Profile) -> tuple:
        ltf = self.candles(symbol, self._interval_of(prof))
        htf = resample(ltf, prof.htf_ms)
        return ltf, htf

    @staticmethod
    def _interval_of(prof: Profile) -> str:
        return prof.base_interval

    # ------------------------------------------------------------------ evaluation
    def _scan_symbol(self, sym: str) -> list:
        out = []
        mkt = self.info[sym]
        if mkt.tick <= 0:
            mkt.tick = 0.0
        for prof in self.profiles.values():
            try:
                ltf, htf = self.series_for(sym, prof)
                s = evaluate(sym, ltf, htf, prof, mkt, self.cfg, self.sizes)
                if s:
                    out.append(s)
            except Exception as e:  # noqa: BLE001
                self.last_error = f"{sym}: {e}"
                log.debug("scan %s failed: %s", sym, e)
        return out

    def _sizing(self, s: Setup) -> Optional[dict]:
        a = self.cfg.account
        return size_position(a.equity_usdt, a.risk_per_trade_pct, s.entry, s.stop, self.cfg.fees.taker_pct,
                             self.info.get(s.symbol), a.max_leverage)

    def _payload(self, s: Setup) -> dict:
        d = s.to_dict()
        d["sizing"] = self._sizing(s)
        return d

    def scan_once(self) -> list:
        self.refresh_universe()
        self._apply_books()
        with ThreadPoolExecutor(max_workers=6) as ex:
            results = list(ex.map(self._scan_symbol, list(self.universe)))
        setups = sorted((s for r in results for s in r), key=lambda s: (-s.score, -s.cost_multiple))
        al = self.cfg.alerts
        with self._lock:
            self.watch = [self._payload(s) for s in setups if s.score >= al.watch_min_score][:15]
            self.last_scan_ms = int(time.time() * 1000)
            self.cycles += 1
        self._alert(setups)
        self.track()
        return setups

    # ------------------------------------------------------------------ alerts
    def _alert(self, setups: list) -> None:
        al = self.cfg.alerts
        sent = 0
        now_ms = int(time.time() * 1000)
        for s in setups:
            if s.score < al.min_score or sent >= al.top_n:
                continue
            cool = getattr(al.cooldown_min, s.style, 15) * 60_000
            if now_ms - self.store.last_created_ms(s.symbol, s.style) < cool:
                continue
            p = self._payload(s)
            tr = new_trade(s.side, s.entry, s.stop, s.tp1, s.brick_ltf, self.cfg.fees.taker_pct)
            tr.last_ts = s.ts
            sid = self.store.insert(s.key, p, tr.to_dict())
            if sid is None:
                continue
            p["id"] = sid
            title, body = signal_message(p)
            self.out.send(title, body, "high" if s.score >= 80 else "default")
            sent += 1

    # ------------------------------------------------------------------ lifecycle tracking
    def track(self) -> None:
        for row in self.store.list(limit=200, status="active"):
            p, t = row["payload"], row["trade"]
            try:
                st = TradeState.from_dict(t)
                prof = self.profiles.get(p["style"])
                if not prof:
                    continue
                cs = self.candles(p["symbol"], self._interval_of(prof))
                events: list = []
                for c in cs:
                    if c.ts > st.last_ts and st.status != "closed":
                        events += advance(st, c)
                if st.status != "closed" and st.bars >= p.get("max_hold_candles", 90):
                    st.status, st.exit_reason = "closed", "expired"
                    events.append("expired")
                if events:
                    status = "expired" if "expired" in events else st.status if st.status != "closed" else st.exit_reason
                    self.store.update(row["id"], status, st.to_dict())
                    for ev in events:
                        m = event_message(p, ev, st.to_dict())
                        if m:
                            self.out.send(*m)
                elif st.last_ts != t.get("last_ts"):
                    self.store.update(row["id"], row["status"], st.to_dict())
            except Exception as e:  # noqa: BLE001
                log.warning("track %s failed: %s", row["id"], e)

    # ------------------------------------------------------------------ chart data for the app
    def renko_view(self, symbol: str, style: str, tf: str = "ltf", limit: int = 80) -> Optional[dict]:
        prof = self.profiles.get(style)
        if not prof or symbol not in self.info:
            return None
        ltf, htf = self.series_for(symbol, prof)
        candles = ltf if tf == "ltf" else htf
        if len(candles) < 30:
            return None
        mkt = self.info[symbol]
        tick = mkt.tick if mkt.tick > 0 else infer_tick(candles[-1].c)
        mult = prof.ltf_atr_mult if tf == "ltf" else prof.htf_atr_mult
        size = self.sizes.get((symbol, style, tf), atr(candles) * mult, tick)
        bricks = build_renko(candles, size)[-limit:]
        return {
            "symbol": symbol, "style": style, "tf": tf, "size": size, "price": candles[-1].c,
            "bricks": [{"ts": b.ts, "dir": b.dir, "o": b.o, "c": b.c, "vol": b.vol} for b in bricks],
        }

    # ------------------------------------------------------------------ loop
    def run_forever(self, stop: threading.Event) -> None:
        log.info("scanner started: profiles=%s", list(self.profiles))
        while not stop.is_set():
            t0 = time.time()
            try:
                self.scan_once()
            except Exception as e:  # noqa: BLE001
                self.last_error = str(e)
                log.exception("scan cycle failed")
            stop.wait(max(1.0, self.cfg.scan.interval_sec - (time.time() - t0)))
