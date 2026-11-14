from renko_scalper.indicators import atr, momentum, resample, stochastic
from renko_scalper.models import Candle
from renko_scalper.renko import StableSizes, build_renko, last_run, prior_run, quantize_size


def C(ts, o, h, l, c, v=1.0):
    return Candle(ts, o, h, l, c, v)


def test_up_bricks_and_two_brick_reversal():
    # steady climb 100 -> 130 with size 10, then fall
    cs = [C(0, 100, 100, 100, 100), C(1, 100, 131, 100, 130)]
    b = build_renko(cs, 10)
    assert [x.dir for x in b] == [1, 1, 1]
    assert (b[-1].o, b[-1].c) == (120, 130)
    # a drop of one brick from the last close (to 120) is NOT a reversal
    b2 = build_renko(cs + [C(2, 130, 130, 120, 120)], 10)
    assert b2[-1].dir == 1 and len(b2) == 3
    # a drop to 110 (open of last brick 120 minus 10) is
    b3 = build_renko(cs + [C(2, 130, 130, 110, 110)], 10)
    assert b3[-1].dir == -1 and (b3[-1].o, b3[-1].c) == (120, 110)


def test_small_moves_make_no_bricks():
    cs = [C(i, 100, 101, 99, 100.5) for i in range(50)]
    assert build_renko(cs, 10) == []


def test_runs():
    cs = [C(0, 100, 100, 100, 100), C(1, 100, 131, 100, 130), C(2, 130, 130, 100, 100)]
    b = build_renko(cs, 10)
    d, n = last_run(b)
    assert d == -1 and n >= 1
    pr = prior_run(b)
    assert pr is not None and pr[0] == 1


def test_quantize_and_stable_sizes():
    assert quantize_size(0.0234, 0.01) == 0.02
    assert quantize_size(0.001, 0.01) == 0.01
    s = StableSizes(0.25)
    a = s.get("k", 2.0, 0.01)
    assert s.get("k", 2.3, 0.01) == a  # within tolerance -> unchanged
    assert s.get("k", 3.5, 0.01) != a  # beyond -> refreshed


def test_atr_and_stochastic_bounds():
    cs = [C(i, 100 + i % 5, 102 + i % 5, 98 + i % 5, 100 + (i * 7) % 5) for i in range(80)]
    assert atr(cs) > 0
    k, d = stochastic(cs)
    vals = [x for x in k + d if x is not None]
    assert vals and all(0 <= x <= 100 for x in vals)
    m = momentum(cs)
    assert m is not None and m["rev_dir"] in (-1, 0, 1)


def test_resample_drops_incomplete_bucket():
    one = [C(i * 60_000, 1, 2, 0.5, 1.5, 10) for i in range(12)]  # 12 one-minute bars
    r = resample(one, 300_000)
    assert len(r) == 2  # 10 complete minutes -> 2 five-minute bars; last 2 minutes incomplete
    assert r[0].v == 50
