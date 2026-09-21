# Pre-registration: ethfilter v3

Run ID: `2026-09-21-insentos-v3-robinhood`
Written 2026-09-21, before any data was collected.

## Why there is a v3

Neither v1 nor v2 ever collected a single event. Both are retired, nothing is
discarded, and nothing is invalidated. A pre-registration locks at the first
data collection, not at the moment of writing.

v3 exists because of two findings:

1. **Wrong chain.** The source video is titled "BEST FILTERS TO TRADE ON
   ROBINHOOD". v1 and v2 read "Robinhood" as a token name and tested Base. It
   means Robinhood Chain: an Arbitrum-stack L2, mainnet since July 1 2026, chain
   ID 4663, ETH for gas, and memecoins make up most of its activity. The video's
   own frames fit: 0x addresses, fees in ETH, and an "Almost bonded" tab for
   bonding-curve launchpads. Testing the filter on Base tested something the
   creator never claimed.
2. **No security data.** Claude Code checked GoPlus live on Base: 0 of 40
   tokens returned usable tax or LP data, including tokens that passed every
   market clause. Robinhood Chain is newer and most of its new pools are Uniswap
   v4 pools with launchpad hooks, where LP-holder analysis does not apply. No
   free source was found that simulates buys and sells on this chain.

## Changelog

| # | Change | Why | Effect on what is measured |
|---|---|---|---|
| 1 | Base to Robinhood Chain | The video is about Robinhood Chain | Tests the claim that was actually made |
| 2 | Safety half of the filter dropped (honeypot, renounce, LP burn, dev holdings, tax) | Not reproducible from free data on this chain | Q1 now tests the market-size half only |
| 3 | Universe gate requires 3+ distinct sellers in the last hour | A pure honeypot shows buys and a rising price but nobody can sell. Scored on price alone it looks like a big winner | Keeps unsellable pools out of both arms and out of every exit replay |
| 4 | Universe gate rejects liquidity above 2x FDV | Claude Code saw $98.7M of reported liquidity on a 69-minute-old pool. A genuine pool cannot hold much more than its own fully diluted value | Keeps meaningless liquidity figures out of the death rule and fill rule |
| 5 | Request spacing 20s, 30 calls per run | Live measurement: 7s 60% blocked, 15s 30%, 20s 10% | None. Operational |
| 6 | Results also split at 2026-09-30 00:00 UTC, exploratory | The Robinhood Wallet 90-day gas rebate that began at mainnet launch is reported to end around September 29 | Makes a known regime change visible instead of hiding it in the average |

Carried forward from v2 unchanged: batched reads, liquidity checkpoints, one
candle call per 7-day path, failed reads never recorded as data, append-only
event log, the tradeable-universe gate, the fill rule, the death rule, the cost
assumptions, the exit policies, and one primary result per question.

## Universe

New pools on Robinhood Chain as listed by GeckoTerminal's newest-pools feed,
polled about every 15 minutes, two pages per poll. When the chain produces more
new pools than that captures, the sample is the pools that happened to be
newest at each poll. Inclusion depends only on creation time, never on later
performance, so the sample is unbiased with respect to outcomes.

Age is pool age. For a launchpad token that graduated into a pool, that is time
since graduation, not time since the token was first created.

**Tradeable gate**, applied once at evaluation, identically for both arms. The
first failing check is recorded as the reason:

1. has a price
2. liquidity >= $2,000
3. 1-hour volume >= $100
4. liquidity <= 2x FDV (spoof guard)
5. the 1-hour seller count is present (a missing count is "unknown", never zero)
6. at least 3 distinct sellers in the last hour (sellability guard)

Pools failing the gate are `untradeable` and excluded from scoring. Their count
and reasons are reported.

## Evaluation

Once per pool, between 60 and 100 minutes after pool creation. The video's age
cap is 100 minutes. The entry snapshot is taken at that moment for both arms.
Market cap is GeckoTerminal's `market_cap_usd` where present, otherwise
`fdv_usd`, which for new tokens is almost always what terminals display.

## The filter tested

| Clause | Threshold |
|---|---|
| Market cap | >= $25,000 |
| 1-hour volume | >= $1,000 |
| Liquidity | >= $10,000 |

Read off the @insentos filter panel. The creator offered no evidence.

**Not tested, stated plainly:** Dev Burnt, LP Burnt, Exclude Honeypot, Exclude
Non-Renounced, Exclude Vamped, Exclude RapidLaunch, Exclude Insiders/Wash
Trading, Total Fees >= 0.5 ETH. A null result here says the size thresholds
alone don't separate winners. It says nothing about the full filter.

## Outcomes

**Liquidity checkpoints** at 1h, 6h, 24h and 168h after evaluation, with read
tolerances of 0.5h, 1.5h, 4h and 24h. First successful read inside the
tolerance is used. Not read inside it means MISSING, never dead.

**Death** is observed, never inferred: liquidity under $500 at a checkpoint.

**Price path**: 15-minute candles covering the 168 hours after evaluation,
fetched once after the window closes.

**Costs**, applied identically everywhere: 2% slippage in, 4% out, 2% fees.

## Q1: does the size filter beat its own rejects?

- **Primary**: net return holding to the 24h checkpoint, pass vs reject,
  difference in medians, two-sided permutation test, 10,000 shuffles,
  alpha 0.01. No verdict below 100 tokens per arm.
- **Exploratory**: 1h, 6h, 168h, and the before/after split at 2026-09-30. No
  verdicts.
- **Missing-data guard**: if missing-checkpoint rates differ between arms by
  more than 5 points at a horizon, that horizon is flagged unreliable.

## Q2: does laddering out beat holding?

Paired: every exit policy is replayed over the identical price paths, so
selection cannot explain a difference.

- **Primary**: `ladder_mid` (equal fifths at 2x, 3x, 5x, 10x, 25x) against
  `hold_7d`. Paired bootstrap, 10,000 resamples, 95% CI on the mean paired
  difference in net return. "Beats" only if the whole CI is above zero. No
  verdict below 150 paths.
- **Exploratory**: every other policy against `hold_7d`, including the
  @noahknows ladder near 50x to 180x, plus the before/after split. No verdicts.
- **Base rates**: the share of tradeable tokens ever sellable at 1.5x, 2x, 3x,
  5x, 10x, 25x, 50x and 100x. Descriptive.

**Fill rule**: a rung fills in the first 15-minute candle whose high reaches
it, if that candle traded and the most recent checkpoint at or before it showed
live liquidity. Known limitation: a pool that dies between checkpoints can have
a rung counted in the gap before its death is observed.

**Known limitation of the sellability guard**: it catches pools nobody can sell
at all. It does not catch a token with a punishing sell tax, where sells go
through but the seller receives little. With no buy/sell simulator on this
chain, that risk remains in both arms equally.

## What invalidates this run

Changing anything in `config.json` outside the `api` block after the first
event. The only pre-launch exception is correcting the network id if
GeckoTerminal does not call the chain `robinhood`. Adding or removing an exit
policy after seeing results. Promoting an exploratory result to primary.
Dropping missing or dead tokens. Pooling with any other test.
