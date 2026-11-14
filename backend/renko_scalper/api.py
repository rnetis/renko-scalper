from __future__ import annotations

import hmac
import time
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query

from .scanner import Scanner


def _age(created_ms: int, ltf_ms: int) -> float:
    return (time.time() * 1000 - created_ms) / ltf_ms


def _public(row: dict) -> dict:
    p = dict(row["payload"])
    t = row["trade"]
    p.update({
        "id": row["id"], "status": row["status"], "created_ts": row["created_ms"],
        "age_candles": round(_age(row["created_ms"], p.get("ltf_ms", 60_000)), 2),
        "current_stop": t.get("stop"), "tp1_hit": t.get("tp1_hit", False), "result_r": t.get("result_r"),
    })
    return p


def create_app(scanner: Scanner) -> FastAPI:
    cfg = scanner.cfg
    app = FastAPI(title="Renko Scalper", version="1.0.0")

    def auth(authorization: Optional[str] = Header(default=None)) -> None:
        token = cfg.api.token or ""
        got = (authorization or "").removeprefix("Bearer ").strip()
        if not token or not hmac.compare_digest(got, token):
            raise HTTPException(status_code=401, detail="invalid token")

    @app.get("/api/v1/health")
    def health():
        # unauthenticated: only what a load balancer / uptime monitor needs
        return {"ok": not scanner.degraded, "degraded": scanner.degraded, "last_scan_ts": scanner.last_scan_ms,
                "server_time": int(time.time() * 1000)}

    @app.get("/api/v1/status", dependencies=[Depends(auth)])
    def status():
        return {"cycles": scanner.cycles, "symbols": len(scanner.universe), "last_scan_ts": scanner.last_scan_ms,
                "last_ok_ts": scanner.last_ok_ms, "bad_cycles": scanner.bad_cycles, "degraded": scanner.degraded,
                "guard_pause": scanner.guard_reason, "paper": bool(cfg.alerts.paper),
                "last_error": scanner.last_error, "server_time": int(time.time() * 1000)}

    @app.get("/api/v1/signals", dependencies=[Depends(auth)])
    def signals(since_id: int = 0, limit: int = Query(30, le=200), status: Optional[str] = None):
        rows = scanner.store.list(since_id=since_id, limit=limit, status=status)
        return {"signals": [_public(r) for r in rows], "last_scan_ts": scanner.last_scan_ms,
                "server_time": int(time.time() * 1000), "min_score": cfg.alerts.min_score}

    @app.get("/api/v1/signals/{sid}", dependencies=[Depends(auth)])
    def one(sid: int):
        r = scanner.store.get(sid)
        if not r:
            raise HTTPException(404, "not found")
        return _public(r)

    @app.get("/api/v1/watchlist", dependencies=[Depends(auth)])
    def watchlist():
        with scanner._lock:
            items = list(scanner.watch)
        return {"items": items, "last_scan_ts": scanner.last_scan_ms, "min_score": cfg.alerts.min_score,
                "server_time": int(time.time() * 1000)}

    @app.get("/api/v1/renko", dependencies=[Depends(auth)])
    def renko(symbol: str, style: str = "scalp", tf: str = "ltf", limit: int = Query(80, le=300)):
        if tf not in ("ltf", "htf"):
            raise HTTPException(400, "tf must be ltf|htf")
        v = scanner.renko_view(symbol, style, tf, limit)
        if v is None:
            raise HTTPException(404, "no data for symbol/style")
        return v

    return app
