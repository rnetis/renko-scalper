from renko_scalper.models import Candle, MarketInfo
from renko_scalper.risk import size_position
from renko_scalper.trade import advance, new_trade


def C(ts, o, h, l, c):
    return Candle(ts, o, h, l, c, 1.0)


def test_miner_position_size_example():
    # Miner: $50,000 capital, 3% max exposure, $21.05 per-unit exposure -> ~71 shares (book rounds to 72)
    r = size_position(50_000, 3.0, 526.83, 505.78, 0.0)
    assert r and 71 <= r["qty"] <= 72


def test_risk_capped_at_three_percent_and_fees_included():
    r = size_position(1000, 50.0, 100.0, 99.0, 0.06)
    assert r["risk_usdt"] <= 30.0 + 1e-6
    r2 = size_position(1000, 1.0, 100.0, 99.0, 0.06)
    assert abs(r2["risk_usdt"] - 10.0) < 0.01


def test_exchange_minimums():
    m = MarketInfo("X", step=0.001, min_qty=0.5, min_notional=10)
    ok = size_position(100, 1.0, 100.0, 99.0, 0.0, m)
    assert ok and abs(ok["qty"] - 1.0) < 1e-9
    assert size_position(100, 1.0, 100.0, 99.99, 0.0, MarketInfo("X", step=0.001, min_qty=500)) is None


def test_trade_stopped_before_tp1():
    st = new_trade(1, 100, 99, 101, 0.5, 0.0)
    ev = advance(st, C(1, 100, 100.5, 98.9, 99.2))
    assert ev == ["stopped"] and st.status == "closed" and abs(st.result_r + 1) < 1e-9


def test_stop_beats_target_in_same_candle():
    st = new_trade(1, 100, 99, 101, 0.5, 0.0)
    ev = advance(st, C(1, 100, 102, 98.5, 100))
    assert ev == ["stopped"]


def test_tp1_then_trailing_runner_exit():
    st = new_trade(1, 100, 99, 101, 0.5, 0.0)
    assert advance(st, C(1, 100, 101.2, 100, 101)) == ["tp1"]
    assert st.stop >= 100  # at breakeven
    advance(st, C(2, 101, 103, 101, 102.8))  # extreme 103 -> trail 102
    assert abs(st.stop - 102.0) < 1e-9
    ev = advance(st, C(3, 102.8, 102.9, 101.5, 101.6))
    assert ev == ["runner_exit"]
    assert abs(st.result_r - (0.5 * 1.0 + 0.5 * 2.0)) < 1e-9


def test_short_side_mirrors():
    st = new_trade(-1, 100, 101, 99, 0.5, 0.0)
    assert advance(st, C(1, 100, 100.2, 98.9, 99.1)) == ["tp1"]
    ev = advance(st, C(2, 99.1, 101.5, 99, 101))
    assert ev == ["runner_exit"] and st.result_r > 0


def test_gap_through_stop_fills_at_open():
    st = new_trade(1, 100, 99, 101, 0.5, 0.0)
    advance(st, C(1, 97, 98, 96, 97))
    assert st.result_r < -1.5  # gap worse than 1R


def test_fees_reduce_result():
    st = new_trade(1, 100, 99, 101, 0.5, 0.06)
    advance(st, C(1, 100, 100.5, 98.9, 99.2))
    assert st.result_r < -1.0
