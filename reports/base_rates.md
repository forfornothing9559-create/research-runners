# ethfilter base rates: how often a new Robinhood token became sellable at a multiple

Generated 2026-10-02 05:53 UTC by `ethfilter/base_rates.py`. Pre-registered as a descriptive output of
Q2 (`preregistration.md`), and declared unaffected by the cost finding
(`cost_finding.md`), because it reads no cost model and reports no return.

**Run id** `2026-09-21-insentos-v3-robinhood`  |  **chain** robinhood (4663)  |  **death threshold** $500 liquidity

## Sample

| | |
|---|---|
| Pools evaluated | 31771 |
| Failed the tradeable-universe gate (excluded, pre-registered) | 26632 |
| Tradeable | **5139** | 
| &nbsp;&nbsp;of which **pass** arm (the filter's own picks) | **600** |
| &nbsp;&nbsp;of which **reject** arm | 4539 |
| Tradeable but no usable entry price | 0 |
| Tradeable tokens with a usable 15-min price path | **1021** |
| Tradeable, candle file present but empty | 733 |
| Tradeable, no candle file yet | 3385 |

The table below is over the **1021** tokens with a usable price path, not over all 5139
tradeable tokens. 4118 of 5139 (80.1%) are missing a usable path, which is a coverage
limit on this table and is reported here rather than silently absorbed into the
denominator. A 168-hour price path cannot exist yet for a token evaluated in the last
week, so this number is expected to be large early and to fall as the window fills.

## The table

`sellable` is the pre-registered fill rule: a 15-minute candle whose high reaches the rung,
that candle traded, and the most recent liquidity reading at or before it was above the
death threshold. `price alone` ignores whether anything could be sold and is shown only to
size the difference.

**Read this before the numbers.** On this sample the fill rule's sellability conditions
almost never bind: of 33145 in-window candles, 0 had no volume and 1 sat below the death
threshold. So `sellable` and `price alone` come out nearly identical, and the table is in
practice a **price-reached** table, not an executable one. Two structural reasons, both
inherent to the data rather than to this script:

1. GeckoTerminal's OHLCV feed only returns candles that traded, so "that candle traded"
   is true by construction and filters nothing.
2. Liquidity is only read at 4 checkpoints (1h, 6h, 24h, 168h), so a pool that dies between
   them can still have a rung counted. `preregistration.md` states this limitation itself:
   "a pool that dies between checkpoints can have a rung counted in the gap before its
   death is observed."

**Treat every share below as an upper bound.** It is the share that ever *printed* the
multiple, which is the same quantity as marking a position at last price. Answering what
could actually be exited needs quote-side depth at the moment of the hit, which this
dataset does not carry per candle. The 2026-09-24 launch-tape measurement is the warning:
20x+ tickets there carried a 73% average round-trip cost and 69-71% of them had under $500
of exit liquidity.

| Rung | Ever sellable | Share | Price alone | Share | Gap |
|---|---|---|---|---|---|
| 1.5x | 141 | 13.8% | 141 | 13.8% | +0.0 pts |
| 2x | 100 | 9.8% | 100 | 9.8% | +0.0 pts |
| 3x | 51 | 5.0% | 51 | 5.0% | +0.0 pts |
| 5x | 27 | 2.6% | 27 | 2.6% | +0.0 pts |
| 10x | 10 | 1.0% | 10 | 1.0% | +0.0 pts |
| 25x | 3 | 0.3% | 3 | 0.3% | +0.0 pts |
| 50x | 2 | 0.2% | 2 | 0.2% | +0.0 pts |
| 100x | 0 | 0.0% | 0 | 0.0% | +0.0 pts |

## Split by the filter being tested

Pass = market cap >= $25000, 1h volume >= $1000, liquidity >= $10000. The arm is read from the
eval record's own `status`, not recomputed. **The pass column is the 'final arm'.**
**Descriptive only.** Q1's verdict is a permutation test on 24h net return, not
this table, and no verdict may be read off these two columns.

| Rung | pass (n=135) | reject (n=886) |
|---|---|---|
| 1.5x | 67 (49.6%) | 74 (8.4%) |
| 2x | 46 (34.1%) | 54 (6.1%) |
| 3x | 30 (22.2%) | 21 (2.4%) |
| 5x | 16 (11.9%) | 11 (1.2%) |
| 10x | 5 (3.7%) | 5 (0.6%) |
| 25x | 1 (0.7%) | 2 (0.2%) |
| 50x | 0 (0.0%) | 2 (0.2%) |
| 100x | 0 (0.0%) | 0 (0.0%) |

## Why tokens failed the universe gate

| Reason | Count |
|---|---|
| `vol_h1<100` | 14571 |
| `liq<2000` | 10377 |
| `sellers<3` | 1606 |
| `liquidity_spoofed` | 78 |

