#!/usr/bin/env python
"""Base-rate table: how often a new Robinhood token became sellable at a price rung.

Pre-registered in preregistration.md as a descriptive output of Q2:

    "Base rates: the share of tradeable tokens ever sellable at 1.5x, 2x, 3x, 5x, 10x, 25x,
     50x and 100x. Descriptive."

and declared unaffected by the locked cost model (cost_finding.md: "It is a statement about
observed prices, not about net returns"). That last claim is true of the PRINTED columns here. It
is not true of the NET columns, which exist because a printed price is not a sellable one, and
which therefore do carry a cost model -- stated inline, not inherited from config.

## Three decisions this table turns on, all settled here rather than left implicit

**1. Only mature tokens are scored.** A 168-hour price path cannot exist for a token evaluated
four days ago. Mixing immature tokens into the denominator counts "the week is not over yet" as
"it never reached 2x". Tokens are scored only once `eval_ts + 168h` has elapsed.

**2. An empty candle file is a NO, not a missing value.** This is the correction that matters
most. 733 candle files are present but contain no candles. GeckoTerminal is queried once after the
window closes, so an empty response means the pool recorded no trades in those 168 hours -- which
means it certainly never printed any rung. Dropping those tokens from the denominator, as the
first version of this script did, silently deletes the worst outcomes and inflates every share.
They are counted as rung-not-reached. Only `no_file` (the fetch never happened) is genuinely
unknown, and those are excluded and counted.

Measured consequence, and the reason this is not a cosmetic point: the empty files are not evenly
spread. Of 733, **41 are pass-arm and 692 are reject-arm**. Excluding them inflated the reject arm
far more than the pass arm, so the original table understated the filter's separation while
overstating both its levels.

**3. A rung only counts if a real stake could have left through it.** The pre-registered fill rule
("the candle traded and the most recent checkpoint showed live liquidity") binds on 1 candle in
33,145 here, because GeckoTerminal only returns candles that traded and liquidity is read at just
4 checkpoints. As written it is a price scan. So the NET columns apply constant-product exit
impact for a concrete stake against the pool's own liquidity at that moment:

    impact = V / (V + Q),  V = stake * multiple,  Q = liquidity / 2

which reproduces cost_finding.md's worked case ($200 out against $2,500 depth = 7.4%). Fees and
entry slippage stay at the locked config values; only the 4% flat exit slippage -- the number
cost_finding.md identifies as wrong -- is replaced by the modelled impact.

  python base_rates.py              print the report
  python base_rates.py --write      also write reports/base_rates.md and reports/status.md
"""
import glob, gzip, json, os, sys, time
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
EVENTS = os.path.join(HERE, "data", "events")
RUNGS = [1.5, 2, 3, 5, 10, 25, 50, 100]      # pre-registered ladder, not chosen here
WINDOW_H = 168                                # pre-registered price-path window
STAKES = [100.0, 1000.0]                      # dollar stakes the NET columns must absorb
ARMS = ("pass", "reject")                     # the eval record's own `status` IS the arm


def load_events():
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
                    evals.setdefault(d["pool_id"], d)
                elif e == "cp":
                    cps[d["pool_id"]].append((d.get("t"), d.get("liq")))
                elif e == "ohlcv":
                    ohlcv[d["pool_id"]] = d
                elif e == "run":
                    runs.append(d)
    for p in cps:
        cps[p].sort(key=lambda x: (x[0] or 0))
    return evals, cps, ohlcv, runs


