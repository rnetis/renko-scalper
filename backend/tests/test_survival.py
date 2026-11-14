import time

import pytest
import requests

from renko_scalper.config import assert_safe_token, load_config
from renko_scalper.doctor import run_doctor
from renko_scalper.guard import RiskGuard
from renko_scalper.models import Candle
from renko_scalper.notify import Dispatcher
from renko_scalper.scanner import Scanner
from renko_scalper.store import Store
from renko_scalper.toobit import ToobitClient
from renko_scalper.trade import advance, new_trade, time_exit
from renko_scalper.validate import Criteria, evaluate_trades, stressed


def _store(tmp_path):
    return Store(str(tmp_path / "g.db"))


def _add(store, key, side, status, result_r=None, last_ts=0):
    sid = store.insert(key, {"symbol": "X", "style": "scalp", "side": side, "score": 80},
                       {"last_ts": last_ts, "result_r": result_r, "stop": 1.0})
    store.update(sid, status, {"last_ts": last_ts, "result_r": result_r, "stop": 1.0})
    return sid


# ------------------------------------------------------------------ guard
def test_guard_correlated_side_and_max_active(tmp_path):
    cfg = load_config()
    g, st, now = RiskGuard(cfg.guard), _store(tmp_path), int(time.time() * 1000)
    assert g.blocked(st, 1, now) is None
    _add(st, "a", 1, "open")
    _add(st, "b", 1, "tp1")
    assert "correlated" in g.blocked(st, 1, now)
    assert g.blocked(st, -1, now) is None  # opposite side still allowed
    _add(st, "c", -1, "open")
    assert "max 3" in g.blocked(st, -1, now)


def test_guard_daily_loss_and_streak(tmp_path):
    cfg = load_config()
    g, st = RiskGuard(cfg.guard), _store(tmp_path)
    now = 1_800_000_000_000
    for i in range(3):
        _add(st, f"l{i}", 1, "stopped", -1.0, last_ts=now - 10 * 60_000 + i)
    assert "daily loss" in g.blocked(st, 1, now)
    # next day the daily limit resets, but the losing streak pause still applies for 60 min after the last loss
    assert "in a row" in g.blocked(st, 1, now + 20 * 60_000) or "daily" in g.blocked(st, 1, now + 20 * 60_000)
    assert g.blocked(st, 1, now + 3 * 86_400_000) is None


def test_guard_can_be_disabled(tmp_path):
    cfg = load_config()
    cfg.guard.enabled = False
    st = _store(tmp_path)
    for i in range(5):
        _add(st, f"o{i}", 1, "open")
    assert RiskGuard(cfg.guard).blocked(st, 1, int(time.time() * 1000)) is None


# ------------------------------------------------------------------ trade lifecycle
def test_time_exit_matches_backtest_maths():
    t = new_trade(1, 100.0, 99.0, 101.0, 0.5, 0.06)
    advance(t, Candle(1, 100, 101.5, 100, 101.2, 1))  # TP1 hit
    assert t.tp1_hit
    time_exit(t, 100.5)
    assert t.status == "closed" and t.exit_reason == "time_exit" and t.result_r is not None


# ------------------------------------------------------------------ watchdog
class Rec(Dispatcher):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.sent = []

    def send(self, title, body, priority="default"):
        self.sent.append((title, priority))


def test_watchdog_alerts_once_then_recovers(tmp_path):
    cfg = load_config()
    cfg.notify.console = False
    cfg.storage.db_path = str(tmp_path / "w.db")
    rec = Rec(cfg.notify)
    sc = Scanner(cfg, client=object(), store=Store(cfg.storage.db_path), dispatcher=rec)
    for _ in range(cfg.watchdog.fail_cycles - 1):
        sc._record_cycle(False)
    assert not rec.sent and not sc.degraded
    sc._record_cycle(False)
    sc._record_cycle(False)  # still down: must not spam
    assert sc.degraded and len(rec.sent) == 1 and rec.sent[0][1] == "urgent" and "BLIND" in rec.sent[0][0]
    sc._record_cycle(True)
    assert not sc.degraded and "recovered" in rec.sent[-1][0]


def test_paper_tag_and_health_endpoint(tmp_path):
    from fastapi.testclient import TestClient
    from renko_scalper.api import create_app
    cfg = load_config()
    cfg.api.token = "x" * 20
    cfg.storage.db_path = str(tmp_path / "h.db")
    sc = Scanner(cfg, client=object(), store=Store(cfg.storage.db_path), dispatcher=Dispatcher(cfg.notify))
    assert sc._tag("hi").startswith("[PAPER]")
    cfg.alerts.paper = False
    assert sc._tag("hi") == "hi"
    cl = TestClient(create_app(sc))
    pub = cl.get("/api/v1/health").json()
    assert "last_error" not in pub and pub["ok"] is True
    assert cl.get("/api/v1/status").status_code == 401
    assert "last_error" in cl.get("/api/v1/status", headers={"Authorization": "Bearer " + "x" * 20}).json()


