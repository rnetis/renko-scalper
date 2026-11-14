from __future__ import annotations

import copy
import os
from types import SimpleNamespace
from typing import Optional

import yaml

DEFAULTS: dict = {
    "exchange": {"base_url": "https://api.toobit.com", "proxy": None, "timeout": 10},
    "universe": {
        "max_symbols": 40,
        "min_quote_volume_usdt": 20_000_000,
        "exclude": [],
        "include_only": [],
        "refresh_sec": 300,
    },
    "account": {
        "equity_usdt": 1000.0,
        "risk_per_trade_pct": 1.0,  # hard-capped at 3.0 in risk.py
        "max_leverage": 20,
    },
    # Verify against your own VIP tier. Round-trip cost assumes taker both ways (conservative).
    "fees": {"taker_pct": 0.06, "maker_pct": 0.02},
    "filters": {
        "max_spread_pct": 0.05,
        "default_spread_pct": 0.03,  # used when bookTicker is unavailable
        "min_move_cost_multiple": 3.0,  # TP1 distance must be >= this x round-trip cost
        "allow_extended_trend": True,  # allow trend entries when HTF stochastic is pinned OB/OS (flagged)
    },
    "profiles": {
        "scalp": {"enabled": True, "ltf": "1m", "htf": "5m", "ltf_atr_mult": 1.0, "htf_atr_mult": 1.0,
                  "max_age_candles": 2, "max_stop_bricks": 4.0, "tp1_r": 1.0, "max_hold_candles": 90},
        "day": {"enabled": True, "ltf": "5m", "htf": "15m", "ltf_atr_mult": 1.0, "htf_atr_mult": 1.0,
                "max_age_candles": 2, "max_stop_bricks": 4.0, "tp1_r": 1.0, "max_hold_candles": 144},
    },
    "alerts": {
        "paper": True,  # tag every alert [PAPER]; set false only after `validate` says GO
        "min_score": 70,
        "watch_min_score": 50,
        "top_n": 3,
        "cooldown_min": {"scalp": 15, "day": 60},
    },
    # Account-level circuit breakers: new alerts are suppressed while any of these trips.
    "guard": {
        "enabled": True,
        "max_active": 3,  # tracked signals open at once
        "max_same_side": 2,  # crypto alts are highly correlated: do not stack the same direction
        "daily_loss_limit_r": 3.0,  # stop for the UTC day after losing this many R
        "consecutive_losses": 3,  # N losers in a row ...
        "pause_min": 60,  # ... pauses new alerts for this long
    },
    # Dead-man's switch: tells you when the scanner cannot see the market, so you never trust silence.
    "watchdog": {"fail_cycles": 4, "ping_url": ""},  # ping_url: healthchecks.io-style URL, hit after each good cycle
    "scan": {"interval_sec": 30},
    "notify": {
        "console": True,
        "telegram": {"token": "", "chat_id": "", "proxy": None},
        "ntfy": {"server": "https://ntfy.sh", "topic": "", "token": ""},
    },
    "api": {"host": "0.0.0.0", "port": 8787, "token": "change-me"},
    "storage": {"db_path": "data/signals.db"},
}

_ENV = {
    "RS_PROXY": ("exchange", "proxy"),
    "RS_EQUITY": ("account", "equity_usdt"),
    "RS_API_TOKEN": ("api", "token"),
    "RS_TG_TOKEN": ("notify", "telegram", "token"),
    "RS_TG_CHAT": ("notify", "telegram", "chat_id"),
    "RS_TG_PROXY": ("notify", "telegram", "proxy"),
    "RS_NTFY_SERVER": ("notify", "ntfy", "server"),
    "RS_NTFY_TOPIC": ("notify", "ntfy", "topic"),
    "RS_NTFY_TOKEN": ("notify", "ntfy", "token"),
    "RS_DB": ("storage", "db_path"),
    "RS_PING_URL": ("watchdog", "ping_url"),
}


def _merge(a: dict, b: dict) -> dict:
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _ns(d):
    if isinstance(d, dict):
        return SimpleNamespace(**{k: _ns(v) for k, v in d.items()})
    return d


def load_config(path: Optional[str] = None) -> SimpleNamespace:
    data = copy.deepcopy(DEFAULTS)
    path = path or os.environ.get("RS_CONFIG")
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = _merge(data, yaml.safe_load(f) or {})
    for env, keys in _ENV.items():
        val = os.environ.get(env)
        if val in (None, ""):
            continue
        node = data
        for k in keys[:-1]:
            node = node[k]
        if keys[-1] == "equity_usdt":
            val = float(val)
        node[keys[-1]] = val
    return _ns(data)


# candles fetched per interval; shared by the live scanner and the backtester so they see the same window
FETCH_LIMIT = {"1m": 720, "5m": 500, "15m": 400}

INSECURE_TOKENS = {"", "change-me", "changeme", "secret", "token", "password"}


def assert_safe_token(token: str) -> None:
    """Refuse to expose the API with a placeholder/short token."""
    if (token or "").strip().lower() in INSECURE_TOKENS or len(token or "") < 16:
        raise SystemExit(
            "Refusing to start the API: set a strong api.token (>=16 chars) in config.yaml or RS_API_TOKEN.\n"
            "  generate one:  python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )


INTERVAL_MS = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000}
