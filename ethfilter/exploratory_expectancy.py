#!/usr/bin/env python
"""EXPLORATORY: what the pass arm's non-hitters actually return, and what that does to expectancy.

## Status, stated first because it governs how this may be read

`preregistration.md` declares the 168-hour horizon **exploratory, no verdicts** (Q1: "Exploratory:
1h, 6h, 168h, and the before/after split. No verdicts."). Q1's verdict is a permutation test on
24-hour net return and is not computed here. Nothing in this file is a verdict, and no pass/fail
may be read off it. It exists because the base-rate table answers "how often did a rung print"
and says nothing about what happened to everything that did not print, which is where most of the
money goes.

It also differs in kind from `base_rates.py`. That script reports observed prices. This one builds
a hypothetical trading rule on top of them, so it inherits every assumption listed under
"Assumptions" below. A base rate is a measurement; an expectancy is a model.

## What is computed

1. The 168-hour return distribution of pass-arm tokens that never reached 2x exitably. The
   168h **checkpoint** is used, not the candles, for two reasons: it carries price and liquidity
   together, and 41 pass-arm tokens never traded at all, so they have no candles but do have a
   checkpoint price. Using candles would delete exactly the worst cases again.

2. Expectancy of a plain sell-at-2x rule, with the non-hitters' real returns substituted for the
   assumed loss figure. The breakeven arithmetic that motivated this needed non-hitters to average
   about -27.6%; this reports what they actually averaged.

3. Entry cost. The base-rate table's depth haircut was **exit-only**, so its rung shares are
   optimistic by an unmeasured amount. Here constant-product impact is applied at entry too, at
   the evaluation-time liquidity, and the rungs are reported round trip.

   impact = V / (V + Q),  Q = liquidity / 2

   applied at entry with V = stake, and at exit with V = stake * (1 - impact_in) * multiple. Same
   form as `cost_finding.md`'s worked case ($200 against $2,500 depth = 7.4%).

## Assumptions, all of which lean optimistic

* A rung is assumed to fill at exactly the rung multiple. A 15-minute candle high may be one small
  trade at a price no size could have been sold into.
* Liquidity is read at the eval and 4 checkpoints, so the figure used at any moment may be hours
  stale.
* Q = liquidity / 2 assumes a balanced pool.
* Non-hitters are held to 168h with no stop. A real stop would cut losses and also cut winners;
  neither effect is modelled.
* The pass arm is 202 mature tokens. Every share here carries that n.

  python exploratory_expectancy.py
"""
import glob, gzip, json, os, sys, time
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
WINDOW_H = 168
STAKE = 1000.0
RUNGS = [1.5, 2, 3, 5, 10]


def load():
    evals, cps, ohlcv = {}, defaultdict(dict), {}
    for f in sorted(glob.glob(os.path.join(HERE, "data", "events", "*.jsonl"))):
        with open(f, encoding="utf-8") as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    d = json.loads(ln)
                except ValueError:
                    continue
                e = d.get("e")
                if e == "eval" and d.get("status") in ("pass", "reject"):
                    evals.setdefault(d["pool_id"], d)
                elif e == "cp":
                    cps[d["pool_id"]][d.get("h")] = d
                elif e == "ohlcv":
                    ohlcv[d["pool_id"]] = d
    return evals, cps, ohlcv