# ------------------------------------------------------------------ security
@pytest.mark.parametrize("tok", ["", "change-me", "short", "password"])
def test_unsafe_tokens_refused(tok):
    with pytest.raises(SystemExit):
        assert_safe_token(tok)


def test_strong_token_accepted():
    assert_safe_token("k3J9-very-long-random-token-123")


# ------------------------------------------------------------------ client resilience
class _Resp:
    def __init__(self, code, body=None, headers=None):
        self.status_code, self._b, self.headers = code, body, headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code), response=self)

    def json(self):
        return self._b


def test_client_retries_then_succeeds(monkeypatch):
    c = ToobitClient(retries=2)
    seq = iter([_Resp(429, headers={"Retry-After": "0"}), _Resp(503), _Resp(200, {"ok": 1})])
    monkeypatch.setattr(c.s, "get", lambda *a, **k: next(seq))
    monkeypatch.setattr("renko_scalper.toobit.time.sleep", lambda s: None)
    assert c._get("/x") == {"ok": 1}


def test_client_gives_up_and_raises(monkeypatch):
    c = ToobitClient(retries=1)
    monkeypatch.setattr(c.s, "get", lambda *a, **k: _Resp(503))
    monkeypatch.setattr("renko_scalper.toobit.time.sleep", lambda s: None)
    with pytest.raises(requests.HTTPError):
        c._get("/x")


def test_klines_falls_back_to_from_to_on_400(monkeypatch):
    c = ToobitClient()
    calls = []

    def fake(path, params=None):
        calls.append(dict(params))
        if "startTime" in params:
            raise requests.HTTPError("400", response=_Resp(400))
        return [[1000, "1", "2", "0.5", "1.5", "10"]]

    monkeypatch.setattr(c, "_get", fake)
    out = c.klines("BTC-SWAP-USDT", "1m", 10)
    assert len(out) == 1 and "from" in calls[1] and "to" in calls[1] and "startTime" not in calls[1]


# ------------------------------------------------------------------ doctor
class GoodClient:
    def server_time(self):
        return int(time.time() * 1000)

    def contracts(self):
        from renko_scalper.models import MarketInfo
        return {f"S{i}-SWAP-USDT": MarketInfo(f"S{i}-SWAP-USDT", tick=0.01) for i in range(30)}

    def tickers_24h(self):
        return {f"S{i}-SWAP-USDT": {"qv": 1e7, "last": 1, "pcp": 0} for i in range(30)}

    def book_tickers(self):
        return {f"S{i}-SWAP-USDT": (1.0, 1.01) for i in range(30)}

    def klines(self, symbol, interval, limit, start_ms=None, end_ms=None):
        n = 1000 if start_ms else 200
        base = (int(time.time() * 1000) // 60_000 - n) * 60_000
        return [Candle(base + i * 60_000, 1, 1.1, 0.9, 1.05, 5) for i in range(n)]


def test_doctor_passes_on_healthy_exchange_and_flags_breakage():
    res = run_doctor(GoodClient(), load_config())
    assert all(ok for _, ok, _ in res), res

    class Broken(GoodClient):
        def klines(self, *a, **k):
            return [Candle(1000 + i * 60_000, 1, 0.5, 2, 1, 1) for i in range(300)]  # high < low: broken payload

        def server_time(self):
            return int(time.time() * 1000) - 60_000  # clock 60 s off
    bad = {n: ok for n, ok, _ in run_doctor(Broken(), load_config())}
    assert not bad["clock sync"] and not bad["klines live (BTC-SWAP-USDT)"]


# ------------------------------------------------------------------ validation verdicts
def _trades(rs, fee_r=0.05):
    return [{"ts": i, "r": r, "score": 75, "fee_r": fee_r} for i, r in enumerate(rs)]


def test_validate_says_no_go_on_thin_data():
    v = evaluate_trades(_trades([1, -1, 1, 1, -1] * 4), Criteria())
    assert not v.go and any("noise" in r for r in v.reasons)


def test_validate_says_no_go_on_coin_flip():
    rs = ([1.0, -1.0] * 150)  # exactly zero expectancy before costs
    v = evaluate_trades(_trades(rs), Criteria())
    assert not v.go


def test_validate_says_go_on_real_edge_and_stress_flips_marginal_edge():
    rs = ([2.0, 2.0, -1.0, 1.0, -1.0, 1.0] * 60)  # +0.67R expectancy, shallow drawdowns
    assert evaluate_trades(_trades(rs), Criteria()).go
    # a real but bumpy +0.28R edge is correctly refused: 49% odds of a 10R drawdown is not survivable
    bumpy = evaluate_trades(_trades([2.0, -1.0, -1.0, 2.0, 1.0, -1.0] * 60), Criteria())
    assert not bumpy.go and any("drawdown" in r for r in bumpy.reasons)
    marginal = ([1.0, -1.0, 1.0, -0.9] * 80)  # tiny gross edge that costs destroy
    assert not evaluate_trades(_trades(marginal, fee_r=0.12), Criteria()).go
    assert stressed(_trades([1.0], 0.1), 2.0, 0.05)[0]["r"] == pytest.approx(1.0 - 0.1 - 0.05)
