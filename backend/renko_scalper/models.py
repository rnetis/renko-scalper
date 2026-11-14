from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass(frozen=True)
class Candle:
    ts: int  # open time, ms
    o: float
    h: float
    l: float
    c: float
    v: float


@dataclass
class Brick:
    ts: int  # candle open-time (ms) in which the brick formed
    dir: int  # +1 up, -1 down
    o: float
    c: float
    vol: float = 0.0
    candles: int = 1  # candles it took to form

    @property
    def high(self) -> float:
        return max(self.o, self.c)

    @property
    def low(self) -> float:
        return min(self.o, self.c)


@dataclass
class MarketInfo:
    symbol: str
    qv24h: float = 0.0  # 24h quote volume (USDT)
    bid: float = 0.0
    ask: float = 0.0
    tick: float = 0.0
    step: float = 0.0
    min_qty: float = 0.0
    min_notional: float = 0.0

    @property
    def spread_pct(self) -> Optional[float]:
        if self.bid > 0 and self.ask > 0 and self.ask >= self.bid:
            mid = (self.bid + self.ask) / 2
            return (self.ask - self.bid) / mid * 100
        return None


@dataclass
class Profile:
    name: str  # "scalp" | "day"
    base_interval: str  # exchange interval string fetched for this profile
    ltf_ms: int
    htf_ms: int
    ltf_atr_mult: float = 1.0
    htf_atr_mult: float = 1.0
    max_age_candles: int = 2  # trigger must be this fresh
    max_stop_bricks: float = 4.0
    tp1_r: float = 1.0
    max_hold_candles: int = 90


@dataclass
class Setup:
    key: str
    symbol: str
    style: str
    side: int  # +1 long, -1 short
    score: int
    grade: str
    ts: int  # ts of last closed ltf candle
    price: float
    entry: float
    stop: float
    tp1: float
    brick_ltf: float
    brick_htf: float
    risk_dist: float
    cost_multiple: float
    net_rr1: float
    reasons: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    ltf_ms: int = 60_000
    max_hold_candles: int = 90

    @property
    def side_name(self) -> str:
        return "LONG" if self.side > 0 else "SHORT"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["side_name"] = self.side_name
        return d
