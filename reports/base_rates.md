# ethfilter base rates: how often a new Robinhood token became sellable at a multiple

Generated 2026-10-09 01:20 UTC by `ethfilter/base_rates.py`. Run id `2026-09-21-insentos-v3-robinhood`, chain robinhood (4663).
Pre-registered as a descriptive Q2 output. **Descriptive only: no verdict is issued here.**
Q1's verdict is a permutation test on 24h net return and is not this table.

## Denominator, and why it is not simply 'tokens with a price path'

Scored tokens are **mature** (`eval_ts + 168h` elapsed) and tradeable. Within those, a
candle file that is present but **empty** counts as *never reached the rung*, not as a
missing value: GeckoTerminal is queried once after the window closes, so no candles means
the pool recorded no trades in 168 hours. Only `no_file` is genuinely unknown.

| Arm | Mature | Traded (usable path) | Never traded (empty) | Unknown (no file) | Denominator |
|---|---|---|---|---|---|
| pass | 587 | 417 (71.0%) | 167 (28.4%) | 3 (0.5%) | **584** |
| reject | 4473 | 2576 (57.6%) | 1880 (42.0%) | 17 (0.4%) | **4456** |

**This is the survivorship check, and it does not come out neutral.** The empty-candle
tokens are overwhelmingly reject-arm (167 pass vs 1880 reject). An earlier version of this
script excluded them, which inflated the reject arm far more than the pass arm: it
overstated both arms' levels while *understating* the separation between them. Counting
them is what the numbers below do.

Not scored: 1593 tradeable tokens whose 168-hour window is still open (261 pass, 1332 reject).

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
| 1.5x | 207 (35.4%) | 194 (33.2%) | 164 (28.1%) | 223 (5.0%) | 195 (4.4%) | 102 (2.3%) |
| 2x | 131 (22.4%) | 118 (20.2%) | 103 (17.6%) | 147 (3.3%) | 124 (2.8%) | 44 (1.0%) |
| 3x | 75 (12.8%) | 71 (12.2%) | 63 (10.8%) | 70 (1.6%) | 57 (1.3%) | 16 (0.4%) |
| 5x | 37 (6.3%) | 34 (5.8%) | 28 (4.8%) | 31 (0.7%) | 21 (0.5%) | 3 (0.1%) |
| 10x | 17 (2.9%) | 14 (2.4%) | 12 (2.1%) | 9 (0.2%) | 5 (0.1%) | 2 (0.0%) |
| 25x | 4 (0.7%) | 3 (0.5%) | 1 (0.2%) | 3 (0.1%) | 2 (0.0%) | 1 (0.0%) |
| 50x | 1 (0.2%) | 1 (0.2%) | 0 (0.0%) | 2 (0.0%) | 2 (0.0%) | 0 (0.0%) |
| 100x | 1 (0.2%) | 1 (0.2%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |

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

The pre-registered fill rule's own conditions, measured: of 85924 in-window candles, 0 had
no volume and 304 sat below the death threshold. GeckoTerminal only returns candles that
traded, so "the candle traded" filters nothing, and liquidity is read at 4 points, so a
pool dying between them can still have a rung counted -- a limitation
`preregistration.md` states itself. That is why the net columns exist.

## Why tokens failed the tradeable-universe gate

| Reason | Count |
|---|---|
| `vol_h1<100` | 20520 |
| `liq<2000` | 15951 |
| `sellers<3` | 2114 |
| `liquidity_spoofed` | 163 |

