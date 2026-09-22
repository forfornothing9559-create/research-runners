#!/usr/bin/env python3
"""
venue_split.py - the exploratory analysis specified in preregistration_addendum_1.md

READ-ONLY. Imports ethfilter's scoring functions and reads ethfilter/data/.
It never writes a file, never calls an API, and never changes a primary
result. Every number it prints is exploratory and carries no verdict.

Why it exists: on Robinhood Chain most new tokens are still on a launchpad's
bonding curve (pons-v2 in Claude Code's calibration sample). A curve token can
always be sold back to the curve, so it has a price floor and effectively
cannot meet the death rule. A token that graduated to a regular pool can be
rugged to zero. The size filter mostly rejects small curve tokens, so the
pooled Q1 mixes "big vs small" with "curve vs graduated". Splitting by venue
separates the two.

Usage:
  python venue_split.py            # report on ethfilter/data
  python venue_split.py selftest   # checks on simulated data
"""

import contextlib
import glob
import io
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ethfilter as E  # noqa: E402

MIN_PER_ARM = 30     # per arm, within a venue, before a p-value is printed
MIN_PATHS = 30       # complete 7-day paths, within a venue, before a CI is printed
TOP_VENUES = 4       # the four most common venues get their own group; the rest pool as "other"


def venue(tk):
    return tk.get("dex") or "unknown"


def report(cfg, data_dir, out=print):
    rows = E._rows(cfg, data_dir)
    out("=" * 66)
    out("EXPLORATORY: RESULTS BY LAUNCH VENUE   run_id=%s" % cfg["run_id"])
    out("=" * 66)
    out("Pre-specified in preregistration_addendum_1.md. No verdicts here.")
    out("The primary results are the ones `score` and `ladder` print, unchanged.")
    if not rows:
        out("no scored tokens yet")
        return {}

    counts = {}
    for tk, _cps, _c in rows:
        counts[venue(tk)] = counts.get(venue(tk), 0) + 1
    top = [v for v, _n in sorted(counts.items(), key=lambda kv: -kv[1])[:TOP_VENUES]]

    groups = {}
    for r in rows:
        v = venue(r[0])
        groups.setdefault(v if v in top else "other", []).append(r)

    H = float(cfg["primary"]["q1_horizon_hours"])
    prim, base = cfg["primary"]["q2_policy"], cfg["primary"]["q2_baseline"]
    dead = cfg["dead_liquidity_usd"]
    result = {}

    for g in sorted(groups, key=lambda k: -len(groups[k])):
        rs = groups[g]
        out("\n-- %s  (%d scored tokens) --" % (g, len(rs)))

        # descriptive: how curve-like the venue is, how its tokens split, how often they die
        ratios = [tk["eval_liq"] / tk["eval_mcap"] for tk, _cps, _c in rs
                  if tk.get("eval_liq") and tk.get("eval_mcap")]
        if ratios:
            out("   liquidity / market cap at entry, median %.2f  (near 1.00 = still on a curve)"
                % E.median(ratios))
        npass = sum(1 for tk, _cps, _c in rs if tk["status"] == "pass")
        out("   in the pass arm: %d of %d" % (npass, len(rs)))
        day7 = [tk["cps"].get(168.0) for tk, _cps, _c in rs]
        day7 = [ev for ev in day7 if ev and ev["status"] == "ok"]
        if day7:
            died = sum(1 for ev in day7 if (ev.get("liq") or 0) < dead)
            out("   dead by day 7 (liquidity under $%d): %d of %d" % (dead, died, len(day7)))

        # Q1 at the primary horizon, inside this venue
        arms = {"pass": [], "reject": []}
        for tk, cps, _c in rs:
            ev = tk["cps"].get(H)
            if not ev or ev["status"] != "ok":
                continue
            g_ = E.policy_value({"type": "hold", "hours": H}, tk["eval_price"], None, cps, cfg)
            arms[tk["status"]].append(E.net_return(g_, cfg))
        pa, pr = arms["pass"], arms["reject"]
        line = "   Q1 at %gh: pass n=%d" % (H, len(pa))
        if pa:
            line += " median %+.1f%%" % (100 * E.median(pa))
        line += "  |  reject n=%d" % len(pr)
        if pr:
            line += " median %+.1f%%" % (100 * E.median(pr))
        out(line)
        q1 = None
        if len(pa) >= MIN_PER_ARM and len(pr) >= MIN_PER_ARM:
            obs, p = E.permutation_p(pa, pr, iters=cfg["permutations"])
            q1 = (obs, p)
            out("      gap %+.1f pp, permutation p = %.4f  (exploratory)" % (100 * obs, p))
        else:
            out("      too few for a p-value (need %d per arm)" % MIN_PER_ARM)

        # Q2 primary comparison inside this venue, same pairing rule as `ladder`
        diffs = []
        for tk, cps, candles in rs:
            if tk["ohlcv"] is None:
                continue
            vals = {}
            for name, pol in cfg["exit_policies"].items():
                v = E.policy_value(pol, tk["eval_price"], candles, cps, cfg)
                if v is None:
                    vals = None
                    break
                vals[name] = E.net_return(v, cfg)
            if vals:
                diffs.append(vals[prim] - vals[base])
        q2 = None
        if len(diffs) >= MIN_PATHS:
            m, lo, hi = E.paired_bootstrap_ci(diffs, iters=cfg["bootstraps"])
            q2 = (m, lo, hi)
            out("   Q2 %s vs %s: n=%d  %+.1f pp  [%+.1f, %+.1f]  (exploratory)"
                % (prim, base, len(diffs), 100 * m, 100 * lo, 100 * hi))
        else:
            out("   Q2: %d complete paths, need %d" % (len(diffs), MIN_PATHS))

        result[g] = {"n": len(rs), "q1": q1, "q2": q2}
    return result


