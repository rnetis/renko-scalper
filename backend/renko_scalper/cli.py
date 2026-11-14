from __future__ import annotations

import argparse
import logging
import threading

from .backtest import fetch_history, run_backtest, summarize, write_csv
from .config import INTERVAL_MS, assert_safe_token, load_config
from .scanner import Scanner, build_profiles
from .toobit import ToobitClient


def main() -> None:
    ap = argparse.ArgumentParser(prog="renko_scalper", description="Renko/Wyckoff/Miner scanner for Toobit USDT-M futures")
    ap.add_argument("-c", "--config", help="path to config.yaml (or set RS_CONFIG)")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="run scanner + HTTP API for the iOS app")
    sc = sub.add_parser("scan", help="one scan cycle, print the ranking")
    sc.add_argument("--top", type=int, default=10)
    bt = sub.add_parser("backtest", help="walk-forward backtest on recent history")
    bt.add_argument("--symbol", default="BTC-SWAP-USDT")
    bt.add_argument("--profile", default="scalp", choices=["scalp", "day"])
    bt.add_argument("--days", type=float, default=7)
    bt.add_argument("--csv")
    dc = sub.add_parser("doctor", help="verify every Toobit API assumption against the live exchange (run this first)")
    dc.add_argument("--notify", action="store_true", help="also send a test alert to Telegram/ntfy")
    dc.add_argument("--symbol", default="BTC-SWAP-USDT")
    va = sub.add_parser("validate", help="GO / NO-GO: out-of-sample, cost-stressed backtest over many symbols")
    va.add_argument("--profile", default="scalp", choices=["scalp", "day"])
    va.add_argument("--days", type=float, default=30)
    va.add_argument("--symbols", help="comma list; default = top --top symbols by 24h volume")
    va.add_argument("--top", type=int, default=12)
    va.add_argument("--workers", type=int, default=4)
    va.add_argument("--fee-mult", type=float, default=1.5)
    va.add_argument("--slippage-r", type=float, default=0.05)
    va.add_argument("--json", help="write the full report here")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)

    if args.cmd == "serve":
        assert_safe_token(cfg.api.token)
        import uvicorn
        from .api import create_app
        sc_ = Scanner(cfg)
        stop = threading.Event()
        threading.Thread(target=sc_.run_forever, args=(stop,), daemon=True).start()
        try:
            uvicorn.run(create_app(sc_), host=cfg.api.host, port=int(cfg.api.port), log_level="info")
        finally:
            stop.set()
    elif args.cmd == "scan":
        cfg.notify.console = False
        s = Scanner(cfg)
        setups = s.scan_once()
        print(f"{len(s.universe)} symbols scanned, {len(setups)} setups pass all gates")
        for x in setups[: args.top]:
            print(f"{x.score:3d} {x.grade} {x.side_name:5s} {x.style:5s} {x.symbol:18s} entry {x.entry:<12.6g} "
                  f"stop {x.stop:<12.6g} tp1 {x.tp1:<12.6g} costx {x.cost_multiple:4.1f}")
    elif args.cmd == "doctor":
        from .doctor import run_doctor
        from .notify import Dispatcher
        client = ToobitClient(cfg.exchange.base_url, cfg.exchange.proxy, cfg.exchange.timeout)
        res = run_doctor(client, cfg, args.symbol, args.notify, Dispatcher(cfg.notify))
        for name, ok, detail in res:
            print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
        if not all(ok for _, ok, _ in res):
            raise SystemExit("doctor found problems - fix these before trusting any alert")
        print("all checks passed")
    elif args.cmd == "validate":
        import json
        from .validate import Criteria, format_report, run_validation
        prof = build_profiles(cfg)[args.profile]
        client = ToobitClient(cfg.exchange.base_url, cfg.exchange.proxy, cfg.exchange.timeout)
        contracts = client.contracts()
        if args.symbols:
            syms = [x.strip() for x in args.symbols.split(",") if x.strip()]
        else:
            tick = client.tickers_24h()
            syms = [s for _, s in sorted(((tick.get(s, {}).get("qv", 0.0), s) for s in contracts), reverse=True)][: args.top]
        data, infos = {}, {}
        for sym in syms:
            if sym not in contracts:
                print(f"skip {sym}: not a tradable USDT-M contract")
                continue
            print(f"downloading {args.days}d of {prof.base_interval} for {sym} ...", flush=True)
            data[sym] = fetch_history(client, sym, prof.base_interval, args.days)
            infos[sym] = contracts[sym]
            infos[sym].qv24h = 1e12
        crit = Criteria(fee_mult=args.fee_mult, slippage_r=args.slippage_r)
        print(f"backtesting {len(data)} symbols (this takes a while) ...", flush=True)
        trades, verdict = run_validation(data, prof, infos, cfg, crit, workers=args.workers)
        print(format_report(verdict))
        if args.json:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump({"verdict": verdict.go, "reasons": verdict.reasons, "stats": verdict.stats, "symbols": syms,
                           "days": args.days, "profile": args.profile}, f, indent=2, default=str)
        raise SystemExit(0 if verdict.go else 2)
    elif args.cmd == "backtest":
        prof = build_profiles(cfg)[args.profile]
        client = ToobitClient(cfg.exchange.base_url, cfg.exchange.proxy, cfg.exchange.timeout)
        info = client.contracts().get(args.symbol)
        if info is None:
            raise SystemExit(f"{args.symbol} is not a tradable USDT-M contract")
        info.qv24h = 1e12  # historical run: liquidity gate not applied
        print(f"downloading {args.days}d of {prof.base_interval} candles for {args.symbol} ...")
        cs = fetch_history(client, args.symbol, prof.base_interval, args.days)
        print(f"{len(cs)} candles; running walk-forward ...")
        trades = run_backtest(args.symbol, cs, prof, info, cfg)
        print(summarize(trades, args.days))
        if args.csv:
            write_csv(args.csv, trades)


if __name__ == "__main__":
    main()
