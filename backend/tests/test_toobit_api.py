from fastapi.testclient import TestClient

from renko_scalper.api import create_app
from renko_scalper.config import load_config
from renko_scalper.notify import Dispatcher
from renko_scalper.scanner import Scanner
from renko_scalper.store import Store
from renko_scalper.toobit import ToobitClient, closed_only, parse_klines
from renko_scalper.models import Candle


def test_parse_klines_list_and_dict_and_dedupe():
    rows = [[2000, "1", "2", "0.5", "1.5", "10", 0, "15", 3, "5", "7"],
            [1000, "1", "2", "0.5", "1.2", "9"],
            [2000, "1", "2", "0.5", "1.6", "11"],
            {"t": 3000, "o": "1", "h": "2", "l": "1", "c": "1.1", "v": "4"}]
    out = parse_klines(rows)
    assert [c.ts for c in out] == [1000, 2000, 3000] and out[1].c == 1.6


def test_closed_only():
    cs = [Candle(0, 1, 1, 1, 1, 1), Candle(60_000, 1, 1, 1, 1, 1)]
    assert len(closed_only(cs, 60_000, now_ms=90_000)) == 1


def test_contracts_filtering(monkeypatch):
    c = ToobitClient()
    sample = {"contracts": [
        {"symbol": "BTC-SWAP-USDT", "status": "TRADING", "inverse": False, "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.1"},
            {"filterType": "LOT_SIZE", "stepSize": "0.0001", "minQty": "0.0001"},
            {"filterType": "MIN_NOTIONAL", "minNotional": "10"}]},
        {"symbol": "BTC-SWAP", "status": "TRADING", "inverse": True, "filters": []},
        {"symbol": "ETH-SWAP-USDT", "status": "OFFLINE", "inverse": False, "filters": []}]}
    monkeypatch.setattr(c, "_get", lambda *a, **k: sample)
    out = c.contracts()
    assert list(out) == ["BTC-SWAP-USDT"] and out["BTC-SWAP-USDT"].tick == 0.1 and out["BTC-SWAP-USDT"].min_notional == 10


def test_klines_sends_time_window(monkeypatch):
    c = ToobitClient()
    seen = {}
    monkeypatch.setattr(c, "_get", lambda path, params=None: seen.update(params=params) or [])
    c.klines("BTC-SWAP-USDT", "1m", 100)
    assert {"startTime", "endTime", "limit", "symbol", "interval"} <= set(seen["params"])


def test_api_auth_and_endpoints(tmp_path):
    cfg = load_config()
    cfg.storage.db_path = str(tmp_path / "a.db")
    cfg.api.token = "secret"
    sc = Scanner(cfg, client=object(), store=Store(cfg.storage.db_path), dispatcher=Dispatcher(cfg.notify))
    payload = {"symbol": "X-SWAP-USDT", "style": "scalp", "side": 1, "score": 80, "side_name": "LONG", "ltf_ms": 60000}
    sc.store.insert("k1", payload, {"stop": 1.0})
    cl = TestClient(create_app(sc))
    assert cl.get("/api/v1/health").status_code == 200
    assert cl.get("/api/v1/signals").status_code == 401
    assert cl.get("/api/v1/signals", headers={"Authorization": "Bearer nope"}).status_code == 401
    h = {"Authorization": "Bearer secret"}
    r = cl.get("/api/v1/signals", headers=h).json()
    assert r["signals"][0]["symbol"] == "X-SWAP-USDT" and r["signals"][0]["status"] == "open"
    assert cl.get("/api/v1/signals/1", headers=h).status_code == 200
    assert cl.get("/api/v1/signals/99", headers=h).status_code == 404
    assert cl.get("/api/v1/watchlist", headers=h).status_code == 200
    assert cl.get("/api/v1/renko?symbol=NOPE", headers=h).status_code == 404
