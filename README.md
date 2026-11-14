# Renko Scalper

Scans Toobit **USDT-M perpetual futures** for day-trading and scalping setups and alerts you on your iPhone.
Logic = **Renko** bricks + Miner's **dual-time-frame momentum** + **Wyckoff** price/volume reading + the Day Trader's Bible **cost rule**
(see [docs/STRATEGY.md](docs/STRATEGY.md) for the rule-by-rule mapping to the three books).

It uses public market data only: **no exchange API keys, no orders are ever placed.** Each alert gives side, entry, stop, TP1,
a trailing rule for the runner, and a position size for your risk budget. It also tracks each alert afterwards (TP1 hit, stopped, runner exit).

```
Toobit public API ──► scanner (Python) ──► SQLite ──► REST API ──► iOS app (list, Renko chart, local alerts)
                         │                                          
                         └──► Telegram / ntfy push (reliable alerts even when the app is closed)
```

## 1. Run the backend (your server or PC)

```bash
cd backend
pip install -r requirements.txt
cp config.example.yaml config.yaml       # set account.equity_usdt, api.token, notify.*
python -m renko_scalper -c config.yaml scan        # one-off ranking, prints to console
python -m renko_scalper -c config.yaml serve       # scanner + API on :8787
# or: docker compose up -d --build  (from the repo root, after creating backend/config.yaml)
```

From Iran you will likely need a proxy for Toobit and/or Telegram: `exchange.proxy: socks5h://127.0.0.1:1080`, `notify.telegram.proxy: ...`.
For ntfy, install the ntfy iOS app and subscribe to your topic. Put HTTPS in front of the API (Caddy / Cloudflare Tunnel) if the phone is outside your LAN.

### Before you risk a cent (in this order)

```bash
python -m renko_scalper -c config.yaml doctor                 # 1. does Toobit really answer the way the code assumes?
python -m renko_scalper -c config.yaml validate --days 30     # 2. GO / NO-GO: out-of-sample, fee-stressed, bootstrapped
python -m renko_scalper -c config.yaml serve                  # 3. run in PAPER mode (default) for 2-4 weeks, compare with step 2
```

Only when `validate` says GO **and** your paper results agree, set `alerts.paper: false` and start at 0.25-0.5% risk.
Full checklist and kill criteria: [docs/SURVIVAL.md](docs/SURVIVAL.md).

**Single-symbol backtest:**

```bash
python -m renko_scalper -c config.yaml backtest --symbol SOL-SWAP-USDT --profile scalp --days 14 --csv sol.csv
```

It replays the exact live logic walk-forward (fees, next-bar entry, stop-before-target) and prints win rate, average R, profit factor, drawdown.

## 2. Build the iOS app (.ipa)

**GitHub Actions (no Mac needed):** push this repo to GitHub → *Actions → Build iOS IPA* → download artifact `RenkoScalper-unsigned-ipa`.
If the build fails, download the `xcodebuild-log` artifact - that is the first thing to look at.
**Locally on a Mac:** `brew install xcodegen && ./scripts/build_ipa.sh` → `build/RenkoScalper.ipa`.

The IPA is **unsigned**. Install it with Sideloadly or AltStore (re-signs with your Apple ID; free accounts expire every 7 days) or TrollStore.
Then open the app → Settings → server URL (`http://host:8787`) and the API token.

### How alerts reach you (important)
* Sideloaded apps cannot receive Apple remote push (APNs needs a paid developer account and a signing identity). The app polls every 15 s while open and fires **local** notifications, plus a best-effort iOS background refresh (iOS decides when, often every 15+ minutes).
* For alerts that always arrive, enable **Telegram** or **ntfy** on the server - those are the reliable channel. The app is the dashboard (chart, levels, size, history).

## Layout

```
backend/renko_scalper/   renko.py · indicators.py · wyckoff.py · strategy.py · risk.py · trade.py · guard.py
                         toobit.py · scanner.py · store.py · notify.py · api.py · backtest.py · validate.py · doctor.py · cli.py
backend/tests/           44 tests (Renko rules, sizing, trade lifecycle, strategy gates, API, end-to-end with a fake exchange,
                         risk guard, dead-man's switch, client retries, doctor, go/no-go verdicts)
ios/                     XcodeGen project + SwiftUI app (iOS 16+)
.github/workflows/       ios-ipa.yml (macOS build) · backend-ci.yml
```

## Honest limits
* Verified here: the backend (44 passing tests on synthetic data). **Not verified here:** the Swift code (no Swift toolchain in my environment - the first CI run is its first compile) and live calls to Toobit (endpoints and response formats follow Toobit's current official API docs, but I could not reach the exchange). Expect to fix small things on first run.
* Fee defaults (0.06% taker / 0.02% maker) are the commonly published standard rates; check your tier.
* This is decision support for a high-risk activity. Leverage amplifies losses; start with paper trading, 1% risk or less.
