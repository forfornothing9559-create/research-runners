# ethfilter base rates: how often a new Robinhood token became sellable at a multiple

Generated 2026-10-08 12:00 UTC by `ethfilter/base_rates.py`. Run id `2026-09-21-insentos-v3-robinhood`, chain robinhood (4663).
Pre-registered as a descriptive Q2 output. **Descriptive only: no verdict is issued here.**
Q1's verdict is a permutation test on 24h net return and is not this table.

## Denominator, and why it is not simply 'tokens with a price path'

Scored tokens are **mature** (`eval_ts + 168h` elapsed) and tradeable. Within those, a
candle file that is present but **empty** counts as *never reached the rung*, not as a
missing value: GeckoTerminal is queried once after the window closes, so no candles means
the pool recorded no trades in 168 hours. Only `no_file` is genuinely unknown.

| Arm | Mature | Traded (usable path) | Never traded (empty) | Unknown (no file) | Denominator |
|---|---|---|---|---|---|
| pass | 567 | 401 (70.7%) | 165 (29.1%) | 1 (0.2%) | **566** |
| reject | 4231 | 2470 (58.4%) | 1752 (41.4%) | 9 (0.2%) | **4222** |

**This is the survivorship check, and it does not come out neutral.** The empty-candle
tokens are overwhelmingly reject-arm (165 pass vs 1752 reject). An earlier version of this
script excluded them, which inflated the reject arm far more than the pass arm: it
overstated both arms' levels while *understating* the separation between them. Counting
them is what the numbers below do.

Not scored: 1721 tradeable tokens whose 168-hour window is still open (250 pass, 1471 reject).

## The table

`printed` = a 15-minute candle high reached the rung while liquidity was above the $500
death threshold. This is the share that ever *printed* the multiple, which is the same
quantity as marking a position at last price.

`net $100` / `net $1k` = the rung still clears after paying constant-product exit impact
for that stake against the pool's own liquidity at that moment, plus the locked 2% fees
and 2% entry slippage. The locked flat 4% exit slippage is replaced, because
`cost_finding.md` shows it understates every realistic held exit.

| Rung | pass printed | pass net $100 | pass net $1k | reject printed | reject net $100 | reject net $1k |
|---|---|---|---|---|---|---|
| 1.5x | 199 (35.2%) | 186 (32.9%) | 156 (27.6%) | 215 (5.1%) | 189 (4.5%) | 98 (2.3%) |
| 2x | 126 (22.3%) | 113 (20.0%) | 99 (17.5%) | 142 (3.4%) | 119 (2.8%) | 43 (1.0%) |
| 3x | 71 (12.5%) | 67 (11.8%) | 61 (10.8%) | 68 (1.6%) | 55 (1.3%) | 16 (0.4%) |
| 5x | 35 (6.2%) | 32 (5.7%) | 26 (4.6%) | 30 (0.7%) | 21 (0.5%) | 3 (0.1%) |
| 10x | 16 (2.8%) | 13 (2.3%) | 11 (1.9%) | 9 (0.2%) | 5 (0.1%) | 2 (0.0%) |
| 25x | 3 (0.5%) | 2 (0.4%) | 1 (0.2%) | 3 (0.1%) | 2 (0.0%) | 1 (0.0%) |
| 50x | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 2 (0.0%) | 2 (0.0%) | 0 (0.0%) |
| 100x | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |

**n behind each cell is small above 5x.** At 10x and beyond both arms are in single digits
and nothing there separates them; at 25x and 50x the counts are 0-2 and the apparent
inversion is noise, not a finding. Read 1.5x through 5x; treat the rest as not yet measured.

## What the depth columns cost, and what that says

The haircut from `printed` to `net $1k` is the part no price-based table can see. It is not
symmetric between the arms, and that asymmetry is itself the result: the filter is
selecting for pools deep enough to leave through, which is a different claim from
selecting for pools that go up.

Caveats on the depth model, stated rather than buried: liquidity is only read at the eval
and 4 checkpoints, so the figure used at a hit can be hours stale; `Q = liquidity / 2`
assumes a balanced pool; and a single 15-minute candle high may itself be one small trade.
All three push the net columns **optimistic**, so they remain upper bounds.

## Fill-rule diagnostics

The pre-registered fill rule's own conditions, measured: of 83550 in-window candles, 0 had
no volume and 304 sat below the death threshold. GeckoTerminal only returns candles that
traded, so "the candle traded" filters nothing, and liquidity is read at 4 points, so a
pool dying between them can still have a rung counted -- a limitation
`preregistration.md` states itself. That is why the net columns exist.

## Why tokens failed the tradeable-universe gate

| Reason | Count |
|---|---|
| `vol_h1<100` | 19927 |
| `liq<2000` | 15309 |
| `sellers<3` | 2076 |
| `liquidity_spoofed` | 160 |

