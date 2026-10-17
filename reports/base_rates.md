# ethfilter base rates: how often a new Robinhood token became sellable at a multiple

Generated 2026-10-17 23:22 UTC by `ethfilter/base_rates.py`. Run id `2026-09-21-insentos-v3-robinhood`, chain robinhood (4663).
Pre-registered as a descriptive Q2 output. **Descriptive only: no verdict is issued here.**
Q1's verdict is a permutation test on 24h net return and is not this table.

## Denominator, and why it is not simply 'tokens with a price path'

Scored tokens are **mature** (`eval_ts + 168h` elapsed) and tradeable. Within those, a
candle file that is present but **empty** counts as *never reached the rung*, not as a
missing value: GeckoTerminal is queried once after the window closes, so no candles means
the pool recorded no trades in 168 hours. Only `no_file` is genuinely unknown.

| Arm | Mature | Traded (usable path) | Never traded (empty) | Unknown (no file) | Denominator |
|---|---|---|---|---|---|
| pass | 951 | 741 (77.9%) | 209 (22.0%) | 1 (0.1%) | **950** |
| reject | 6191 | 3585 (57.9%) | 2593 (41.9%) | 13 (0.2%) | **6178** |

**This is the survivorship check, and it does not come out neutral.** The empty-candle
tokens are overwhelmingly reject-arm (209 pass vs 2593 reject). An earlier version of this
script excluded them, which inflated the reject arm far more than the pass arm: it
overstated both arms' levels while *understating* the separation between them. Counting
them is what the numbers below do.

Not scored: 1369 tradeable tokens whose 168-hour window is still open (350 pass, 1019 reject).

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
| 1.5x | 399 (42.0%) | 380 (40.0%) | 338 (35.6%) | 335 (5.4%) | 288 (4.7%) | 150 (2.4%) |
| 2x | 282 (29.7%) | 265 (27.9%) | 235 (24.7%) | 212 (3.4%) | 181 (2.9%) | 72 (1.2%) |
| 3x | 175 (18.4%) | 163 (17.2%) | 139 (14.6%) | 107 (1.7%) | 89 (1.4%) | 25 (0.4%) |
| 5x | 88 (9.3%) | 83 (8.7%) | 67 (7.1%) | 46 (0.7%) | 35 (0.6%) | 8 (0.1%) |
| 10x | 30 (3.2%) | 25 (2.6%) | 18 (1.9%) | 17 (0.3%) | 11 (0.2%) | 2 (0.0%) |
| 25x | 4 (0.4%) | 3 (0.3%) | 1 (0.1%) | 7 (0.1%) | 5 (0.1%) | 1 (0.0%) |
| 50x | 1 (0.1%) | 1 (0.1%) | 0 (0.0%) | 6 (0.1%) | 2 (0.0%) | 0 (0.0%) |
| 100x | 1 (0.1%) | 1 (0.1%) | 0 (0.0%) | 3 (0.0%) | 0 (0.0%) | 0 (0.0%) |

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

The pre-registered fill rule's own conditions, measured: of 137361 in-window candles, 0 had
no volume and 317 sat below the death threshold. GeckoTerminal only returns candles that
traded, so "the candle traded" filters nothing, and liquidity is read at 4 points, so a
pool dying between them can still have a rung counted -- a limitation
`preregistration.md` states itself. That is why the net columns exist.

## Why tokens failed the tradeable-universe gate

| Reason | Count |
|---|---|
| `vol_h1<100` | 27350 |
| `liq<2000` | 25500 |
| `sellers<3` | 2624 |
| `liquidity_spoofed` | 282 |

