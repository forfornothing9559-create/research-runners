#!/usr/bin/env python
"""Base-rate table: the share of tradeable tokens that ever became SELLABLE at a price rung.

Pre-registered in preregistration.md as a descriptive output of Q2:

    "Base rates: the share of tradeable tokens ever sellable at 1.5x, 2x, 3x, 5x, 10x, 25x,
     50x and 100x. Descriptive."

and declared unaffected by the cost finding (cost_finding.md: "The base-rate table is
unaffected ... It is a statement about observed prices, not about net returns"). So this script
reads no cost model and produces no net return. It is counts and shares only.

The fill rule is the pre-registered one, not a price scan:

    "a rung fills in the first 15-minute candle whose high reaches it, if that candle traded and
     the most recent checkpoint at or before it showed live liquidity"

with live liquidity being the pre-registered death threshold inverted: liq >= config
`dead_liquidity_usd` ($500). Two readings of that rule had to be settled here and both are
printed with the table rather than buried:

  * A candle in the first hour has no checkpoint before it, because the first checkpoint is at
    1h. The evaluation snapshot itself is a liquidity reading at t0 -- the universe gate measured
    liquidity >= $2,000 there -- so the eval is used as the t0 checkpoint. Without this, every
    rung reached in the first hour would be discarded on a technicality.
  * "That candle traded" is volume > 0 in the candle.

Alongside the pre-registered table this prints the same ladder computed on price alone, ignoring
whether anything could actually be sold. That column is not the result; it is there because the
difference between the two is the entire point. A price a position cannot be exited at is not a
return.

  python base_rates.py              print the table
  python base_rates.py --write      also write reports/base_rates.md and refresh reports/status.md
"""
import glob, gzip, json, os, sys, time
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
EVENTS = os.path.join(HERE, "data", "events")
CANDLES = os.path.join(HERE, "data", "candles")
RUNGS = [1.5, 2, 3, 5, 10, 25, 50, 100]          # pre-registered ladder, not chosen here
WINDOW_H = 168                                    # pre-registered price-path window


def load_config():
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as fh:
        return json.load(fh)


def load_events():
    """evals keyed by pool, checkpoint liquidity timelines, and ohlcv statuses."""
    evals, cps, ohlcv, runs = {}, defaultdict(list), {}, []
    for f in sorted(glob.glob(os.path.join(EVENTS, "*.jsonl"))):
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
                if e == "eval":
                    # One eval per pool is pre-registered; keep the first if that is ever violated.
                    evals.setdefault(d["pool_id"], d)
                elif e == "cp":
                    cps[d["pool_id"]].append((d.get("t"), d.get("liq"), d.get("status")))
                elif e == "ohlcv":
                    ohlcv[d["pool_id"]] = d
                elif e == "run":
                    runs.append(d)
    for p in cps:
        cps[p].sort(key=lambda x: (x[0] or 0))
    return evals, cps, ohlcv, runs


def liq_at_or_before(ts, eval_ev, cp_list):
    """Most recent liquidity reading at or before ts. The eval is the t0 reading; see module doc."""
    best_t, best_liq = eval_ev.get("t"), eval_ev.get("liq")
    for t, liq, status in cp_list:
        if t is None or t > ts:
            break
        if liq is None:
            continue
        best_t, best_liq = t, liq
    return best_liq


# The collector records the arm in `status` itself: "pass" and "reject" are the two arms of the
# filter under test, "untradeable" is the universe gate rejecting the pool before either arm.
# The arm is read from that field rather than recomputed from the thresholds, so this table
# cannot drift from what the collector actually decided at evaluation time.
ARMS = ("pass", "reject")


