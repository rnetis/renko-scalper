import time

from renko_scalper.backtest import run_backtest, summarize
from renko_scalper.config import INTERVAL_MS, load_config
from renko_scalper.indicators import resample
from renko_scalper.models import Candle, MarketInfo, Profile
from renko_scalper.notify import Dispatcher, signal_message
from renko_scalper.renko import StableSizes
from renko_scalper.scanner import Scanner
from renko_scalper.store import Store
from renko_scalper.strategy import evaluate, momentum_permit
from synth import gen_candles, trending

PROF = Profile("scalp", "1m", 60_000, 300_000)
MKT = MarketInfo("T-SWAP-USDT", qv24h=1e9, bid=99.99, ask=100.0, tick=0.01)


def _scan(data, cfg=None, mkt=MKT):
    cfg = cfg or load_config()
    sizes = StableSizes()
    out = []
    for i in range(300, len(data)):
        ltf = data[: i + 1][-600:]
        s = evaluate("T-SWAP-USDT", ltf, resample(ltf, 300_000), PROF, mkt, cfg, sizes)
        if s:
            out.append(s)
    return out


def test_momentum_table():
    assert momentum_permit({"bull": True, "ob": False, "os": False}, 1) == "trend"
    assert momentum_permit({"bull": True, "ob": True, "os": False}, 1) is None
    assert momentum_permit({"bull": True, "ob": True, "os": False}, -1) == "reversal"
    assert momentum_permit({"bull": False, "ob": False, "os": True}, 1) == "reversal"
    assert momentum_permit({"bull": False, "ob": False, "os": True}, -1) is None


def test_setup_invariants_up_and_down():
    for up in (True, False):
        data = trending(900, up, step_pct=0.004, noise=0.0015)
        setups = _scan(data)
        assert setups, "expected setups in a clean staircase trend"
        for s in setups:
            assert (s.stop < s.entry < s.tp1) if s.side > 0 else (s.tp1 < s.entry < s.stop)
            assert 0 <= s.score <= 100 and s.cost_multiple >= 3.0
        majority = sum(1 for s in setups if (s.side > 0) == up) / len(setups)
        assert majority > 0.7


def test_cost_filter_blocks_tiny_moves():
    # same shape but microscopic volatility: moves cannot cover fees -> nothing passes
    data = trending(900, True, step_pct=0.00005, noise=0.00002)
    assert _scan(data) == []


def test_liquidity_and_spread_gates():
    data = trending(900, True, step_pct=0.004, noise=0.0015)
    assert _scan(data, mkt=MarketInfo("T", qv24h=1_000, bid=99.99, ask=100.0, tick=0.01)) == []
    assert _scan(data, mkt=MarketInfo("T", qv24h=1e9, bid=90, ask=100, tick=0.01)) == []


def test_backtest_runs_and_is_deterministic():
    data = trending(1500, True, step_pct=0.004, noise=0.0015)
    cfg = load_config()
    cfg.alerts.min_score = 50
    t1 = run_backtest("T-SWAP-USDT", data, PROF, MKT, cfg)
    t2 = run_backtest("T-SWAP-USDT", data, PROF, MKT, cfg)
    assert t1 == t2
    s = summarize(t1, 1.0)
    assert s["trades"] > 0 and -10 < s["avg_r"] < 10


def _aligned(raw, n):
    """First n synthetic candles re-timed so the last one closed during the previous minute."""
    end_open = (int(time.time() * 1000) // 60_000 - 1) * 60_000
    t0 = end_open - (n - 1) * 60_000
    return [Candle(t0 + k * 60_000, c.o, c.h, c.l, c.c, c.v) for k, c in enumerate(raw[:n])]


class FakeClient:
    """Serves synthetic 1m candles (ending 'just closed') in place of Toobit."""

    def __init__(self, cfg):
        raw = trending(800, True, step_pct=0.004, noise=0.0015)
        for n in range(300, 800):
            d = _aligned(raw, n)
            st = evaluate("T-SWAP-USDT", d[-600:], resample(d[-600:], 300_000), PROF, MKT, cfg, StableSizes())
            if st and st.score >= 40:
                self.data1 = d
                return
        raise AssertionError("no trigger found in synthetic data")

    def contracts(self):
        return {"T-SWAP-USDT": MarketInfo("T-SWAP-USDT", tick=0.01, step=0.001, min_qty=0.001, min_notional=5)}

    def tickers_24h(self):
        return {"T-SWAP-USDT": {"qv": 1e9, "last": 100, "pcp": 1}}

    def book_tickers(self):
        return {"T-SWAP-USDT": (99.99, 100.0)}

    def klines(self, symbol, interval, limit, start_ms=None, end_ms=None):
        return self.data1 if interval == "1m" else []


def test_scanner_end_to_end_with_fake_exchange(tmp_path):
    cfg = load_config()
    cfg.storage.db_path = str(tmp_path / "s.db")
    cfg.profiles.day.enabled = False
    cfg.alerts.min_score = 40
    cfg.alerts.cooldown_min.scalp = 0
    cfg.notify.console = False
    sent = []

    class Rec(Dispatcher):
        def send(self, title, body, priority="default"):
            sent.append((title, body))

    sc = Scanner(cfg, client=FakeClient(cfg), store=Store(cfg.storage.db_path), dispatcher=Rec(cfg.notify))
    sc.scan_once()
    rows = sc.store.list()
    assert sc.universe == ["T-SWAP-USDT"]
    assert rows, "scanner must store at least one signal"
    assert sc.watch, "watchlist must be populated"
    assert sent and "LONG" in sent[0][0] and "Entry" in sent[0][1] and "Stop" in sent[0][1]
    assert rows[0]["payload"]["sizing"]["qty"] > 0
    view = sc.renko_view("T-SWAP-USDT", "scalp", "ltf", 40)
    assert view and view["bricks"] and view["size"] > 0
    # second cycle: same trigger key must not alert twice
    n = len(sent)
    sc.scan_once()
    assert len(sent) == n
