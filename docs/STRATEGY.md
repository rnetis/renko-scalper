# Strategy: how the three books became rules

Every alert is a conjunction of **hard gates** (all must pass) and a **0-100 score** (used for ranking).
Nothing here predicts price; it filters for situations the books argue have better odds and survivable costs.

## Sources → rules

| Rule in code | Source idea (paraphrased) |
|---|---|
| Two time frames: HTF decides which side is allowed, LTF supplies the trigger (`strategy.momentum_permit`, `indicators.momentum`) | Miner, *High Probability Trading Strategies*, ch. 2 - the Dual Time Frame Momentum table. Bull and not overbought → longs after an LTF bullish reversal; bull and overbought → no new longs; mirrored for bear/oversold. A momentum "reversal" is the fast line crossing the slow line. |
| Pinned overbought/oversold exception (`allow_extended_trend`) | Not from the book. Stochastics sit in the extreme zone for long stretches of a strong trend (Miner notes this too), which would silence a trend scanner. When the HTF Renko run is ≥3 bricks with the trade, the signal is allowed, scored low and flagged. Set `false` for the strict table. |
| Entry only after the market confirms (Renko reversal brick; price must not be >1 brick beyond it) (`strategy.evaluate`) | Miner ch. 6 - enter only after price takes out a bar high/low following the reversal, never in anticipation. |
| Stop one tick beyond the swing made before entry; reject if wider than `max_stop_bricks` | Miner ch. 6 - the stop is structural and known before entry, so exposure is known. |
| Position size = equity × risk% ÷ per-unit loss (incl. taker fees), risk hard-capped at 3% (`risk.size_position`) | Miner ch. 6 - capital preservation; ≤3% per trade, ≤6% across open trades. Defaults to 1%. The 6% total is a discipline rule: the scanner cannot know which signals you actually took. |
| Two units: TP1 at 1R then breakeven stop; runner trailed and only closed when the market takes it out (`trade.py`) | Miner ch. 7 - two-unit trading, let the market exit you, base the exit on the same conditions as the entry. Wyckoff (Day Trader's Bible) - once the stop covers costs, stop forcing it. |
| TP1 must be ≥ `min_move_cost_multiple` × round-trip cost; spread cap; liquidity floor | Wyckoff, *Day Trader's Bible*, ch. IV - commissions and the bid/ask gap are paid on every trade, a small-swing market cannot pay them, each trade needs a profit potential several times its cost. Here the cost is 2×taker fee + spread. **This is why most BTC 1-minute scalps are rejected: the move does not clear fees.** |
| Trade with the immediate trend; avoid dead markets | Day Trader's Bible ch. IV. HTF Renko direction/run adds the most points. |
| Significant bar: wide range, higher volume, close in the direction half, close beyond the prior level (`wyckoff.significant_bar`) | Villahermosa, *The Wyckoff Methodology in Depth*, ch. 27 - the objective sign of institutional intent. |
| Spring / Upthrust: a range extreme is pierced and reclaimed (`wyckoff.shake`); low-volume shakes score more, high-volume ones are flagged "wait for the test" | Methodology ch. 18/26 - shakes are the best-R:R area (Phase C) but a high-volume shake is usually retested first. |
| Effort vs result (`wyckoff.effort_result`) | Methodology ch. 9 - harmony confirms a move; heavy volume with no progress signals absorption (selling absorbed after a decline = bullish). |
| Reversal-brick volume vs. recent bricks | Same effort/result idea applied to Renko bricks. |

## Renko details

* Brick size = ATR(14) of that time frame × multiplier, rounded to a whole number of ticks, with 25% hysteresis so the chart does not repaint every scan. Bricks sit on absolute multiples of the size.
* A reversal brick needs two bricks of movement against the last close - this is the noise filter.
* A trigger is the first or second brick after a counter-run (run length ≤2) that formed ≤`max_age_candles` ago. Only **closed** candles are used (no repainting; a 1m signal can lag up to a minute).
* Renko discards time. Volume per brick is the volume of the candles it took to form.

## Score (max 100)

HTF Renko with the trade 20/12 · HTF momentum permit 15 (reversal 8, extended 4) · LTF momentum reversal 15 · 2nd-brick confirmation 5 · significant bar 10 · spring/upthrust 10 (4 if high volume) · effort/result ±5 · reversal-brick volume 5 · TP1 ≥6× costs 10 (≥ minimum 5) · very liquid and tight 5.
Grade A ≥80, B ≥70. Default alert threshold 70.

## What this does *not* do

* It does not know the future. The books themselves say good traders win well under half the time and survive on small losses; expect losing streaks.
* Renko and stochastics lag; fast spikes and news will blow through stops (gaps fill worse than the stop).
* Crypto trades 24/7 with thin weekends and funding payments; funding is not yet in the score.
* Backtests on past data are not evidence about the future. Run `backtest` on the symbols you care about, then paper-trade before using money.
