# Cost finding: the locked cost model understates the cost of a held position

Recorded 2026-09-24, during collection, before any outcome was examined.

`config.json` is **not** changed. It locked when the first event was written on
2026-09-22 and it stays locked. This file records the finding instead, so the
gap is on the record before any result is read rather than discovered
afterwards.

## The locked model

2% slippage in, 4% slippage out, 2% round-trip fees: **about 8% round trip**,
applied identically to every arm and every exit policy.

## What a constant-product check gives instead

An immediate in-and-out of the same pool is cheap, because the entry price
impact is handed back on the way out. Only fees are lost:

| Fee stack | Cost of an immediate round trip |
|---|---|
| Pons 1% default, each way | about 1.9% |
| 1% plus a 7.2% hook, each way | about 15.3% |

A **held** position is the case this study actually measures, and it is
different, because the exit impact is never recovered. For a position marked at
$200, exit impact alone is:

| Quote-side depth | Exit impact |
|---|---|
| $2,500 | 7.4% |
| $1,000 | 16.7% |
| $500 | 28.6% |

Adding exit impact to compounded fees gives the total for a held position:

| Case | Total round-trip cost |
|---|---|
| Mildest | 9.3% |
| Drained pool with a fat hook | 39.8% |

**Every realistic held case exceeds the locked 8%.**

## What this does and does not damage

**Q1 still stands.** The locked costs are applied identically to the pass arm
and the reject arm. A cost that is too low in both arms shifts both levels down
by the same amount and cannot manufacture a difference between them. The Q1
comparison is of medians between arms, so it survives.

**Q2 must carry this caveat.** Q2 compares exit policies over the same paths,
but those policies do not trade the same number of times: a five-rung ladder
pays costs on five exits, a hold pays them on one. Understating per-trade cost
therefore favours the policies that trade more. Both Q2's absolute levels and
its ladder-versus-hold margin are unreliable, and no Q2 result may be reported
without this file cited beside it.

**The base-rate table is unaffected.** The share of tradeable tokens that ever
became sellable at 1.5x, 2x, 3x, 5x, 10x, 25x, 50x and 100x does not use the
cost model at all. It is a statement about observed prices, not about net
returns, so nothing here touches it. Given the size of the gap above, that
table is the more trustworthy of the two outputs.
