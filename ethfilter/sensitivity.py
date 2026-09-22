#!/usr/bin/env python3
"""
sensitivity.py - the exploratory checks specified in preregistration_addendum_2.md

READ-ONLY. Imports ethfilter's scoring functions and reads ethfilter/data/.
It never writes a file, never calls an API, and never changes a primary result.
Every number it prints is exploratory and carries no verdict.

Why it exists, from an outside review of the design on 2026-09-22:

1. FILL OPTIMISM. The pre-registered fill rule lets a ladder rung fill when a
   15-minute candle's HIGH reaches it. A real sell does not land on the high of
   the bar. If the ladder beats holding under that rule but not under a stricter
   one, the win is mark-to-high, not an executable exit. This reruns the primary
   Q2 comparison under three fill rules, strictest last.

2. THRESHOLD ARBITRARINESS. Q1 splits tokens at exactly one point: pass or
   reject. If the filter is measuring something real, forward returns should
   change gradually as tokens get further above or below the thresholds. If the
   only change is a jump at the line, the thresholds are arbitrary and the split
   is doing the work. This bins tokens by how far they sat from the thresholds.

Usage:
  python sensitivity.py            # report on ethfilter/data
  python sensitivity.py selftest   # checks on simulated data
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

HAIRCUT = 0.98          # fill rule 2: the rung must be reached 2% below the high
MIN_PATHS = 30          # before a CI is printed
MIN_BUCKET = 20         # before a bucket's median is printed

FILL_MODES = [
    ("high (pre-registered)", "high"),
    ("high minus 2%", "haircut"),
    ("close only (strictest)", "close"),
]

BUCKETS = [
    ("under 0.25x", 0.0, 0.25),
    ("0.25x to 0.5x", 0.25, 0.5),
    ("0.5x to 1x", 0.5, 1.0),
    ("1x to 2x", 1.0, 2.0),
    ("2x and above", 2.0, float("inf")),
]


def retune(candles, mode):
    """Return the same candles with the fill reference lowered. None stays None."""
    if candles is None or mode == "high":
        return candles
    out = []
    for ts, o, h, l, c, v in candles:
        nh = (h or 0.0) * HAIRCUT if mode == "haircut" else (c or 0.0)
        out.append((ts, o, nh, l, c, v))
    return out


def threshold_ratio(cfg, tk):
    """
    How close the token was to the filter, as the binding clause. 1.0 means it
    sat exactly on the tightest threshold; below 1.0 it was rejected.
    """
    f = cfg["filter"]
    parts = []
    for value, floor in ((tk.get("eval_mcap"), f["min_market_cap_usd"]),
                         (tk.get("eval_vol_h1"), f["min_volume_h1_usd"]),
                         (tk.get("eval_liq"), f["min_liquidity_usd"])):
        if value is None or floor <= 0:
            return None
        parts.append(value / float(floor))
    return min(parts)


def report(cfg, data_dir, out=print):
    rows = E._rows(cfg, data_dir)
    out("=" * 66)
    out("EXPLORATORY: FILL SENSITIVITY AND THRESHOLD SHAPE   run_id=%s" % cfg["run_id"])
    out("=" * 66)
    out("Pre-specified in preregistration_addendum_2.md. No verdicts here. The")
    out("primary results stay the ones `score` and `ladder` print, unchanged.")
    if not rows:
        out("no scored tokens yet")
        return {}

    result = {"fills": {}, "buckets": {}}

    # ---- 1. how much of any Q2 result survives a stricter fill ---------------
    prim, base = cfg["primary"]["q2_policy"], cfg["primary"]["q2_baseline"]
    usable = [r for r in rows if r[0]["ohlcv"] is not None and r[2] is not None]
    out("\n-- Q2 primary (%s vs %s) under three fill rules --" % (prim, base))
    out("Same paths every time. Only the price a rung is allowed to fill at changes.")
    if len(usable) < MIN_PATHS:
        out("%d complete paths, need %d. Nothing to report yet." % (len(usable), MIN_PATHS))
    else:
        for label, mode in FILL_MODES:
            diffs, prim_rets = [], []
            for tk, cps, candles in usable:
                shifted = retune(candles, mode)
                vals = {}
                for name, pol in cfg["exit_policies"].items():
                    v = E.policy_value(pol, tk["eval_price"], shifted, cps, cfg)
                    if v is None:
                        vals = None
                        break
                    vals[name] = E.net_return(v, cfg)
                if vals:
                    diffs.append(vals[prim] - vals[base])
                    prim_rets.append(vals[prim])
            if len(diffs) < MIN_PATHS:
                out("  %-24s too few paths (%d)" % (label, len(diffs)))
                continue
            m, lo, hi = E.paired_bootstrap_ci(diffs, iters=cfg["bootstraps"])
            verdict = "above zero" if lo > 0 else ("below zero" if hi < 0 else "straddles zero")
            out("  %-24s n=%-4d  %+7.1f pp  [%+7.1f, %+7.1f]  %s"
                % (label, len(diffs), 100 * m, 100 * lo, 100 * hi, verdict))
            out("  %-24s   ladder median net return %+.1f%%" % ("", 100 * E.median(prim_rets)))
            result["fills"][mode] = (m, lo, hi)
        out("\n  If the first line is above zero and the last is not, the ladder's edge")
        out("  is mark-to-high and should be reported that way.")

    # ---- 2. does the filter measure a gradient, or just cut a line? ----------
    H = float(cfg["primary"]["q1_horizon_hours"])
    out("\n-- Q1 at %gh by distance from the filter thresholds --" % H)
    out("Ratio is the binding clause: market cap, 1h volume or liquidity over its")
    out("floor, whichever is smallest. Tokens at 1.0 and above are the pass arm.")
    graded = []
    for tk, cps, _c in rows:
        ev = tk["cps"].get(H)
        if not ev or ev["status"] != "ok":
            continue
        ratio = threshold_ratio(cfg, tk)
        if ratio is None:
            continue
        g = E.policy_value({"type": "hold", "hours": H}, tk["eval_price"], None, cps, cfg)
        graded.append((ratio, E.net_return(g, cfg), tk["status"]))
    if not graded:
        out("no tokens with a %gh checkpoint yet" % H)
        return result

    out("\n  %-16s %6s %10s %8s" % ("distance", "n", "median", "arm"))
    for label, lo_b, hi_b in BUCKETS:
        vals = [r for ratio, r, _s in graded if lo_b <= ratio < hi_b]
        arms = set(s for ratio, _r, s in graded if lo_b <= ratio < hi_b)
        arm = "/".join(sorted(arms)) if arms else "-"
        if len(vals) >= MIN_BUCKET:
            out("  %-16s %6d %9.1f%% %8s" % (label, len(vals), 100 * E.median(vals), arm))
            result["buckets"][label] = (len(vals), E.median(vals))
        else:
            out("  %-16s %6d %10s %8s" % (label, len(vals), "too few", arm))
    out("\n  A gradient across buckets supports the filter measuring something real.")
    out("  A flat line with a jump only at 1.0 says the cut point is doing the work.")
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
        print("  %-52s %s %s" % (name, "PASS" if ok else "FAIL", detail))
        if not ok:
            fails.append(name)

    cfg = E.load_config()

    print("-- fill rules --")
    cps = {0.0: (0, 1.0, 50000.0), 168.0: (604800, 1.0, 50000.0)}
    # high reaches 2x, close does not
    wick = [(900, 1.0, 2.05, 0.95, 1.10, 1000.0), (1800, 1.10, 1.20, 1.0, 1.0, 1000.0)]
    pol = {"type": "ladder", "multiples": [2.0]}
    hi = E.policy_value(pol, 1.0, retune(wick, "high"), cps, cfg)
    hc = E.policy_value(pol, 1.0, retune(wick, "haircut"), cps, cfg)
    cl = E.policy_value(pol, 1.0, retune(wick, "close"), cps, cfg)
    check("high fills the rung on the wick", abs(hi - 2.0) < 1e-9, "got %.3f" % hi)
    check("2% haircut still fills (2.05 x 0.98 = 2.009)", abs(hc - 2.0) < 1e-9, "got %.3f" % hc)
    check("close only does not fill", abs(cl - 1.0) < 1e-9, "got %.3f" % cl)
    check("strictness is ordered", cl <= hc <= hi)
    near = [(900, 1.0, 2.01, 0.95, 1.10, 1000.0)]
    hc2 = E.policy_value(pol, 1.0, retune(near, "haircut"), cps, cfg)
    check("2% haircut blocks a rung only just touched", abs(hc2 - 1.0) < 1e-9, "got %.3f" % hc2)
    check("hold policies are untouched by fill mode",
          E.policy_value({"type": "hold", "hours": 168}, 1.0, retune(wick, "close"), cps, cfg)
          == E.policy_value({"type": "hold", "hours": 168}, 1.0, wick, cps, cfg))

    print("-- threshold ratio --")
    tk = {"eval_mcap": 50000.0, "eval_vol_h1": 2000.0, "eval_liq": 20000.0}
    check("ratio is the binding clause", abs(threshold_ratio(cfg, tk) - 2.0) < 1e-9)
    tk2 = dict(tk, eval_liq=5000.0)
    check("a failing clause pulls the ratio under 1", threshold_ratio(cfg, tk2) < 1.0)
    check("missing data returns nothing", threshold_ratio(cfg, dict(tk, eval_mcap=None)) is None)

    print("-- runs on simulated data without touching it --")
    tmp = tempfile.mkdtemp(prefix="sens_sim_")
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
        fast = dict(cfg, bootstraps=400)
        with contextlib.redirect_stdout(buf):
            res = report(fast, tmp)
        text = buf.getvalue()
        check("never writes to the data folder", before == _snapshot(tmp) and len(before) > 0)
        check("prints all three fill rules",
              all(label in text for label, _m in FILL_MODES))
        check("prints no verdicts", "VERDICT" not in text)
        check("produces fill estimates", len(res["fills"]) >= 1, "%d modes" % len(res["fills"]))
        check("buckets the tokens", "distance" in text)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nsensitivity selftest: %s" % ("ALL PASS" if not fails else "FAILED: " + ", ".join(fails)))
    return 0 if not fails else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        sys.exit(selftest())
    report(E.load_config(), E.DATA_DIR)