def main():
    cfg = load_config()
    dead = cfg["dead_liquidity_usd"]
    evals, cps, ohlcv, runs = load_events()

    tradeable = {p: e for p, e in evals.items()
                 if e.get("status") in ARMS and (e.get("price") or 0) > 0}
    no_price = sum(1 for e in evals.values()
                   if e.get("status") in ARMS and not (e.get("price") or 0) > 0)
    untradeable_reasons = Counter(e.get("reasons") for e in evals.values()
                                  if e.get("status") == "untradeable")
    arm_total = Counter(e.get("status") for e in evals.values() if e.get("status") in ARMS)

    # Candle coverage. An ohlcv event with status "ok" does NOT mean candles exist: the sampled
    # file carried status ok with k/h/c/v all empty. Coverage is measured from the files.
    have_file, empty_file, no_file, usable = 0, 0, 0, {}
    for p, ev in tradeable.items():
        rec = ohlcv.get(p)
        path = os.path.join(HERE, "data", rec["file"]) if rec and rec.get("file") else None
        if not path or not os.path.exists(path):
            no_file += 1
            continue
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            empty_file += 1
            continue
        have_file += 1
        k, h, v = d.get("k") or [], d.get("h") or [], d.get("v") or []
        if not k or not h:
            empty_file += 1
            continue
        # `k` is a 15-minute STEP INDEX from eval_ts, not a timestamp: ethfilter.py:545 writes
        # int((candle_ts - eval_ts) // 900) and its own reader at :561 rebuilds t0 + k * step.
        t0, step = d.get("eval_ts") or 0, d.get("step") or 900
        usable[p] = ([t0 + (ki * step) for ki in k], h, v)

    # The table. Scored over tokens with a usable price path, which is the only set where the
    # question "did it ever reach this rung" can be answered at all.
    sellable = Counter()
    price_only = Counter()
    bind = Counter()          # how often the fill rule's own conditions actually bind
    by_arm = {"pass": Counter(), "reject": Counter()}
    arm_n = Counter()
    for p, (k, h, v) in usable.items():
        ev = tradeable[p]
        entry, t0 = ev["price"], ev.get("t") or 0
        end = t0 + WINDOW_H * 3600
        arm = ev["status"]
        arm_n[arm] += 1
        hit_s, hit_p = set(), set()
        for i, ts in enumerate(k):
            if ts is None or ts < t0 or ts > end:
                continue
            hi = h[i] if i < len(h) else None
            if not hi:
                continue
            mult = hi / entry
            traded = (v[i] if i < len(v) else 0) or 0
            live = (liq_at_or_before(ts, ev, cps.get(p, [])) or 0) >= dead
            bind["candles"] += 1
            if traded <= 0:
                bind["no_volume"] += 1
            if not live:
                bind["below_death"] += 1
            for r in RUNGS:
                if mult >= r:
                    hit_p.add(r)
                    if traded > 0 and live:
                        hit_s.add(r)
        for r in hit_p:
            price_only[r] += 1
        for r in hit_s:
            sellable[r] += 1
            by_arm[arm][r] += 1

    n = len(usable)
    out = []
    w = out.append
    w("# ethfilter base rates: how often a new Robinhood token became sellable at a multiple")
    w("")
    w("Generated %s UTC by `ethfilter/base_rates.py`. Pre-registered as a descriptive output of"
      % time.strftime("%Y-%m-%d %H:%M", time.gmtime()))
    w("Q2 (`preregistration.md`), and declared unaffected by the cost finding")
    w("(`cost_finding.md`), because it reads no cost model and reports no return.")
    w("")
    w("**Run id** `%s`  |  **chain** robinhood (4663)  |  **death threshold** $%s liquidity"
      % (cfg["run_id"], dead))
    w("")
    w("## Sample")
    w("")
    w("| | |")
    w("|---|---|")
    w("| Pools evaluated | %d |" % len(evals))
    w("| Failed the tradeable-universe gate (excluded, pre-registered) | %d |"
      % sum(untradeable_reasons.values()))
    w("| Tradeable | **%d** | " % len(tradeable))
    w("| &nbsp;&nbsp;of which **pass** arm (the filter's own picks) | **%d** |" % arm_total["pass"])
    w("| &nbsp;&nbsp;of which **reject** arm | %d |" % arm_total["reject"])
    w("| Tradeable but no usable entry price | %d |" % no_price)
    w("| Tradeable tokens with a usable 15-min price path | **%d** |" % n)
    w("| Tradeable, candle file present but empty | %d |" % empty_file)
    w("| Tradeable, no candle file yet | %d |" % no_file)
    w("")
    if n:
        w("The table below is over the **%d** tokens with a usable price path, not over all %d"
          % (n, len(tradeable)))
        w("tradeable tokens. %d of %d (%.1f%%) are missing a usable path, which is a coverage"
          % (len(tradeable) - n, len(tradeable), 100.0 * (len(tradeable) - n) / len(tradeable)))
        w("limit on this table and is reported here rather than silently absorbed into the")
        w("denominator. A 168-hour price path cannot exist yet for a token evaluated in the last")
        w("week, so this number is expected to be large early and to fall as the window fills.")
    w("")
    w("## The table")
    w("")
    w("`sellable` is the pre-registered fill rule: a 15-minute candle whose high reaches the rung,")
    w("that candle traded, and the most recent liquidity reading at or before it was above the")
    w("death threshold. `price alone` ignores whether anything could be sold and is shown only to")
    w("size the difference.")
    w("")
    w("**Read this before the numbers.** On this sample the fill rule's sellability conditions")
    w("almost never bind: of %d in-window candles, %d had no volume and %d sat below the death"
      % (bind["candles"], bind["no_volume"], bind["below_death"]))
    w("threshold. So `sellable` and `price alone` come out nearly identical, and the table is in")
    w("practice a **price-reached** table, not an executable one. Two structural reasons, both")
    w("inherent to the data rather than to this script:")
    w("")
    w("1. GeckoTerminal's OHLCV feed only returns candles that traded, so \"that candle traded\"")
    w("   is true by construction and filters nothing.")
    w("2. Liquidity is only read at 4 checkpoints (1h, 6h, 24h, 168h), so a pool that dies between")
    w("   them can still have a rung counted. `preregistration.md` states this limitation itself:")
    w("   \"a pool that dies between checkpoints can have a rung counted in the gap before its")
    w("   death is observed.\"")
    w("")
    w("**Treat every share below as an upper bound.** It is the share that ever *printed* the")
    w("multiple, which is the same quantity as marking a position at last price. Answering what")
    w("could actually be exited needs quote-side depth at the moment of the hit, which this")
    w("dataset does not carry per candle. The 2026-09-24 launch-tape measurement is the warning:")
    w("20x+ tickets there carried a 73% average round-trip cost and 69-71% of them had under $500")
    w("of exit liquidity.")
    w("")
    w("| Rung | Ever sellable | Share | Price alone | Share | Gap |")
    w("|---|---|---|---|---|---|")
    for r in RUNGS:
        s, pq = sellable[r], price_only[r]
        w("| %gx | %d | %s | %d | %s | %s |"
          % (r, s, ("%.1f%%" % (100.0 * s / n)) if n else "-",
             pq, ("%.1f%%" % (100.0 * pq / n)) if n else "-",
             ("%+.1f pts" % (100.0 * (pq - s) / n)) if n else "-"))
    w("")
    if arm_n:
        w("## Split by the filter being tested")
        w("")
        w("Pass = market cap >= $%s, 1h volume >= $%s, liquidity >= $%s. The arm is read from the"
          % (cfg["filter"]["min_market_cap_usd"], cfg["filter"]["min_volume_h1_usd"],
             cfg["filter"]["min_liquidity_usd"]))
        w("eval record's own `status`, not recomputed. **The pass column is the 'final arm'.**")
        w("**Descriptive only.** Q1's verdict is a permutation test on 24h net return, not")
        w("this table, and no verdict may be read off these two columns.")
        w("")
        w("| Rung | pass (n=%d) | reject (n=%d) |" % (arm_n["pass"], arm_n["reject"]))
        w("|---|---|---|")
        for r in RUNGS:
            a, b = by_arm["pass"][r], by_arm["reject"][r]
            w("| %gx | %s | %s |"
              % (r, ("%d (%.1f%%)" % (a, 100.0 * a / arm_n["pass"])) if arm_n["pass"] else "-",
                 ("%d (%.1f%%)" % (b, 100.0 * b / arm_n["reject"])) if arm_n["reject"] else "-"))
        w("")
    w("## Why tokens failed the universe gate")
    w("")
    w("| Reason | Count |")
    w("|---|---|")
    for reason, c in untradeable_reasons.most_common():
        w("| `%s` | %d |" % (reason, c))
    w("")
    text = "\n".join(out) + "\n"
    print(text)

    if "--write" in sys.argv:
        rp = os.path.join(REPO, "reports")
        os.makedirs(rp, exist_ok=True)
        with open(os.path.join(rp, "base_rates.md"), "w", encoding="utf-8") as fh:
            fh.write(text)
        # status.md: counts only, same discipline as the hand-written version it replaces.
        last = max([r.get("t") or 0 for r in runs], default=0)
        st = ["# Runner status", "",
              "Written by `ethfilter/base_rates.py --write` on every scheduled run. Counts only:",
              "no returns, no z-scores, no outcomes are read to produce this file.", "",
              "**As of %s UTC**" % time.strftime("%Y-%m-%d %H:%M", time.gmtime()), "",
              "## ethfilter (this repo, public)", "", "| | |", "|---|---|",
              "| Run id | `%s` |" % cfg["run_id"],
              "| Chain | robinhood (chain id 4663) |",
              "| Last run event | %s UTC |" % (time.strftime("%Y-%m-%d %H:%M", time.gmtime(last)) if last else "?"),
              "| Run events recorded | %d |" % len(runs),
              "| Pools evaluated | %d |" % len(evals),
              "| Tradeable | %d (pass %d, reject %d) |"
              % (len(tradeable), arm_total["pass"], arm_total["reject"]),
              "| Untradeable | %d |" % sum(untradeable_reasons.values()),
              "| Checkpoints recorded | %d |" % sum(len(v) for v in cps.values()),
              "| Candle files | %d present, %d empty, %d missing |" % (have_file, empty_file, no_file),
              "", "Base-rate table: [base_rates.md](base_rates.md).", ""]
        with open(os.path.join(rp, "status.md"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(st))
        print("wrote reports/base_rates.md and reports/status.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
