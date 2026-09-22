# Pre-registration addendum 1: results by launch venue

Run ID: `2026-09-21-insentos-v3-robinhood`
Written Tuesday 2026-09-22 around 1:45 AM Pacific (08:45 UTC), about eight
hours after collection began at 00:31 UTC. By then some 1-hour and 6-hour
checkpoints existed in the data, but none had been examined by anyone, and no
24-hour outcome existed yet: the first fall due Tuesday 2026-09-22 around
6:30 PM Pacific. The commit that adds this file is its public timestamp.

The original `preregistration.md` is unchanged. This addendum adds exploratory
analysis only. It changes no threshold, no primary analysis, no exit policy, no
universe rule, and no line of the collector code.

## What prompted it

Claude Code's pre-launch calibration on 30 real tradeable pools found 22 of
them on the pons-v2 launchpad, with reported liquidity almost exactly equal to
market cap (ratio 1.00). That is the signature of a token still on a bonding
curve rather than one that graduated to a regular pool.

The two kinds of token behave differently in a way that matters here:

- **On a bonding curve**, a holder can always sell back to the curve. Nobody can
  pull the liquidity, so the price has a floor at the curve's starting level and
  the token effectively cannot meet the death rule (liquidity under $500).
  Its worst realistic outcome is a large loss, not zero.
- **In a regular pool**, liquidity providers can withdraw. A rug takes the
  token to zero, and the death rule catches it.

The size filter mostly rejects small curve tokens, so the reject arm will be
mostly curve tokens and the pass arm will lean toward larger or graduated ones.
The pooled Q1 comparison therefore mixes two effects: big versus small, and
curve versus graduated. A pooled result could be driven by the curve's price
floor rather than by size.

## What is added

`venue_split.py`, a read-only report, grouping scored tokens by launch venue
(GeckoTerminal's `dex` id, recorded for every pool from the first event). The
four most common venues each get their own group; all others pool as "other".
Within each group it reports:

1. **Descriptive**: median liquidity-to-market-cap ratio at entry, how many
   tokens landed in each arm, and how many were dead by day 7.
2. **Q1 inside the venue**: pass versus reject net return at the primary 24h
   horizon, with a permutation p-value only when both arms have at least 30.
3. **Q2 inside the venue**: the primary comparison, `ladder_mid` versus
   `hold_7d`, as a paired bootstrap 95% CI, only with at least 30 complete
   paths.

## How to read it

Everything here is exploratory and carries no verdict. The primary results are
exactly those in `preregistration.md`, printed by `score` and `ladder`.

If the pooled Q1 and the within-venue results disagree, the within-venue
results describe the size effect, and the pooled result describes the size
effect plus the venue mix. That observation belongs in any writeup. It does not
promote any within-venue result to primary.