def candles(pool, ohlcv):
    rec = ohlcv.get(pool)
    if not rec or not rec.get("file"):
        return None
    fp = os.path.join(HERE, "data", rec["file"])
    if not os.path.exists(fp):
        return None
    try:
        with gzip.open(fp, "rt", encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:
        return None
    if not (d.get("k") and d.get("h")):
        return None
    t0, step = d.get("eval_ts") or 0, d.get("step") or 900
    return [t0 + ki * step for ki in d["k"]], d["h"], d.get("v") or []


def impact(v, liq):
    q = max((liq or 0.0) / 2.0, 1e-9)
    return v / (v + q)


def net_mult(mult, liq_exit, stake, fee, liq_entry=None):
    """Realized multiple. Exit-only when liq_entry is None, round trip when it is given."""
    f_in = (1.0 - impact(stake, liq_entry)) if liq_entry is not None else 1.0
    v = stake * f_in * mult
    return f_in * mult * (1.0 - impact(v, liq_exit)) * (1.0 - fee)


def liq_at(ts, ev, cp_by_h):
    best = ev.get("liq")
    for h in sorted(cp_by_h):
        c = cp_by_h[h]
        if (c.get("t") or 0) > ts:
            break
        if c.get("liq") is not None:
            best = c["liq"]
    return best or 0.0


def pct(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    i = min(len(s) - 1, max(0, int(round(p / 100.0 * (len(s) - 1)))))
    return s[i]


def main():
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    fee = cfg["costs"]["fee_round_trip"]
    evals, cps, ohlcv = load()
    now, win = time.time(), WINDOW_H * 3600

    rows = []
    for p, ev in evals.items():
        if ev["status"] != "pass" or not (ev.get("price") or 0) > 0:
            continue
        if now < (ev.get("t") or 0) + win:
            continue
        cp168 = cps[p].get(168.0)
        if not cp168 or not (cp168.get("price") or 0) > 0:
            rows.append({"pool": p, "missing168": True})
            continue
        entry, t0, liq_entry = ev["price"], ev.get("t") or 0, ev.get("liq") or 0.0
        # Peak exitable multiple over the window, exit-only and round trip.
        best_exit, best_rt = 0.0, 0.0
        c = candles(p, ohlcv)
        traded = c is not None
        if traded:
            k, h, v = c
            for i, ts in enumerate(k):
                if ts < t0 or ts > t0 + win:
                    continue
                hi = h[i] if i < len(h) else None
                if not hi:
                    continue
                m = hi / entry
                lq = liq_at(ts, ev, cps[p])
                best_exit = max(best_exit, net_mult(m, lq, STAKE, fee))
                best_rt = max(best_rt, net_mult(m, lq, STAKE, fee, liq_entry))
        # Terminal 168h value, the fate of anything not sold at a rung.
        m168 = cp168["price"] / entry
        end_exit = net_mult(m168, cp168.get("liq") or 0.0, STAKE, fee)
        end_rt = net_mult(m168, cp168.get("liq") or 0.0, STAKE, fee, liq_entry)
        rows.append({"pool": p, "missing168": False, "traded": traded,
                     "peak_exit": best_exit, "peak_rt": best_rt,
                     "end_exit": end_exit, "end_rt": end_rt, "m168": m168})

    ok = [r for r in rows if not r["missing168"]]
    miss = [r for r in rows if r["missing168"]]
    print("EXPLORATORY. No verdict. preregistration.md declares the 168h horizon exploratory.")
    print("Q1's verdict is a permutation test on 24h net return and is not computed here.\n")
    print("pass arm, mature (eval + 168h elapsed): %d" % len(rows))
    print("  with a usable 168h checkpoint price:  %d" % len(ok))
    print("  missing the 168h checkpoint (excluded, counted): %d" % len(miss))
    print("  of the scored, never traded at all (no candles): %d"
          % sum(1 for r in ok if not r["traded"]))

    for label, pk, en in (("EXIT-ONLY (matches the base-rate table)", "peak_exit", "end_exit"),
                          ("ROUND TRIP (entry impact added)", "peak_rt", "end_rt")):
        print("\n" + "=" * 78)
        print(label + "   stake $%.0f" % STAKE)
        print("=" * 78)
        hit = [r for r in ok if r[pk] >= 2.0]
        non = [r for r in ok if r[pk] < 2.0]
        n = len(ok)
        print("reached 2x exitably: %d of %d = %.1f%%   did not: %d = %.1f%%"
              % (len(hit), n, 100.0*len(hit)/n, len(non), 100.0*len(non)/n))

        rets = [r[en] - 1.0 for r in non]
        print("\n168h return of the %d NON-HITTERS (held to 168h, no stop):" % len(non))
        print("  mean   %+7.1f%%        median %+7.1f%%"
              % (100.0*sum(rets)/len(rets), 100.0*pct(rets, 50)))
        print("  deciles: " + "  ".join("%d%% %+.0f%%" % (d, 100.0*pct(rets, d))
                                        for d in range(10, 100, 10)))
        print("  worst %+.1f%%   best %+.1f%%   share below -50%%: %.1f%%   below -90%%: %.1f%%"
              % (100.0*min(rets), 100.0*max(rets),
                 100.0*sum(1 for x in rets if x < -0.50)/len(rets),
                 100.0*sum(1 for x in rets if x < -0.90)/len(rets)))

        # Expectancy of sell-at-2x: hitters realize exactly 2x, non-hitters realize their 168h value.
        exp = (len(hit)*2.0 + sum(r[en] for r in non)) / n
        need = (n - len(hit)*2.0) / len(non) if non else float("nan")
        print("\nsell-at-2x expectancy per token: %+.1f%%   (hitters booked at exactly 2.00x,"
              % (100.0*(exp-1.0)))
        print("  non-hitters held to 168h). Breakeven would need non-hitters to average %+.1f%%;"
              % (100.0*(need-1.0)))
        print("  they actually averaged %+.1f%%." % (100.0*sum(rets)/len(rets)))

        print("\nbuy-and-hold-168h expectancy per token: %+.1f%%"
              % (100.0*(sum(r[en] for r in ok)/n - 1.0)))
        print("rungs, round-trip-adjusted:")
        for r in RUNGS:
            c = sum(1 for x in ok if x[pk] >= r)
            print("   %4gx  %4d of %d  %5.1f%%" % (r, c, n, 100.0*c/n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