def _snapshot(d):
    snap = {}
    for f in glob.glob(os.path.join(d, "**", "*"), recursive=True):
        if os.path.isfile(f):
            st = os.stat(f)
            snap[os.path.relpath(f, d)] = (st.st_size, st.st_mtime_ns)
    return snap


def selftest():
    fails = []

    def check(name, ok, detail=""):
        print("  %-50s %s %s" % (name, "PASS" if ok else "FAIL", detail))
        if not ok:
            fails.append(name)

    cfg = E.load_config()
    print("-- venue split on simulated data (two venues, 10 days) --")
    tmp = tempfile.mkdtemp(prefix="venue_sim_")
    try:
        t0 = 1_780_000_000
        world = E.FakeWorld(5, t0)
        for step in range(96 * 10):
            world.now = t0 + step * 900
            if step < 96 * 2:
                world.spawn()
            api = E.Api(cfg, getter=world.get, sleeper=lambda _x: None, clock=lambda: 0.0)
            E.run_cycle(cfg, api, tmp, world.now)

        before = _snapshot(tmp)
        buf = io.StringIO()
        fast = dict(cfg, permutations=500, bootstraps=500)
        with contextlib.redirect_stdout(buf):
            res = report(fast, tmp)
        text = buf.getvalue()
        after = _snapshot(tmp)

        check("never writes to the data folder", before == after and len(before) > 0)
        check("reports every venue present in the data",
              "uniswap-v4-robinhood" in text and "uniswap-v3-robinhood" in text)
        n_rows = len(E._rows(cfg, tmp))
        check("venue groups cover every scored token exactly once",
              sum(r["n"] for r in res.values()) == n_rows, "%d tokens" % n_rows)
        check("prints no verdicts", "VERDICT" not in text)
        check("produces within-venue Q2 estimates", any(r["q2"] for r in res.values()))
        empty = tempfile.mkdtemp(prefix="venue_empty_")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                ok = report(cfg, empty) == {}
            check("handles an empty data folder", ok)
        finally:
            shutil.rmtree(empty, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nvenue_split selftest: %s" % ("ALL PASS" if not fails else "FAILED: " + ", ".join(fails)))
    return 0 if not fails else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        sys.exit(selftest())
    report(E.load_config(), E.DATA_DIR)
