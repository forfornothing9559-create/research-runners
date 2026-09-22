# Pre-registration addendum 2: fill sensitivity and threshold shape

Run ID: `2026-09-21-insentos-v3-robinhood`
Written Tuesday 2026-09-22, around midday Pacific, about 19 hours after
collection began at 00:31 UTC. At the time of writing, some 1-hour and 6-hour
checkpoints existed in the data and none had been examined by anyone. No
24-hour outcome existed yet: the first fall due around 6:30 PM Pacific today.
No 7-day path can exist before September 29. The commit that adds this file is
its public timestamp.

`preregistration.md` and `preregistration_addendum_1.md` are unchanged. This
adds exploratory analysis only. It changes no threshold, no primary analysis,
no exit policy, no universe rule, and no line of the collector.

## What prompted it

An outside review of the design on 2026-09-22 raised four points worth keeping.
Two can be checked with data already being collected. Two are interpretation
rules for the writeup.

## Added analysis 1: how much of any Q2 result survives a stricter fill

The pre-registered fill rule lets a rung fill when a 15-minute candle's **high**
reaches it. A real sell does not land on the high of the bar. A single wick from
one trade can mark a rung filled that nobody could have sold into.

`sensitivity.py` reruns the primary Q2 comparison over the identical paths under
three fill rules:

1. high, exactly as pre-registered
2. high minus 2%, so a rung only just touched does not count
3. close only, the strictest: the bar has to close at or above the rung

**Reading rule, fixed now:** if the pre-registered rule puts the ladder above
zero and the close-only rule does not, the ladder's advantage is mark-to-high
and every writeup must say so in those words. The primary result stays the
pre-registered one either way.

## Added analysis 2: does the filter measure a gradient or just cut a line?

Q1 splits tokens at a single point. If the thresholds measure something real,
forward returns should change gradually as tokens sit further above or below
them. If returns are flat except for a jump exactly at the line, the cut point
is doing the work rather than the measurement.

`sensitivity.py` bins every token by its **threshold ratio**: market cap over
$25,000, 1-hour volume over $1,000, and liquidity over $10,000, taking the
smallest of the three, so 1.0 means the token sat exactly on its binding
threshold. Bins: under 0.25, 0.25 to 0.5, 0.5 to 1, 1 to 2, and 2 and above. It
reports the count and median 24-hour net return per bin, with a minimum of 20
tokens before a median is shown.

## Interpretation note A: Q1 is a conditional question

The universe is tokens that survived to 60 minutes old and then passed the
tradeable gate. Q1 therefore does not ask "does this filter beat a random new
token." It asks "among hour-old tokens that are already tradeable, does the
tighter size cut help." That is the weaker and more honest question, and any
writeup must state it that way.

## Interpretation note B: what the regime split actually splits

The gas sponsorship that ends is on **Robinhood Wallet transactions**,
advertised to end September 29, with its threshold cut from $5 to $0.50 on
August 7, 2026. It is not a chain-wide fee change. The locked split sits at
2026-09-30 00:00 UTC, which is 5 PM Pacific on September 29. That is a few
hours off the advertised end and is left exactly as it is, because the config
locked when collection started and a few hours cannot matter to an exploratory
cut. The writeup should describe the rebate as Wallet-only rather than implying
the whole chain changed.

## Noted for a future test, not this one

Three services claim token-security coverage for chain 4663 that GoPlus and
honeypot.is could not provide: ScanHood, Dedaub's Tok{In}, and ContractWolf.
None is added here. This run's safety half stays untested, as pre-registered.
They are candidates for a separate, later test with its own run ID.
