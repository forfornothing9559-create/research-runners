# EXPLORATORY: non-hitter returns and expectancy

Snapshot generated 2026-10-02 10:28 UTC by `ethfilter/exploratory_expectancy.py`.
**Not wired into the workflow and not auto-refreshed**, deliberately: this is exploratory under
`preregistration.md` and must not sit beside the base-rate table as if it were a verdict.

```
EXPLORATORY. No verdict. preregistration.md declares the 168h horizon exploratory.
Q1's verdict is a permutation test on 24h net return and is not computed here.

pass arm, mature (eval + 168h elapsed): 203
  with a usable 168h checkpoint price:  198
  missing the 168h checkpoint (excluded, counted): 5
  of the scored, never traded at all (no candles): 56

==============================================================================
EXIT-ONLY (matches the base-rate table)   stake $1000
==============================================================================
reached 2x exitably: 40 of 198 = 20.2%   did not: 158 = 79.8%

168h return of the 158 NON-HITTERS (held to 168h, no stop):
  mean     -61.9%        median   -84.1%
  deciles: 10% -100%  20% -99%  30% -96%  40% -92%  50% -84%  60% -66%  70% -18%  80% -8%  90% -6%
  worst -100.0%   best +35.4%   share below -50%: 65.2%   below -90%: 44.9%

sell-at-2x expectancy per token: -29.2%   (hitters booked at exactly 2.00x,
  non-hitters held to 168h). Breakeven would need non-hitters to average -25.3%;
  they actually averaged -61.9%.

buy-and-hold-168h expectancy per token: -54.4%
rungs, round-trip-adjusted:
    1.5x    59 of 198   29.8%
      2x    40 of 198   20.2%
      3x    29 of 198   14.6%
      5x    13 of 198    6.6%
     10x     4 of 198    2.0%

==============================================================================
ROUND TRIP (entry impact added)   stake $1000
==============================================================================
reached 2x exitably: 40 of 198 = 20.2%   did not: 158 = 79.8%

168h return of the 158 NON-HITTERS (held to 168h, no stop):
  mean     -63.8%        median   -85.6%
  deciles: 10% -100%  20% -99%  30% -96%  40% -93%  50% -86%  60% -69%  70% -23%  80% -12%  90% -10%
  worst -100.0%   best +27.9%   share below -50%: 65.2%   below -90%: 45.6%

sell-at-2x expectancy per token: -30.7%   (hitters booked at exactly 2.00x,
  non-hitters held to 168h). Breakeven would need non-hitters to average -25.3%;
  they actually averaged -63.8%.

buy-and-hold-168h expectancy per token: -56.4%
rungs, round-trip-adjusted:
    1.5x    55 of 198   27.8%
      2x    40 of 198   20.2%
      3x    29 of 198   14.6%
      5x    12 of 198    6.1%
     10x     4 of 198    2.0%
```
