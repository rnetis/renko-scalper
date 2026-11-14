# Survival guide: treat this as a live-or-dead situation

A signal scanner cannot make you money by itself. It can only (a) show you a statistical edge, if one exists, and
(b) keep you alive long enough to find out. Most retail futures accounts die from three things: **trading an
unproven edge, oversizing, and not noticing the tool went blind.** This repo now has a defence against each.

## The three gates (all must pass before real money)

| Gate | Command | Passes when |
|---|---|---|
| 1. Plumbing | `doctor` | every check PASS (clock, contracts, tickers, books, live + historical klines) |
| 2. Edge | `validate --days 30` (then 60, 90) | verdict GO: >=100 trades, out-of-sample avg R > +0.05 after 1.5x fees and slippage, profit factor >= 1.15, bootstrapped 5th-percentile expectancy > 0, in/out-of-sample agree, P(10R drawdown in 200 trades) <= 20% |
| 3. Reality | 2-4 weeks of paper alerts | paper R within ~0.15R of the backtest, and you actually took every alert on time |

`validate` exits non-zero on NO-GO, so you can script it. Re-run it monthly: edges decay.

## Built-in defences

* **Paper mode is the default** (`alerts.paper: true`): every alert is tagged `[PAPER]`.
* **Risk guard** (`guard.*`): max 3 open signals, max 2 on the same side (alts move together), stop for the day at -3R, 1h pause after 3 straight losses. Pauses are announced once, not spammed.
* **Dead-man's switch** (`watchdog.*`): if market data is stale or failing for ~2 minutes you get an *urgent* "scanner BLIND" alert, and a "recovered" one later. Set `watchdog.ping_url` to a healthchecks.io / Uptime-Kuma push URL so that even a dead server or dead network pages you.
* **Exchange stop orders are mandatory.** Every alert says so. This tool only *tracks*; if it dies, a stop that lives only in your head is no stop.
* **Fail closed on security**: the API refuses to start with a placeholder token, compose binds to localhost, and public `/health` leaks nothing.
* **Live == backtest**: same candle window, same trade lifecycle, same time-exit maths.

## Kill criteria (write these down before you start, then obey them)

1. Live R over the last 50 alerts is negative after fees -> back to paper, re-run `validate`.
2. Drawdown reaches 10R (about 10% at 1% risk) -> stop for a week and review every loser.
3. `doctor` starts failing, or Toobit changes its API -> no trading until it passes.
4. You skip stops, move stops, or add to losers -> stop. That is not the strategy anymore.

## Sizing rules of thumb

* 0.25-0.5% risk per trade until 100+ live trades agree with the backtest; never above 1%.
* Isolated margin only. The leverage hint keeps liquidation far beyond the stop (about 50% price distance/leverage-limited); do not raise it.
* Funding is not modelled. For `day` trades held across a funding time, check the rate.

## What this still cannot tell you

* Whether the three books' rules, as encoded here, have a real edge on Toobit. Only `validate` on live data can, and it may say NO-GO. That is a successful outcome: it cost you nothing.
* Swift/iOS code was never compiled by the author or in this review; the first CI run is its first build.
