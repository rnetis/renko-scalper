"""Renko brick construction.

Classic Renko rules:
  * a continuation brick forms when price moves one brick beyond the last brick's close;
  * a reversal brick needs price to move one brick beyond the last brick's OPEN,
    i.e. two bricks against the close - this is what filters most noise.

Bricks are built on absolute multiples of the brick size so the grid does not
shift when the candle window rolls forward.
"""
from __future__ import annotations

import threading
from typing import Iterable, Optional

from .models import Brick, Candle


def _path(c: Candle):
    """Intra-candle price path assumption (open -> extreme -> extreme -> close)."""
    if c.c >= c.o:
        return (c.o, c.l, c.h, c.c)
    return (c.o, c.h, c.l, c.c)


def quantize_size(raw: float, tick: float) -> float:
    """Round a raw brick size to a whole number of ticks (at least one tick)."""
    if raw <= 0:
        return 0.0
    if tick <= 0:
        return raw
    n = max(1, int(round(raw / tick)))
    return round(n * tick, 12)


def build_renko(candles: Iterable[Candle], size: float) -> list:
    bricks: list = []
    candles = list(candles)
    if size <= 0 or not candles:
        return bricks

    base = round(candles[0].o / size) * size
    last_o = last_c = base
    last_dir = 0
    acc_vol = 0.0
    acc_candles = 0

    for cndl in candles:
        acc_vol += cndl.v
        acc_candles += 1
        new_in_candle: list = []
        for p in _path(cndl):
            while True:
                if last_dir == 0:
                    if p >= last_c + size:
                        o, c, d = last_c, last_c + size, 1
                    elif p <= last_c - size:
                        o, c, d = last_c, last_c - size, -1
                    else:
                        break
                elif last_dir == 1:
                    if p >= last_c + size:
                        o, c, d = last_c, last_c + size, 1
                    elif p <= last_o - size:
                        o, c, d = last_o, last_o - size, -1
                    else:
                        break
                else:
                    if p <= last_c - size:
                        o, c, d = last_c, last_c - size, -1
                    elif p >= last_o + size:
                        o, c, d = last_o, last_o + size, 1
                    else:
                        break
                o, c = round(o, 10), round(c, 10)
                b = Brick(ts=cndl.ts, dir=d, o=o, c=c)
                new_in_candle.append(b)
                last_o, last_c, last_dir = o, c, d
        if new_in_candle:
            share = acc_vol / len(new_in_candle)
            for b in new_in_candle:
                b.vol = share
                b.candles = acc_candles
            bricks.extend(new_in_candle)
            acc_vol = 0.0
            acc_candles = 0
    return bricks


def last_run(bricks: list) -> tuple:
    """Return (direction, length) of the current run of same-direction bricks."""
    if not bricks:
        return 0, 0
    d = bricks[-1].dir
    n = 0
    for b in reversed(bricks):
        if b.dir != d:
            break
        n += 1
    return d, n


def prior_run(bricks: list):
    """The run immediately before the current one: (dir, length, first_idx, last_idx) or None."""
    if not bricks:
        return None
    _, cur_len = last_run(bricks)
    end = len(bricks) - cur_len - 1
    if end < 0:
        return None
    d = bricks[end].dir
    start = end
    while start - 1 >= 0 and bricks[start - 1].dir == d:
        start -= 1
    return d, end - start + 1, start, end


class StableSizes:
    """Keeps brick size steady (hysteresis) so the Renko chart does not repaint every scan."""

    def __init__(self, tolerance: float = 0.25):
        self.tol = tolerance
        self._sizes: dict = {}
        self._lock = threading.Lock()

    def get(self, key, raw: float, tick: float) -> float:
        q = quantize_size(raw, tick)
        if q <= 0:
            return 0.0
        with self._lock:
            cur = self._sizes.get(key)
            if cur and abs(q / cur - 1.0) <= self.tol:
                return cur
            self._sizes[key] = q
            return q

    def peek(self, key) -> Optional[float]:
        with self._lock:
            return self._sizes.get(key)
