# ethfilter base rates: how often a new Robinhood token became sellable at a multiple

Generated 2026-10-14 21:43 UTC by `ethfilter/base_rates.py`. Run id `2026-09-21-insentos-v3-robinhood`, chain robinhood (4663).
Pre-registered as a descriptive Q2 output. **Descriptive only: no verdict is issued here.**
Q1's verdict is a permutation test on 24h net return and is not this table.

## Denominator, and why it is not simply 'tokens with a price path'

Scored tokens are **mature** (`eval_ts + 168h` elapsed) and tradeable. Within those, a
candle file that is present but **empty** counts as *never reached the rung*, not as a
missing value: GeckoTerminal is queried once after the window closes, so no candles means
the pool recorded no trades in 168 hours. Only `no_file` is genuinely unknown.

| Arm | Mature | Traded (usable path) | Never traded (empty) | Unknown (no file) | Denominator |
|---|---|---|---|---|---|
| pass | 785 | 599 (76.3%) | 185 (23.6%) | 1 (0.1%) | **784** |
| reject | 5589 | 3207 (57.4%) | 2368 (42.4%) | 14 (0.3%) | **5575** |

**This is the survivorship check, and it does not come out neutral.** The empty-candle
tokens are overwhelmingly reject-arm (185 pass vs 2368 reject). An earlier version of this
script excluded them, which inflated the reject arm far more than the pass arm: it
overstated both arms' levels while *understating* the separation between them. Counting
them is what the numbers below do.

Not scored: 1584 tradeable tokens whose 168-hour window is still open (366 pass, 1218 reject).

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
| 1.5x | 310 (39.5%) | 295 (37.6%) | 258 (32.9%) | 287 (5.1%) | 248 (4.4%) | 129 (2.3%) |
| 2x | 208 (26.5%) | 194 (24.7%) | 170 (21.7%) | 185 (3.3%) | 157 (2.8%) | 59 (1.1%) |
| 3x | 124 (15.8%) | 113 (14.4%) | 96 (12.2%) | 89 (1.6%) | 72 (1.3%) | 21 (0.4%) |
| 5x | 61 (7.8%) | 58 (7.4%) | 49 (6.2%) | 39 (0.7%) | 28 (0.5%) | 5 (0.1%) |
| 10x | 22 (2.8%) | 18 (2.3%) | 13 (1.7%) | 14 (0.3%) | 8 (0.1%) | 2 (0.0%) |
| 25x | 4 (0.5%) | 3 (0.4%) | 1 (0.1%) | 5 (0.1%) | 3 (0.1%) | 1 (0.0%) |
| 50x | 1 (0.1%) | 1 (0.1%) | 0 (0.0%) | 4 (0.1%) | 2 (0.0%) | 0 (0.0%) |
| 100x | 1 (0.1%) | 1 (0.1%) | 0 (0.0%) | 2 (0.0%) | 0 (0.0%) | 0 (0.0%) |

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

The pre-registered fill rule's own conditions, measured: of 112766 in-window candles, 0 had
no volume and 308 sat below the death threshold. GeckoTerminal only returns candles that
traded, so "the candle traded" filters nothing, and liquidity is read at 4 points, so a
pool dying between them can still have a rung counted -- a limitation
`preregistration.md` states itself. That is why the net columns exist.

## Why tokens failed the tradeable-universe gate

| Reason | Count |
|---|---|
| `vol_h1<100` | 25409 |
| `liq<2000` | 22945 |
| `sellers<3` | 2514 |
| `liquidity_spoofed` | 239 |

