# ethfilter base rates: how often a new Robinhood token became sellable at a multiple

Generated 2026-10-17 20:16 UTC by `ethfilter/base_rates.py`. Run id `2026-09-21-insentos-v3-robinhood`, chain robinhood (4663).
Pre-registered as a descriptive Q2 output. **Descriptive only: no verdict is issued here.**
Q1's verdict is a permutation test on 24h net return and is not this table.

## Denominator, and why it is not simply 'tokens with a price path'

Scored tokens are **mature** (`eval_ts + 168h` elapsed) and tradeable. Within those, a
candle file that is present but **empty** counts as *never reached the rung*, not as a
missing value: GeckoTerminal is queried once after the window closes, so no candles means
the pool recorded no trades in 168 hours. Only `no_file` is genuinely unknown.

| Arm | Mature | Traded (usable path) | Never traded (empty) | Unknown (no file) | Denominator |
|---|---|---|---|---|---|
| pass | 944 | 735 (77.9%) | 206 (21.8%) | 3 (0.3%) | **941** |
| reject | 6162 | 3568 (57.9%) | 2588 (42.0%) | 6 (0.1%) | **6156** |

**This is the survivorship check, and it does not come out neutral.** The empty-candle
tokens are overwhelmingly reject-arm (206 pass vs 2588 reject). An earlier version of this
script excluded them, which inflated the reject arm far more than the pass arm: it
overstated both arms' levels while *understating* the separation between them. Counting
them is what the numbers below do.

Not scored: 1385 tradeable tokens whose 168-hour window is still open (352 pass, 1033 reject).

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
| 1.5x | 396 (42.1%) | 377 (40.1%) | 335 (35.6%) | 333 (5.4%) | 286 (4.6%) | 149 (2.4%) |
| 2x | 279 (29.6%) | 263 (27.9%) | 233 (24.8%) | 210 (3.4%) | 180 (2.9%) | 71 (1.2%) |
| 3x | 173 (18.4%) | 161 (17.1%) | 137 (14.6%) | 106 (1.7%) | 88 (1.4%) | 25 (0.4%) |
| 5x | 86 (9.1%) | 81 (8.6%) | 65 (6.9%) | 45 (0.7%) | 34 (0.6%) | 8 (0.1%) |
| 10x | 30 (3.2%) | 25 (2.7%) | 18 (1.9%) | 17 (0.3%) | 11 (0.2%) | 2 (0.0%) |
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

The pre-registered fill rule's own conditions, measured: of 136060 in-window candles, 0 had
no volume and 317 sat below the death threshold. GeckoTerminal only returns candles that
traded, so "the candle traded" filters nothing, and liquidity is read at 4 points, so a
pool dying between them can still have a rung counted -- a limitation
`preregistration.md` states itself. That is why the net columns exist.

## Why tokens failed the tradeable-universe gate

| Reason | Count |
|---|---|
| `vol_h1<100` | 27244 |
| `liq<2000` | 25396 |
| `sellers<3` | 2618 |
| `liquidity_spoofed` | 278 |

