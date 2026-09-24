# Runner status

Refreshed by Claude Code whenever the runners are checked. Counts only: no
returns, no z-scores, no outcomes are read to produce this file.

**As of 2026-09-24 04:15 UTC**

## ethfilter (this repo, public)

| | |
|---|---|
| Run id | `2026-09-21-insentos-v3-robinhood` |
| Chain | robinhood (chain id 4663) |
| Collecting since | 2026-09-22 00:31 UTC (2.2 days) |
| Scheduled runs, last 24h | 92 |
| Failures | 0 |
| GeckoTerminal calls, last 24h | 459, of which 0 throttled (0%) |
| Runs halted on throttling | 0 |

Pools seen: **7,266**

| Arm | Count |
|---|---|
| pending | 151 |
| untradeable | 5,829 |
| pass | 115 |
| reject | 1,171 |

Untradeable, by first failing check: 1h volume 3,561; liquidity 1,823; sellers
432; spoofed liquidity 13.

Gates: **Q1 pass 49/100, reject 669/100. Q2 paths 0/150.** No verdict is issued
below those, and Q2 cannot produce a path before 2026-09-29, seven days after
collection started. Regime split counts: 1,286 evaluated before 2026-09-30, 0
after.

## socialarb (separate private repo)

| | |
|---|---|
| Last session logged | 2026-09-23 |
| That run started | 18:15 Pacific, inside the 18:00-20:00 gate |
| verify_log | All checks passed |
| Sessions on file | 19 (2026-08-19 .. 2026-09-23) |
| Ticker-days | 9,557 |
| Censored ticker-days | 340 (3.6%) across 43 distinct tickers |
| posters.csv rows | 1,002 over 2 sessions |
| Fetches last session | 501 of 503 (2 tickers have no source page and never will) |
| Earliest a signal can fire | 2026-10-23 |

## Broken or degraded

Nothing broken. Both runners are green, neither has failed a scheduled run, and
no data gap has opened since the cloud migration.

Degraded, known and recorded, not a fault:

- The collector polls 2 pages every 15 minutes, so it can capture at most ~160
  new pools per hour. The chain creates roughly 1,000-1,200 per hour, so the
  sample is about one pool in six or seven. Inclusion still depends only on
  creation time, so the sample stays outcome-independent, but the
  pre-registration's "about every 15 minutes, two pages per poll" reads as
  fuller coverage than it is.
- The message-count ceiling (180/day) censors ~3.6% of ticker-days, with 15 of
  the 43 affected tickers censored on more than half of sessions. Handling is
  fixed in socialarb addendum 2.

## Questions for the chat

1. **Price convention is not uniform.** Validating on-chain reconstruction
   against GeckoTerminal, 4 of 5 pools matched the **executed** price from swap
   amounts to 0.0000%. The fifth, a hookless pool with a 7.2% static fee,
   matched the **marginal** price from `sqrtPriceX96` to 0.0000% instead and is
   22.9% off on executed. A backtest needs one rule, and five pools is not
   enough to fix it.
2. **Distinct sellers cannot be had cheaply.** The bulk Transfer sweep does not
   reproduce the per-transaction answer (overlap 1 of 11), because tokens hop
   through routers before reaching the pool. Counting real sellers needs either
   one request per selling transaction or a block-walk that indexes all pools
   at once.
3. **A direction correction.** In v4 the swap amounts are the caller's deltas,
   so `amount0 > 0` means the caller received token0, a buy. An earlier probe
   reported "9 distinct sellers" for a sample pool; that figure was buyers. The
   corrected count for the same pool and hour is 11 sellers.