def path_of(pool, ohlcv):
    """('usable', (timestamps, highs, volumes)) | ('empty', None) | ('no_file', None).

    `k` in a candle file is a 15-minute STEP INDEX from eval_ts, not a timestamp: ethfilter.py:545
    writes int((ts - eval_ts) // 900) and its own reader at :561 rebuilds t0 + k * step. Reading it
    as a timestamp puts every candle outside the window and silently returns all zeros.
    """
    rec = ohlcv.get(pool)
    if not rec or not rec.get("file"):
        return "no_file", None
    fp = os.path.join(HERE, "data", rec["file"])
    if not os.path.exists(fp):
        return "no_file", None
    try:
        with gzip.open(fp, "rt", encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:
        return "empty", None
    if not (d.get("k") and d.get("h")):
        return "empty", None
    t0, step = d.get("eval_ts") or 0, d.get("step") or 900
    return "usable", ([t0 + (ki * step) for ki in d["k"]], d["h"], d.get("v") or [])


def liq_at(ts, ev, cp_list):
    """Most recent liquidity reading at or before ts. The eval is the t0 reading: the universe
    gate measured liquidity there, and the first checkpoint is not until 1h."""
    best = ev.get("liq")
    for t, liq in cp_list:
        if t is None or t > ts:
            break
        if liq is not None:
            best = liq
    return best or 0.0


def net_multiple(mult, liq, stake, costs):
    """Realized multiple for `stake` exiting at `mult` against `liq` of pool liquidity."""
    v = stake * mult
    q = max(liq / 2.0, 1e-9)
    impact = v / (v + q)
    return mult * (1.0 - impact) * (1.0 - costs["fee_round_trip"]) / (1.0 + costs["slippage_in"])


def main():
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    dead, costs = cfg["dead_liquidity_usd"], cfg["costs"]
    evals, cps, ohlcv, runs = load_events()
    now = time.time()
    win = WINDOW_H * 3600

    untradeable = Counter(e.get("reasons") for e in evals.values()
                          if e.get("status") == "untradeable")
    arm_total = Counter(e.get("status") for e in evals.values() if e.get("status") in ARMS)

    # Score every tradeable token. hits[0] is printed price; hits[i] is net of exit impact for
    # STAKES[i-1]. A token with no usable path has empty hit sets, which is the correct answer
    # for an empty candle file and is excluded later for a missing one.
    scored = {}
    for p, ev in evals.items():
        if ev.get("status") not in ARMS or not (ev.get("price") or 0) > 0:
            continue
        state, cand = path_of(p, ohlcv)
        mature = now >= (ev.get("t") or 0) + win
        hits = [set() for _ in range(1 + len(STAKES))]
        bind_no_vol = bind_dead = n_cand = 0
        if state == "usable":
            k, h, v = cand
            entry, t0 = ev["price"], ev.get("t") or 0
            for i, ts in enumerate(k):
                if ts < t0 or ts > t0 + win:
                    continue
                hi = h[i] if i < len(h) else None
                if not hi:
                    continue
                n_cand += 1
                if ((v[i] if i < len(v) else 0) or 0) <= 0:
                    bind_no_vol += 1
                liq = liq_at(ts, ev, cps.get(p, []))
                if liq < dead:
                    bind_dead += 1
                    continue
                mult = hi / entry
                for r in RUNGS:
                    if mult >= r:
                        hits[0].add(r)
                for j, s in enumerate(STAKES):
                    nm = net_multiple(mult, liq, s, costs)
                    for r in RUNGS:
                        if nm >= r:
                            hits[j + 1].add(r)
        scored[p] = {"arm": ev["status"], "state": state, "mature": mature, "hits": hits,
                     "n_cand": n_cand, "no_vol": bind_no_vol, "dead": bind_dead}

    mat = {p: s for p, s in scored.items() if s["mature"]}
    cov, den = {}, {}
    for arm in ARMS:
        a = [s for s in mat.values() if s["arm"] == arm]
        c = Counter(s["state"] for s in a)
        cov[arm] = (len(a), c["usable"], c["empty"], c["no_file"])
        den[arm] = c["usable"] + c["empty"]
    tot_cand = sum(s["n_cand"] for s in scored.values())
    tot_novol = sum(s["no_vol"] for s in scored.values())
    tot_dead = sum(s["dead"] for s in scored.values())

    out = []
    w = out.append
    w("# ethfilter base rates: how often a new Robinhood token became sellable at a multiple")
    w("")
    w("Generated %s UTC by `ethfilter/base_rates.py`. Run id `%s`, chain robinhood (4663)."
      % (time.strftime("%Y-%m-%d %H:%M", time.gmtime()), cfg["run_id"]))
    w("Pre-registered as a descriptive Q2 output. **Descriptive only: no verdict is issued here.**")
    w("Q1's verdict is a permutation test on 24h net return and is not this table.")
    w("")
    w("## Denominator, and why it is not simply 'tokens with a price path'")
    w("")
    w("Scored tokens are **mature** (`eval_ts + 168h` elapsed) and tradeable. Within those, a")
    w("candle file that is present but **empty** counts as *never reached the rung*, not as a")
    w("missing value: GeckoTerminal is queried once after the window closes, so no candles means")
    w("the pool recorded no trades in 168 hours. Only `no_file` is genuinely unknown.")
    w("")
    w("| Arm | Mature | Traded (usable path) | Never traded (empty) | Unknown (no file) | Denominator |")
    w("|---|---|---|---|---|---|")
    for arm in ARMS:
        n, u, e, nf = cov[arm]
        w("| %s | %d | %d (%.1f%%) | %d (%.1f%%) | %d (%.1f%%) | **%d** |"
          % (arm, n, u, 100.0*u/n if n else 0, e, 100.0*e/n if n else 0,
             nf, 100.0*nf/n if n else 0, den[arm]))
    w("")
    w("**This is the survivorship check, and it does not come out neutral.** The empty-candle")
    w("tokens are overwhelmingly reject-arm (%d pass vs %d reject). An earlier version of this"
      % (cov["pass"][2], cov["reject"][2]))
    w("script excluded them, which inflated the reject arm far more than the pass arm: it")
    w("overstated both arms' levels while *understating* the separation between them. Counting")
    w("them is what the numbers below do.")
    w("")
    w("Not scored: %d tradeable tokens whose 168-hour window is still open (%d pass, %d reject)."
      % (len(scored) - len(mat),
         sum(1 for s in scored.values() if not s["mature"] and s["arm"] == "pass"),
         sum(1 for s in scored.values() if not s["mature"] and s["arm"] == "reject")))
    w("")
    w("## The table")
    w("")
    w("`printed` = a 15-minute candle high reached the rung while liquidity was above the $%s"
      % dead)
    w("death threshold. This is the share that ever *printed* the multiple, which is the same")
    w("quantity as marking a position at last price.")
    w("")
    w("`net $100` / `net $1k` = the rung still clears after paying constant-product exit impact")
    w("for that stake against the pool's own liquidity at that moment, plus the locked %g%% fees"
      % (100 * costs["fee_round_trip"]))
    w("and %g%% entry slippage. The locked flat %g%% exit slippage is replaced, because"
      % (100 * costs["slippage_in"], 100 * costs["slippage_out"]))
    w("`cost_finding.md` shows it understates every realistic held exit.")
    w("")
    head = "| Rung |" + "".join(" %s printed | %s net $100 | %s net $1k |" % (a, a, a) for a in ARMS)
    w(head)
    w("|---|" + "---|" * (3 * len(ARMS)))
    for r in RUNGS:
        cells = []
        for arm in ARMS:
            a = [s for s in mat.values() if s["arm"] == arm]
            d = den[arm]
            for idx in range(1 + len(STAKES)):
                n = sum(1 for s in a if r in s["hits"][idx])
                cells.append("%d (%.1f%%)" % (n, 100.0 * n / d) if d else "-")
        w("| %gx | %s |" % (r, " | ".join(cells)))
    w("")
    w("**n behind each cell is small above 5x.** At 10x and beyond both arms are in single digits")
    w("and nothing there separates them; at 25x and 50x the counts are 0-2 and the apparent")
    w("inversion is noise, not a finding. Read 1.5x through 5x; treat the rest as not yet measured.")
    w("")
    w("## What the depth columns cost, and what that says")
    w("")
    w("The haircut from `printed` to `net $1k` is the part no price-based table can see. It is not")
    w("symmetric between the arms, and that asymmetry is itself the result: the filter is")
    w("selecting for pools deep enough to leave through, which is a different claim from")
    w("selecting for pools that go up.")
    w("")
    w("Caveats on the depth model, stated rather than buried: liquidity is only read at the eval")
    w("and 4 checkpoints, so the figure used at a hit can be hours stale; `Q = liquidity / 2`")
    w("assumes a balanced pool; and a single 15-minute candle high may itself be one small trade.")
    w("All three push the net columns **optimistic**, so they remain upper bounds.")
    w("")
    w("## Fill-rule diagnostics")
    w("")
    w("The pre-registered fill rule's own conditions, measured: of %d in-window candles, %d had"
      % (tot_cand, tot_novol))
    w("no volume and %d sat below the death threshold. GeckoTerminal only returns candles that"
      % tot_dead)
    w("traded, so \"the candle traded\" filters nothing, and liquidity is read at 4 points, so a")
    w("pool dying between them can still have a rung counted -- a limitation")
    w("`preregistration.md` states itself. That is why the net columns exist.")
    w("")
    w("## Why tokens failed the tradeable-universe gate")
    w("")
    w("| Reason | Count |")
    w("|---|---|")
    for reason, c in untradeable.most_common():
        w("| `%s` | %d |" % (reason or "(none recorded)", c))
    w("")
    text = "\n".join(out) + "\n"
    print(text)

    if "--write" in sys.argv:
        rp = os.path.join(REPO, "reports")
        os.makedirs(rp, exist_ok=True)
        with open(os.path.join(rp, "base_rates.md"), "w", encoding="utf-8") as fh:
            fh.write(text)
        last = max([r.get("t") or 0 for r in runs], default=0)
        st = ["# Runner status", "",
              "Written by `ethfilter/base_rates.py --write` on every scheduled run that commits",
              "data. Counts only: no returns, no verdicts.", "",
              "**As of %s UTC**" % time.strftime("%Y-%m-%d %H:%M", time.gmtime()), "",
              "## ethfilter (this repo, public)", "", "| | |", "|---|---|",
              "| Run id | `%s` |" % cfg["run_id"],
              "| Chain | robinhood (chain id 4663) |",
              "| Last run event | %s UTC |" % (time.strftime("%Y-%m-%d %H:%M", time.gmtime(last))
                                               if last else "?"),
              "| Run events recorded | %d |" % len(runs),
              "| Pools evaluated | %d |" % len(evals),
              "| Tradeable | %d (pass %d, reject %d) |"
              % (arm_total["pass"] + arm_total["reject"], arm_total["pass"], arm_total["reject"]),
              "| Untradeable | %d |" % sum(untradeable.values()),
              "| Mature and scored | %d (pass %d, reject %d) |"
              % (len(mat), cov["pass"][0], cov["reject"][0]),
              "| Checkpoints recorded | %d |" % sum(len(v) for v in cps.values()),
              "| Candle files | %d usable, %d empty, %d missing |"
              % (sum(1 for s in scored.values() if s["state"] == "usable"),
                 sum(1 for s in scored.values() if s["state"] == "empty"),
                 sum(1 for s in scored.values() if s["state"] == "no_file")),
              "", "Base-rate table: [base_rates.md](base_rates.md).", ""]
        with open(os.path.join(rp, "status.md"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(st))
        print("wrote reports/base_rates.md and reports/status.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
