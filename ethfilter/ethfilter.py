#!/usr/bin/env python3
"""
ethfilter v3 - independent prospective test on Robinhood Chain.

Revised 2026-09-21. No data was ever collected under v1 or v2.

v3 changes from v2 (full table in preregistration.md):
 1. RIGHT CHAIN. The @insentos video was "BEST FILTERS TO TRADE ON ROBINHOOD",
    meaning Robinhood Chain (Arbitrum-stack L2, mainnet July 1 2026, ETH gas).
    v1 and v2 misread it as a token name and tested Base.
 2. SAFETY HALF DROPPED. Claude Code found GoPlus returned no usable security
    data even on Base (0 of 40 tokens). No free source covers Robinhood Chain's
    Uniswap v4 hook pools. Q1 now tests the market-size half of the filter only.
 3. HONEYPOT GUARD. A pool needs at least 3 distinct sellers in the last hour to
    enter the tradeable universe. A pure honeypot shows buys and a rising price
    that nobody can sell into; without this it would score as a big winner.
 4. SPOOF GUARD. A pool reporting liquidity above 2x its FDV is rejected.
    Claude Code saw $98.7M of "liquidity" on a 69-minute-old pool.

Kept from v2: batched reads, fixed liquidity checkpoints, one candle call per
path, failed reads never become data, append-only event log, pre-registered
tradeable-universe gate, one primary result per question.

All API parsing is isolated in the Api class. The `api` block in config.json is
operational and may be tuned at any time. Everything else is locked once the
first `run` writes an event.

Commands:
  python ethfilter.py run        # one cycle: collect, evaluate, checkpoints, candles
  python ethfilter.py status     # progress, API health, gate reasons
  python ethfilter.py score      # Q1: does the size filter beat its own rejects?
  python ethfilter.py ladder     # Q2: does laddering out beat holding? (paired)
  python ethfilter.py selftest   # logic tests + simulated 10 days with honeypots
"""

import argparse
import glob
import gzip
import json
import math
import os
import random
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
DATA_DIR = os.path.join(HERE, "data")

GT = "https://api.geckoterminal.com/api/v2"
UA = "ethfilter/3.0 (prospective research script)"

OK, THROTTLED, NOT_FOUND, ERROR, BUDGET = "ok", "throttled", "not_found", "error", "budget"

FINAL_ARMS = ("pass", "reject")


# ============================================================================
# helpers
# ============================================================================

def iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def fnum(x, default=None):
    if x is None or x == "":
        return default
    try:
        v = float(x)
        return default if (math.isnan(v) or math.isinf(v)) else v
    except (TypeError, ValueError):
        return default


def parse_iso(s):
    if not s:
        return None
    try:
        return int(datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp())
    except Exception:
        return None


def load_config(path=CONFIG_PATH):
    with open(path) as f:
        return json.load(f)


def http_get(url, timeout=25):
    """Return (http_status_or_None, parsed_json_or_None). Never raises."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return None, None


# ============================================================================
# API layer - every network call and every bit of response parsing lives here
# ============================================================================

class Api:
    """
    Enforces spacing, a per-run call budget, a wall-clock deadline, and backoff.
    Every call returns (kind, payload). Callers must treat any kind other than
    OK as "no information this time". Never as zero, never as dead.
    """

    def __init__(self, cfg, getter=http_get, sleeper=time.sleep, clock=time.time):
        a = cfg["api"]
        self.gt_spacing = a["gt_min_spacing_sec"]
        self.gt_left = a["gt_max_calls_per_run"]
        self.max_consec_429 = a["stop_after_consecutive_429"]
        self.backoff = list(a["backoff_sec"])
        self.get, self.sleep, self.clock = getter, sleeper, clock
        self.deadline = clock() + a["run_wallclock_budget_sec"]
        self._last_gt = -1e18
        self.consec_429 = 0
        self.halted = False
        self.stats = dict(gt_calls=0, gt_ok=0, gt_429=0, gt_404=0, gt_err=0, halted=0)

    def gt_available(self):
        return not self.halted and self.gt_left > 0 and self.clock() < self.deadline

    def _gt(self, path):
        attempt = 0
        while True:
            if not self.gt_available():
                return BUDGET, None
            wait = self.gt_spacing - (self.clock() - self._last_gt)
            if wait > 0:
                self.sleep(wait)
            self.gt_left -= 1
            self.stats["gt_calls"] += 1
            self._last_gt = self.clock()
            status, data = self.get(GT + path)
            if status == 200 and data is not None:
                self.consec_429 = 0
                self.stats["gt_ok"] += 1
                return OK, data
            if status == 429:
                self.stats["gt_429"] += 1
                self.consec_429 += 1
                if self.consec_429 >= self.max_consec_429:
                    self.halted = True
                    self.stats["halted"] = 1
                    return THROTTLED, None
                if attempt < len(self.backoff):
                    self.sleep(self.backoff[attempt])
                    attempt += 1
                    continue
                return THROTTLED, None
            self.consec_429 = 0
            if status == 404:
                self.stats["gt_404"] += 1
                return NOT_FOUND, None
            self.stats["gt_err"] += 1
            return ERROR, None

    @staticmethod
    def _rel_id(item, name):
        return ((((item.get("relationships") or {}).get(name) or {})
                 .get("data") or {}).get("id") or "")

    @staticmethod
    def _tail(x):
        return x.split("_", 1)[1].lower() if x and "_" in x else None

    # -- newest pools -----------------------------------------------------------
    def new_pools(self, network, page):
        """
        GET /networks/{network}/new_pools?page=N
        Expect: {"data":[{"attributes":{"address","name","pool_created_at"},
                 "relationships":{"base_token":{"data":{"id":"<net>_0xTOKEN"}},
                                  "quote_token":{"data":{"id":"<net>_0xQUOTE"}},
                                  "dex":{"data":{"id":"uniswap-v4-..."}}}}]}
        On Uniswap v4 the pool "address" is a 32-byte pool id, not a contract.
        """
        kind, data = self._gt("/networks/%s/new_pools?page=%d" % (network, page))
        if kind != OK:
            return kind, []
        out = []
        for item in data.get("data") or []:
            a = item.get("attributes") or {}
            addr = (a.get("address") or "").lower()
            if not addr:
                continue
            out.append({
                "pool_id": "%s_%s" % (network, addr),
                "pool": addr,
                "token": self._tail(self._rel_id(item, "base_token")),
                "quote": self._tail(self._rel_id(item, "quote_token")),
                "dex": self._rel_id(item, "dex") or None,
                "name": a.get("name"),
                "created": parse_iso(a.get("pool_created_at")),
            })
        return OK, out

    # -- many pools in one call -------------------------------------------------
    def pools_multi(self, network, addresses):
        """
        GET /networks/{network}/pools/multi/{a1,a2,...}
        Expect attributes: address, base_token_price_usd, market_cap_usd, fdv_usd,
        reserve_in_usd, volume_usd.h1, transactions.h1.{buys,sells,buyers,sellers}.
        Pools GeckoTerminal does not know are omitted. An omitted pool is "no read
        this time", never dead. A missing seller count is recorded as None and the
        universe gate treats it as unknown, never as zero.
        """
        kind, data = self._gt("/networks/%s/pools/multi/%s" % (network, ",".join(addresses)))
        if kind != OK:
            return kind, {}
        out = {}
        for item in data.get("data") or []:
            a = item.get("attributes") or {}
            addr = (a.get("address") or "").lower()
            if not addr:
                continue
            vol = a.get("volume_usd") or {}
            tx = (a.get("transactions") or {}).get("h1") or {}
            fdv = fnum(a.get("fdv_usd"))
            mcap = fnum(a.get("market_cap_usd")) or fdv
            sellers = fnum(tx.get("sellers"))
            out[addr] = {
                "price": fnum(a.get("base_token_price_usd")),
                "mcap": mcap,
                "fdv": fdv if fdv is not None else mcap,
                "liq": fnum(a.get("reserve_in_usd")),
                "vol_h1": fnum(vol.get("h1"), 0.0),
                "sellers_h1": None if sellers is None else int(sellers),
                "buys_h1": int(fnum(tx.get("buys"), 0.0)),
                "sells_h1": int(fnum(tx.get("sells"), 0.0)),
            }
        return OK, out

    # -- 15-minute candles --------------------------------------------------------
    def ohlcv(self, network, pool, before_ts, limit):
        """
        GET /networks/{n}/pools/{addr}/ohlcv/minute?aggregate=15&before_timestamp=T&limit=N
        Expect: {"data":{"attributes":{"ohlcv_list":[[ts,o,h,l,c,v], ...]}}}
        """
        path = ("/networks/%s/pools/%s/ohlcv/minute?aggregate=15&before_timestamp=%d"
                "&limit=%d&currency=usd" % (network, pool, int(before_ts), int(limit)))
        kind, data = self._gt(path)
        if kind != OK:
            return kind, []
        rows = ((data.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
        out = []
        for r in rows:
            if isinstance(r, (list, tuple)) and len(r) >= 6:
                out.append((int(fnum(r[0], 0)),) + tuple(fnum(x, 0.0) for x in r[1:6]))
        out.sort()
        return OK, out


# ============================================================================
# pure logic - no I/O, fully covered by selftest
# ============================================================================

def universe_gate(cfg, st):
    """
    Tradeable-universe gate, applied before the filter. Returns (ok, reason).
    Checks run in this order and the first failure is the recorded reason:
      unpriceable, liquidity floor, volume floor,
      spoofed liquidity (a real pool cannot hold more than ~2x its FDV),
      seller count unknown, too few distinct sellers (honeypot proxy).
    """
    u = cfg["universe"]
    if st is None or not st.get("price") or st["price"] <= 0:
        return False, "unpriceable"
    liq = st.get("liq") or 0
    if liq < u["min_liquidity_usd"]:
        return False, "liq<%g" % u["min_liquidity_usd"]
    if (st.get("vol_h1") or 0) < u["min_volume_h1_usd"]:
        return False, "vol_h1<%g" % u["min_volume_h1_usd"]
    fdv = st.get("fdv") or 0
    if fdv <= 0 or liq > u["max_liq_to_fdv"] * fdv:
        return False, "liquidity_spoofed"
    sellers = st.get("sellers_h1")
    if sellers is None:
        return False, "sellers_unknown"
    if sellers < u["min_sellers_h1"]:
        return False, "sellers<%d" % u["min_sellers_h1"]
    return True, ""


def market_fails(cfg, st):
    f = cfg["filter"]
    out = []
    if (st.get("mcap") or 0) < f["min_market_cap_usd"]:
        out.append("mcap")
    if (st.get("liq") or 0) < f["min_liquidity_usd"]:
        out.append("liq")
    if (st.get("vol_h1") or 0) < f["min_volume_h1_usd"]:
        out.append("vol")
    return out


def net_return(gross, cfg):
    c = cfg["costs"]
    drag = (1 - c["slippage_in"]) * (1 - c["slippage_out"]) * (1 - c["fee_round_trip"])
    return gross * drag - 1.0


def policy_value(policy, entry, candles, cps, cfg):
    """
    Gross multiple of starting capital returned by one exit policy.

    entry   : price at evaluation
    candles : [(ts,o,h,l,c,v)] ascending, eval_ts <= ts < eval_ts+168h (may be None)
    cps     : {hours: (ts, price, liq)} successful checkpoints, 0 = evaluation
    Returns None when the data this policy needs is missing.

    Rules (pre-registered):
      - A checkpoint with liquidity under the dead threshold is worth 0.
      - A rung or target fills in the first candle whose HIGH reaches it, if that
        candle traded (volume > 0) and the latest checkpoint at or before it
        showed live liquidity. Using highs, not snapshots, is what lets a rung
        that was touched between readings actually count.
      - A trailing stop exits on a candle CLOSE, and only if that candle is
        fillable. If you cannot sell, you are still holding.
      - Anything left at the end is valued at the 168h checkpoint.
    """
    dead = cfg["dead_liquidity_usd"]

    def at(h):
        cp = cps.get(h)
        if cp is None:
            return None
        _, price, liq = cp
        if liq is None or liq < dead or not price or price <= 0:
            return 0.0
        return price / entry

    kind = policy["type"]
    if kind == "hold":
        return at(policy["hours"])

    end_val = at(168)
    if end_val is None or candles is None:
        return None

    cp_list = sorted((ts, liq) for (ts, _p, liq) in cps.values())

    def fillable(ts, vol):
        if not vol or vol <= 0:
            return False
        last = None
        for cts, liq in cp_list:
            if cts <= ts:
                last = liq
            else:
                break
        return last is not None and last >= dead

    if kind in ("ladder", "single_target"):
        rungs = list(policy["multiples"]) if kind == "ladder" else [policy["multiple"]]
        frac = 1.0 / len(rungs)
        hit = [False] * len(rungs)
        proceeds, remaining = 0.0, 1.0
        for ts, _o, h, _l, _c, v in candles:
            if not fillable(ts, v):
                continue
            for i, m in enumerate(rungs):
                if not hit[i] and h >= m * entry:
                    hit[i] = True
                    proceeds += frac * m
                    remaining -= frac
            if remaining <= 1e-12:
                return proceeds
        return proceeds + max(remaining, 0.0) * end_val

    if kind == "trailing_stop":
        dd = policy["drawdown"]
        peak = entry
        for ts, _o, _h, _l, c, v in candles:
            if c <= 0:
                continue
            peak = max(peak, c)
            if c <= peak * (1 - dd) and fillable(ts, v):
                return c / entry
        return end_val

    raise ValueError("unknown policy type %r" % kind)


def max_fillable_multiple(entry, candles, cps, cfg):
    """Highest multiple of entry that was actually sellable at any point."""
    if not candles:
        return 1.0
    dead = cfg["dead_liquidity_usd"]
    cp_list = sorted((ts, liq) for (ts, _p, liq) in cps.values())
    best = 0.0
    for ts, _o, h, _l, _c, v in candles:
        if not v or v <= 0:
            continue
        last = None
        for cts, liq in cp_list:
            if cts <= ts:
                last = liq
            else:
                break
        if last is not None and last >= dead:
            best = max(best, h / entry)
    return best


# ---- statistics --------------------------------------------------------------

def regime(tk, cfg):
    """Which side of the Robinhood Wallet gas-rebate expiry a token was evaluated on."""
    return "before" if tk["eval_ts"] < parse_iso(cfg["regime_split_utc"]) else "after"


def median(xs):
    if not xs:
        return float("nan")
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def permutation_p(a, b, iters=10000, seed=17):
    rng = random.Random(seed)
    obs = median(a) - median(b)
    pool = list(a) + list(b)
    na = len(a)
    hits = 0
    for _ in range(iters):
        rng.shuffle(pool)
        if abs(median(pool[:na]) - median(pool[na:])) >= abs(obs):
            hits += 1
    return obs, (hits + 1) / (iters + 1)


def paired_bootstrap_ci(diffs, iters=10000, seed=23, alpha=0.05):
    if not diffs:
        return float("nan"), float("nan"), float("nan")
    rng = random.Random(seed)
    n = len(diffs)
    ms = sorted(mean([diffs[rng.randrange(n)] for _ in range(n)]) for _ in range(iters))
    return mean(diffs), ms[int(alpha / 2 * iters)], ms[min(iters - 1, int((1 - alpha / 2) * iters))]


# ============================================================================
# storage - append-only daily event log + write-once candle files
# ============================================================================

def events_dir(d):
    return os.path.join(d, "events")


def candles_dir(d):
    return os.path.join(d, "candles")


def new_token(ev):
    return {"pool_id": ev["pool_id"], "net": ev["net"], "pool": ev["pool"],
            "token": ev.get("token"), "quote": ev.get("quote"), "dex": ev.get("dex"),
            "name": ev.get("name"), "created": ev.get("created"),
            "first_seen": ev["t"], "status": "pending", "eval_ts": None,
            "eval_price": None, "eval_mcap": None, "eval_liq": None, "eval_vol_h1": None,
            "eval_sellers_h1": None, "reasons": "", "cps": {}, "ohlcv": None}


def apply_event(tokens, runs, ev):
    e = ev["e"]
    if e == "pool":
        if ev["pool_id"] not in tokens:
            tokens[ev["pool_id"]] = new_token(ev)
        return
    if e == "run":
        runs.append(ev)
        return
    tk = tokens.get(ev.get("pool_id"))
    if tk is None:
        return
    if e == "eval":
        if "price" in ev and tk["eval_ts"] is None:
            tk.update(eval_ts=ev["t"], eval_price=ev["price"], eval_mcap=ev.get("mcap"),
                      eval_liq=ev.get("liq"), eval_vol_h1=ev.get("vol_h1"),
                      eval_sellers_h1=ev.get("sellers_h1"))
        tk["status"] = ev["status"]
        if "reasons" in ev:
            tk["reasons"] = ev["reasons"]
    elif e == "cp":
        tk["cps"][float(ev["h"])] = ev
    elif e == "ohlcv":
        tk["ohlcv"] = ev


def load_state(data_dir):
    tokens, runs = {}, []
    for fn in sorted(glob.glob(os.path.join(events_dir(data_dir), "*.jsonl"))):
        with open(fn) as f:
            for line in f:
                line = line.strip()
                if line:
                    apply_event(tokens, runs, json.loads(line))
    return tokens, runs


def append_events(data_dir, evs, now):
    if not evs:
        return
    os.makedirs(events_dir(data_dir), exist_ok=True)
    fn = os.path.join(events_dir(data_dir),
                      datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d") + ".jsonl")
    with open(fn, "a") as f:
        for ev in evs:
            f.write(json.dumps(ev, separators=(",", ":")) + "\n")


def candle_path(data_dir, pool_id):
    return os.path.join(candles_dir(data_dir), pool_id + ".json.gz")


def _sig(x):
    return float("%.6g" % x) if x else 0.0


def write_candles_once(data_dir, pool_id, eval_ts, rows):
    """
    Write-once, compact storage: candle index (15-min steps from eval), high,
    close, volume, 6 significant figures. Open and low are not stored because
    no pre-registered policy uses them. A file is never rewritten.
    """
    os.makedirs(candles_dir(data_dir), exist_ok=True)
    p = candle_path(data_dir, pool_id)
    if not os.path.exists(p):
        doc = {"pool_id": pool_id, "eval_ts": eval_ts, "step": 900,
               "k": [int((r[0] - eval_ts) // 900) for r in rows],
               "h": [_sig(r[2]) for r in rows],
               "c": [_sig(r[4]) for r in rows],
               "v": [_sig(r[5]) for r in rows]}
        with gzip.open(p, "wt") as f:
            json.dump(doc, f, separators=(",", ":"))
    return os.path.relpath(p, data_dir)


def read_candles(data_dir, pool_id):
    p = candle_path(data_dir, pool_id)
    if not os.path.exists(p):
        return None
    with gzip.open(p, "rt") as f:
        d = json.load(f)
    t0, step = d["eval_ts"], d["step"]
    return [(t0 + k * step, None, h, None, c, v)
            for k, h, c, v in zip(d["k"], d["h"], d["c"], d["v"])]


# ============================================================================
# the pipeline - one call does one cycle
# ============================================================================

def chunks(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def run_cycle(cfg, api, data_dir, now):
    tokens, runs = load_state(data_dir)
    out = []

    def emit(ev):
        ev.setdefault("t", now)
        out.append(ev)
        apply_event(tokens, runs, ev)

    dead = cfg["dead_liquidity_usd"]
    batch = int(cfg["api"].get("gt_multi_batch", 30))

    # 1. collect ---------------------------------------------------------------
    for network in cfg["networks"]:
        for page in range(1, cfg["collect_pages"] + 1):
            kind, pools = api.new_pools(network, page)
            if kind != OK:
                break
            fresh = 0
            for p in pools:
                if p["pool_id"] in tokens or p["created"] is None:
                    continue
                emit({"e": "pool", "pool_id": p["pool_id"], "net": network, "pool": p["pool"],
                      "token": p["token"], "quote": p["quote"], "dex": p["dex"],
                      "name": p["name"], "created": p["created"]})
                fresh += 1
            if fresh == 0:
                break   # this page is all known, older pages are too

    # 2. evaluate once, at a fixed age: universe gate, then the size filter ----
    lo = cfg["evaluate_at_age_min"] * 60
    hi = lo + cfg["evaluate_window_min"] * 60
    ready = []
    for tk in list(tokens.values()):
        if tk["status"] != "pending" or tk["created"] is None:
            continue
        age = now - tk["created"]
        if age > hi:
            emit({"e": "eval", "pool_id": tk["pool_id"], "status": "missed_window",
                  "reasons": "never_read_inside_window"})
        elif age >= lo:
            ready.append(tk)
    ready.sort(key=lambda t: t["created"])
    stop = False
    for network in cfg["networks"]:
        mine = [t for t in ready if t["net"] == network]
        for chunk in chunks(mine, batch):
            if not api.gt_available():
                stop = True
                break
            kind, states = api.pools_multi(network, [t["pool"] for t in chunk])
            if kind != OK:
                continue
            for tk in chunk:
                st = states.get(tk["pool"])
                if st is None:
                    continue   # omitted this time: retry next cycle, never assume
                snap = {"price": st["price"], "mcap": st["mcap"], "fdv": st["fdv"],
                        "liq": st["liq"], "vol_h1": st["vol_h1"],
                        "sellers_h1": st["sellers_h1"],
                        "age_min": round((now - tk["created"]) / 60.0, 1)}
                ok, why = universe_gate(cfg, st)
                if not ok:
                    emit(dict(e="eval", pool_id=tk["pool_id"], status="untradeable",
                              reasons=why, **snap))
                    continue
                mf = market_fails(cfg, st)
                emit(dict(e="eval", pool_id=tk["pool_id"], status="reject" if mf else "pass",
                          reasons=";".join(mf), **snap))
        if stop:
            break

    # 3. liquidity checkpoints ----------------------------------------------------
    due = []
    for tk in tokens.values():
        if tk["status"] not in FINAL_ARMS:
            continue
        for H, tol in cfg["checkpoints"]:
            H = float(H)
            if H in tk["cps"]:
                continue
            target = tk["eval_ts"] + H * 3600
            if now < target:
                break
            if now > target + tol * 3600:
                emit({"e": "cp", "pool_id": tk["pool_id"], "h": H, "status": "missing"})
                continue
            due.append((target + tol * 3600, tk, H))
            break
    due.sort(key=lambda x: x[0])
    stop = False
    for network in cfg["networks"]:
        mine = [d for d in due if d[1]["net"] == network]
        for chunk in chunks(mine, batch):
            if not api.gt_available():
                stop = True
                break
            kind, states = api.pools_multi(network, [d[1]["pool"] for d in chunk])
            if kind != OK:
                continue
            for _dl, tk, H in chunk:
                st = states.get(tk["pool"])
                if st is None or st.get("liq") is None:
                    continue
                if st["liq"] >= dead and (not st.get("price") or st["price"] <= 0):
                    continue   # live pool with no price is a bad read, not a fact
                emit({"e": "cp", "pool_id": tk["pool_id"], "h": H, "status": "ok",
                      "price": st["price"], "liq": st["liq"],
                      "sellers_h1": st.get("sellers_h1")})
        if stop:
            break

    # 4. candles, once per token, after the 7-day window closes --------------------
    todo = []
    for tk in tokens.values():
        if tk["status"] not in FINAL_ARMS or tk["ohlcv"] is not None:
            continue
        cp = tk["cps"].get(168.0)
        if cp is None:
            continue
        if cp["status"] != "ok":
            emit({"e": "ohlcv", "pool_id": tk["pool_id"], "status": "skipped",
                  "reason": "168h_checkpoint_missing"})
            continue
        ready_ts = tk["eval_ts"] + 169 * 3600
        if now < ready_ts:
            continue
        if now > ready_ts + cfg["ohlcv_tolerance_hours"] * 3600:
            emit({"e": "ohlcv", "pool_id": tk["pool_id"], "status": "missing"})
            continue
        todo.append(tk)
    todo.sort(key=lambda t: t["eval_ts"])
    for tk in todo:
        if not api.gt_available():
            break
        kind, rows = api.ohlcv(tk["net"], tk["pool"], tk["eval_ts"] + 168 * 3600 + 900,
                               cfg["ohlcv_limit"])
        if kind != OK:
            continue
        end = tk["eval_ts"] + 168 * 3600
        window = [list(r) for r in rows if tk["eval_ts"] <= r[0] < end]
        rel = write_candles_once(data_dir, tk["pool_id"], tk["eval_ts"], window)
        emit({"e": "ohlcv", "pool_id": tk["pool_id"], "status": "ok", "n": len(window), "file": rel})

    emit({"e": "run", "stats": api.stats, "run_id": cfg["run_id"]})
    append_events(data_dir, out, now)
    return api.stats


# ============================================================================
# commands
# ============================================================================

def cmd_run(cfg, args):
    api = Api(cfg)
    stats = run_cycle(cfg, api, DATA_DIR, int(time.time()))
    print("run: %s" % json.dumps(stats))
    cmd_status(cfg, args)


def _arm_counts(tokens):
    c = {}
    for t in tokens.values():
        c[t["status"]] = c.get(t["status"], 0) + 1
    return c


def quote_symbol(tk):
    """Quote asset symbol from the pool name, e.g. 'HOOD / WETH 1%' -> 'WETH'."""
    n = tk.get("name") or ""
    if " / " in n:
        return n.split(" / ", 1)[1].split(" ")[0][:12]
    return (tk.get("quote") or "?")[:12]


def cmd_status(cfg, args, data_dir=None, now=None):
    data_dir = data_dir or DATA_DIR
    now = now or int(time.time())
    tokens, runs = load_state(data_dir)
    counts = _arm_counts(tokens)
    print("=" * 66)
    print("ethfilter status   run_id=%s" % cfg["run_id"])
    print("chain: %s" % ", ".join(cfg["networks"]))
    print("=" * 66)
    if not tokens:
        print("no data yet")
        return
    first = min(t["first_seen"] for t in tokens.values())
    print("collecting since %s  (%.1f days)" % (iso(first), (now - first) / 86400.0))
    print("pools seen      : %d" % len(tokens))
    for k in ("pending", "untradeable", "missed_window", "pass", "reject"):
        if counts.get(k):
            print("  %-16s %d" % (k, counts[k]))

    ur = {}
    for t in tokens.values():
        if t["status"] == "untradeable":
            key = t["reasons"].split("<")[0] or "?"
            ur[key] = ur.get(key, 0) + 1
    if ur:
        print("\nnot tradeable, by first failing check:")
        for k, v in sorted(ur.items(), key=lambda kv: -kv[1]):
            print("  %-20s %d" % (k, v))
        if ur.get("sellers_unknown", 0) > 0.5 * sum(ur.values()):
            print("  WARNING: most pools came back with no seller count.")
            print("  Check the transactions parsing in Api.pools_multi.")

    fin = [t for t in tokens.values() if t["status"] in FINAL_ARMS]
    if fin:
        qs = {}
        for t in fin:
            q = quote_symbol(t)
            qs[q] = qs.get(q, 0) + 1
        top = sorted(qs.items(), key=lambda kv: -kv[1])[:5]
        print("\ntradeable pools paired against: " + ", ".join("%s %d" % kv for kv in top))

    need = cfg["min_per_arm"]
    q1h = float(cfg["primary"]["q1_horizon_hours"])
    have = {a: sum(1 for t in fin if t["status"] == a
                   and t["cps"].get(q1h, {}).get("status") == "ok") for a in FINAL_ARMS}
    print("\nQ1 gate (%gh checkpoint read): pass %d/%d   reject %d/%d"
          % (q1h, have["pass"], need, have["reject"], need))
    paths = sum(1 for t in fin if (t["ohlcv"] or {}).get("status") == "ok")
    print("Q2 gate (7-day paths):          %d/%d" % (paths, cfg["min_paths_for_ladder"]))
    split = parse_iso(cfg["regime_split_utc"])
    nb = sum(1 for t in fin if t["eval_ts"] < split)
    print("evaluated before / after %s: %d / %d"
          % (cfg["regime_split_utc"][:10], nb, len(fin) - nb))

    recent = [r for r in runs if r["t"] >= now - 86400]
    if recent:
        tot = {}
        for r in recent:
            for k, v in r["stats"].items():
                tot[k] = tot.get(k, 0) + v
        calls = max(tot.get("gt_calls", 0), 1)
        print("\nAPI health, last 24h (%d runs):" % len(recent))
        print("  %d calls, %d ok, %d throttled (%.0f%%), halted in %d runs"
              % (tot.get("gt_calls", 0), tot.get("gt_ok", 0), tot.get("gt_429", 0),
                 100.0 * tot.get("gt_429", 0) / calls, tot.get("halted", 0)))
        if tot.get("gt_429", 0) > 0.5 * calls:
            print("  WARNING: more than half of calls are being throttled.")
            print("  The collector is falling behind. Raise api.gt_min_spacing_sec.")

    rr = {}
    for t in fin:
        if t["status"] == "reject":
            rr[t["reasons"]] = rr.get(t["reasons"], 0) + 1
    if rr:
        print("\nwhy tradeable pools failed the size filter:")
        for k, v in sorted(rr.items(), key=lambda kv: -kv[1])[:6]:
            print("  %-30s %d" % (k, v))


def _rows(cfg, data_dir):
    tokens, _ = load_state(data_dir)
    rows = []
    for tk in tokens.values():
        if tk["status"] not in FINAL_ARMS or not tk["eval_price"]:
            continue
        cps = {0.0: (tk["eval_ts"], tk["eval_price"], tk["eval_liq"])}
        for h, ev in tk["cps"].items():
            if ev["status"] == "ok":
                cps[h] = (ev["t"], ev.get("price"), ev.get("liq"))
        candles = None
        if (tk["ohlcv"] or {}).get("status") == "ok":
            candles = read_candles(data_dir, tk["pool_id"])
        rows.append((tk, cps, candles))
    return rows


def cmd_score(cfg, args, data_dir=None):
    data_dir = data_dir or DATA_DIR
    rows = _rows(cfg, data_dir)
    primary = float(cfg["primary"]["q1_horizon_hours"])
    print("=" * 66)
    print("Q1: DOES THE SIZE FILTER BEAT ITS OWN REJECTS?   run_id=%s" % cfg["run_id"])
    print("=" * 66)
    print("Tests the market-size half of the @insentos filter only. The safety half")
    print("cannot be reproduced from free data on this chain (see preregistration).")
    print("Primary horizon is %gh. Other horizons are exploratory and carry no verdict." % primary)
    result = {}
    for H, _tol in cfg["checkpoints"]:
        H = float(H)
        arms = {"pass": [], "reject": []}
        regs = {"pass": [], "reject": []}
        miss = {"pass": 0, "reject": 0}
        tot = {"pass": 0, "reject": 0}
        for tk, cps, _c in rows:
            ev = tk["cps"].get(H)
            if ev is None:
                continue
            tot[tk["status"]] += 1
            if ev["status"] != "ok":
                miss[tk["status"]] += 1
                continue
            g = policy_value({"type": "hold", "hours": H}, tk["eval_price"], None, cps, cfg)
            arms[tk["status"]].append(net_return(g, cfg))
            regs[tk["status"]].append(regime(tk, cfg))
        pa, pr = arms["pass"], arms["reject"]
        tag = "PRIMARY" if H == primary else "exploratory"
        print("\n-- %gh (%s) --" % (H, tag))
        for a, xs in (("pass", pa), ("reject", pr)):
            if xs:
                print("   %-6s n=%-5d median %+7.1f%%   missing %d/%d"
                      % (a, len(xs), 100 * median(xs), miss[a], tot[a]))
            else:
                print("   %-6s n=0" % a)
        mr = {a: (miss[a] / float(tot[a]) if tot[a] else 0.0) for a in FINAL_ARMS}
        if abs(mr["pass"] - mr["reject"]) > cfg["max_missing_rate_gap"]:
            print("   CAUTION: missing-data rates differ by more than %.0f points between arms."
                  % (100 * cfg["max_missing_rate_gap"]))
            print("   Per the pre-registration, this horizon's result is flagged unreliable.")
        if len(pa) < cfg["min_per_arm"] or len(pr) < cfg["min_per_arm"]:
            print("   no verdict: need %d per arm" % cfg["min_per_arm"])
            continue
        obs, p = permutation_p(pa, pr, iters=cfg["permutations"])
        result[H] = (obs, p)
        print("   gap %+.1f pp   permutation p = %.4f" % (100 * obs, p))
        if H == primary:
            if p < cfg["alpha"]:
                print("   VERDICT: the size filter separates the arms at alpha=%g." % cfg["alpha"])
            else:
                print("   VERDICT: cannot reject the null. The size filter is not shown to work.")
            print("   exploratory split at %s (gas rebate ends):" % cfg["regime_split_utc"][:10])
            for r in ("before", "after"):
                a = [v for v, g in zip(pa, regs["pass"]) if g == r]
                b = [v for v, g in zip(pr, regs["reject"]) if g == r]
                if a and b:
                    print("     %-6s pass n=%d median %+.1f%%  |  reject n=%d median %+.1f%%"
                          % (r, len(a), 100 * median(a), len(b), 100 * median(b)))
                else:
                    print("     %-6s not enough data" % r)
    return result


def cmd_ladder(cfg, args, data_dir=None):
    data_dir = data_dir or DATA_DIR
    arm = getattr(args, "arm", "all") if args else "all"
    rows = [r for r in _rows(cfg, data_dir) if arm == "all" or r[0]["status"] == arm]
    pol = cfg["exit_policies"]
    prim, base = cfg["primary"]["q2_policy"], cfg["primary"]["q2_baseline"]
    print("=" * 66)
    print("Q2: DOES LADDERING OUT BEAT HOLDING?   arm=%s  run_id=%s" % (arm, cfg["run_id"]))
    print("=" * 66)
    print("Paired: every policy is replayed over the identical price paths.")
    print("Primary comparison: %s vs %s. Everything else is exploratory." % (prim, base))

    results = {k: [] for k in pol}
    reach, regs = [], []
    excluded = 0
    pending = 0
    for tk, cps, candles in rows:
        if tk["ohlcv"] is None:
            pending += 1          # 7-day window not closed yet: not missing, just early
            continue
        vals = {}
        for name, p in pol.items():
            v = policy_value(p, tk["eval_price"], candles, cps, cfg)
            if v is None:
                break
            vals[name] = net_return(v, cfg)
        else:
            for k, v in vals.items():
                results[k].append(v)
            reach.append(max_fillable_multiple(tk["eval_price"], candles, cps, cfg))
            regs.append(regime(tk, cfg))
            continue
        excluded += 1
    n = len(reach)
    print("paths usable: %d   still inside their 7-day window: %d   excluded for missing data: %d"
          % (n, pending, excluded))
    if n < cfg["min_paths_for_ladder"]:
        print("no verdict: need %d paths. Keep collecting." % cfg["min_paths_for_ladder"])
        return None

    print("\nBase rates - share of tokens that were ever SELLABLE at these multiples:")
    for m in (1.5, 2, 3, 5, 10, 25, 50, 100):
        print("  %5gx   %5.1f%%" % (m, 100.0 * sum(1 for r in reach if r >= m) / n))

    print("\n%-16s %7s %10s %10s %7s" % ("policy", "n", "median", "mean", "wins"))
    for k, xs in results.items():
        print("%-16s %7d %9.1f%% %9.1f%% %6.0f%%" % (
            k, len(xs), 100 * median(xs), 100 * mean(xs),
            100.0 * sum(1 for x in xs if x > 0) / len(xs)))

    print("\nPaired difference vs %s, 95%% bootstrap CI on the mean:" % base)
    out = {}
    for k, xs in results.items():
        if k == base:
            continue
        m, lo, hi = paired_bootstrap_ci([a - b for a, b in zip(xs, results[base])],
                                        iters=cfg["bootstraps"])
        out[k] = (m, lo, hi)
        verdict = "beats" if lo > 0 else ("loses" if hi < 0 else "inconclusive")
        tag = "PRIMARY -> " + verdict.upper() if k == prim else "(exploratory) " + verdict
        print("  %-16s %+7.1f pp  [%+7.1f, %+7.1f]  %s" % (k, 100 * m, 100 * lo, 100 * hi, tag))

    print("\nExploratory split of the primary comparison at %s (gas rebate ends):"
          % cfg["regime_split_utc"][:10])
    for r in ("before", "after"):
        d = [a - b for a, b, g in zip(results[prim], results[base], regs) if g == r]
        if len(d) >= 30:
            m, lo, hi = paired_bootstrap_ci(d, iters=cfg["bootstraps"])
            print("  %-6s n=%-4d %+7.1f pp  [%+7.1f, %+7.1f]" % (r, len(d), 100 * m, 100 * lo, 100 * hi))
        else:
            print("  %-6s n=%d, too few to estimate" % (r, len(d)))
    return out


# ============================================================================
# selftest: logic checks + a simulated 10-day run through the REAL pipeline
# ============================================================================

class FakeWorld:
    """
    Serves responses in GeckoTerminal's JSON shapes, with throttling and omitted
    pools. Mixed in: honeypots (price only rises, nobody can sell) and pools
    whose reported liquidity is absurd next to their FDV. Normal pools' price
    paths are independent of every filter attribute, so the filter has NO edge
    here by construction.
    """

    def __init__(self, seed, t0):
        self.rng = random.Random(seed)
        self.t0, self.now = t0, t0
        self.pools = {}
        self.p_gt429, self.p_omit = 0.35, 0.03

    def spawn(self):
        r = self.rng
        roll = r.random()
        honeypot, spoofed = roll < 0.12, 0.12 <= roll < 0.18
        addr = "0x%064x" % r.getrandbits(256)          # v4-style 32-byte pool id
        path, x = [], 0.0
        for _ in range(12 * 24 * 10):
            if honeypot:
                x += abs(r.gauss(0, 0.0015))
            else:
                x += r.gauss(-0.0004, 0.03) + (r.choice([0.5, -0.5]) if r.random() < 0.002 else 0)
            path.append(math.exp(x))
        p0, supply = 10 ** r.uniform(-5, -3.3), 1e9
        fdv0 = p0 * supply
        if spoofed:
            liq0 = fdv0 * r.uniform(50, 5000)          # impossible for a real pool
        elif r.random() < 0.3:
            liq0 = 10 ** r.uniform(2.0, 3.2)           # junk: tiny liquidity
        else:
            liq0 = fdv0 * r.uniform(0.08, 1.0)         # real pools hold <= ~1x FDV
        weth = r.random() < 0.7
        self.pools[addr] = {
            "created": self.now, "token": "0x%040x" % r.getrandbits(160),
            "quote": "0x" + ("11" if weth else "22") * 20, "quote_sym": "WETH" if weth else "TSLA",
            "dex": r.choice(["uniswap-v4-robinhood", "uniswap-v3-robinhood"]),
            "p0": p0, "supply": supply, "liq0": liq0, "vol0": 10 ** r.uniform(2.5, 4.5),
            "sellers": 0 if honeypot else r.randint(1, 60),
            "honeypot": honeypot, "spoofed": spoofed,
            "death": self.now + (r.uniform(0.5, 9) * 86400 if r.random() < 0.5 else 1e18),
            "path": path,
        }

    def price(self, p, t):
        i = max(0, min(len(p["path"]) - 1, int((t - p["created"]) // 300)))
        return p["p0"] * p["path"][i]

    def liq(self, p, t):
        return p["liq0"] if t < p["death"] else 40.0

    def get(self, url):
        u = urllib.parse.urlparse(url)
        q = urllib.parse.parse_qs(u.query)
        if self.rng.random() < self.p_gt429:
            return 429, None
        parts = u.path.split("/")
        net = "robinhood"
        if parts[-1] == "new_pools":
            page = int(q.get("page", ["1"])[0])
            live = sorted(((a, p) for a, p in self.pools.items() if p["created"] <= self.now),
                          key=lambda ap: -ap[1]["created"])[(page - 1) * 20: page * 20]
            return 200, {"data": [{
                "attributes": {
                    "address": a, "name": "SIM / " + p["quote_sym"] + " 1%",
                    "pool_created_at": datetime.fromtimestamp(p["created"], tz=timezone.utc).isoformat()},
                "relationships": {
                    "base_token": {"data": {"id": net + "_" + p["token"]}},
                    "quote_token": {"data": {"id": net + "_" + p["quote"]}},
                    "dex": {"data": {"id": p["dex"]}}}} for a, p in live]}
        if "multi" in parts:
            data = []
            for a in parts[-1].split(","):
                p = self.pools.get(a)
                if p is None or self.rng.random() < self.p_omit:
                    continue
                pr = self.price(p, self.now)
                alive = self.now < p["death"]
                data.append({"attributes": {
                    "address": a, "base_token_price_usd": str(pr), "market_cap_usd": None,
                    "fdv_usd": str(pr * p["supply"]), "reserve_in_usd": str(self.liq(p, self.now)),
                    "volume_usd": {"h1": str(p["vol0"] if alive else 0)},
                    "transactions": {"h1": {
                        "buys": 40 if alive else 0, "sells": 2 * p["sellers"] if alive else 0,
                        "buyers": 30 if alive else 0, "sellers": p["sellers"] if alive else 0}}}})
            return 200, {"data": data}
        if "ohlcv" in parts:
            p = self.pools.get(parts[-3])
            if p is None:
                return 404, None
            before = int(q["before_timestamp"][0])
            lim = int(q["limit"][0])
            start = max(p["created"], before - lim * 900)
            rows, t = [], start - (start % 900)
            while t < before:
                pts = [self.price(p, t + k * 300) for k in range(3)]
                v = p["vol0"] if t < p["death"] else 0.0
                rows.append([t, pts[0], max(pts) * 1.02, min(pts) * 0.98, pts[-1], v])
                t += 900
            rows.reverse()
            return 200, {"data": {"attributes": {"ohlcv_list": rows}}}
        return 404, None


def cmd_selftest(cfg, args):
    fails = []

    def check(name, ok, detail=""):
        print("  %-54s %s %s" % (name, "PASS" if ok else "FAIL", detail))
        if not ok:
            fails.append(name)

    print("-- statistics under the null --")
    rng = random.Random(99)
    a = [math.exp(rng.gauss(-0.3, 1.2)) - 1 for _ in range(400)]
    b = [math.exp(rng.gauss(-0.3, 1.2)) - 1 for _ in range(400)]
    _, p = permutation_p(a, b, iters=3000)
    check("permutation test finds no edge in identical arms", p > 0.01, "p=%.3f" % p)
    m, lo, hi = paired_bootstrap_ci([0.0] * 200, iters=2000)
    check("paired bootstrap straddles zero for zero diffs", lo <= 0 <= hi)

    print("-- exit policy mechanics --")
    cps = {0.0: (0, 1.0, 50000.0), 168.0: (604800, 1.0, 50000.0)}
    wick = [(900, 1.0, 2.05, 0.95, 1.1, 1000.0), (1800, 1.1, 1.2, 1.0, 1.0, 1000.0)]
    g = policy_value({"type": "ladder", "multiples": [2.0, 4.0]}, 1.0, wick, cps, cfg)
    check("a rung touched by a candle HIGH fills", abs(g - (0.5 * 2.0 + 0.5 * 1.0)) < 1e-9,
          "got %.3f" % g)
    novol = [(900, 1.0, 5.0, 1.0, 1.0, 0.0)]
    g = policy_value({"type": "single_target", "multiple": 2.0}, 1.0, novol, cps, cfg)
    check("no fill on a candle with zero volume", abs(g - 1.0) < 1e-9, "got %.3f" % g)
    cps_dead = {0.0: (0, 1.0, 50000.0), 6.0: (21600, 0.01, 40.0), 168.0: (604800, 0.0, 10.0)}
    after = [(30000, 1.0, 9.0, 1.0, 1.0, 500.0)]
    g = policy_value({"type": "ladder", "multiples": [2.0]}, 1.0, after, cps_dead, cfg)
    check("no fill after a checkpoint showed dead liquidity", g == 0.0, "got %.3f" % g)
    g = policy_value({"type": "hold", "hours": 168}, 1.0, None, cps_dead, cfg)
    check("hold books -100% when the checkpoint is dead", g == 0.0)
    g = policy_value({"type": "hold", "hours": 24}, 1.0, None, cps_dead, cfg)
    check("hold returns None when its checkpoint is missing", g is None)
    trail = [(900, 1.0, 3.0, 1.0, 3.0, 100.0), (1800, 3.0, 3.0, 1.4, 1.4, 100.0)]
    g = policy_value({"type": "trailing_stop", "drawdown": 0.5}, 1.0, trail, cps, cfg)
    check("trailing stop exits on the close that breaks it", abs(g - 1.4) < 1e-9, "got %.3f" % g)

    print("-- universe gate and size filter --")
    st = {"price": 1e-5, "mcap": 30000, "fdv": 30000, "liq": 12000, "vol_h1": 2000,
          "sellers_h1": 10}
    check("gate admits a tradeable pool", universe_gate(cfg, st)[0])
    check("gate rejects a corpse", universe_gate(cfg, dict(st, liq=300))[1].startswith("liq<"))
    check("gate rejects a pool nobody can sell (honeypot proxy)",
          universe_gate(cfg, dict(st, sellers_h1=0))[1].startswith("sellers<"))
    check("gate treats a missing seller count as unknown, not zero",
          universe_gate(cfg, dict(st, sellers_h1=None))[1] == "sellers_unknown")
    check("gate rejects spoofed liquidity ($98.7M on a small pool)",
          universe_gate(cfg, dict(st, liq=98.7e6))[1] == "liquidity_spoofed")
    check("size filter passes a qualifying pool", market_fails(cfg, st) == [])
    check("size filter rejects a small pool", market_fails(cfg, dict(st, mcap=5000)) == ["mcap"])

    print("-- simulated 10 days: honeypots and spoofed pools mixed in, 35% of calls throttled --")
    tmp = tempfile.mkdtemp(prefix="ethfilter_sim_")
    try:
        t0 = 1_780_000_000
        world = FakeWorld(7, t0)
        for step in range(96 * 10):
            world.now = t0 + step * 900
            if step < 96 * 1.5:
                world.spawn()
            api = Api(cfg, getter=world.get, sleeper=lambda _x: None, clock=lambda: 0.0)
            run_cycle(cfg, api, tmp, world.now)
        tokens, runs = load_state(tmp)

        bad = okcps = 0
        for tk in tokens.values():
            p = world.pools[tk["pool"]]
            for ev in tk["cps"].values():
                if ev["status"] == "ok":
                    okcps += 1
                    if abs(ev["liq"] - world.liq(p, ev["t"])) > 1e-6:
                        bad += 1
        check("every recorded checkpoint matches the true liquidity", bad == 0 and okcps > 0,
              "%d ok, %d wrong" % (okcps, bad))
        fake = sum(1 for tk in tokens.values() for ev in tk["cps"].values()
                   if ev["status"] == "ok" and ev["liq"] < cfg["dead_liquidity_usd"]
                   and world.liq(world.pools[tk["pool"]], ev["t"]) >= cfg["dead_liquidity_usd"])
        check("no death is ever booked from a failed read", fake == 0, "%d fake deaths" % fake)

        hp = [tk for tk in tokens.values() if world.pools[tk["pool"]]["honeypot"]]
        leak = sum(1 for tk in hp if tk["status"] in FINAL_ARMS)
        check("no honeypot ever enters a scored arm", len(hp) > 5 and leak == 0,
              "%d honeypots seen, %d leaked" % (len(hp), leak))
        grow = [world.price(world.pools[tk["pool"]], world.pools[tk["pool"]]["created"] + 7 * 86400)
                / world.price(world.pools[tk["pool"]], world.pools[tk["pool"]]["created"] + 3600)
                for tk in hp]
        print("    (without the seller guard those honeypots would have scored a median %.1fx)"
              % median(grow))
        fp = sum(1 for tk in tokens.values() if tk["reasons"] == "liquidity_spoofed"
                 and not world.pools[tk["pool"]]["spoofed"])
        check("spoof guard never rejects a genuine pool", fp == 0, "%d false positives" % fp)
        sp = [tk for tk in tokens.values() if world.pools[tk["pool"]]["spoofed"]]
        leak = sum(1 for tk in sp if tk["status"] in FINAL_ARMS)
        check("no spoofed-liquidity pool ever enters a scored arm", len(sp) > 3 and leak == 0,
              "%d spoofed seen, %d leaked" % (len(sp), leak))

        final = [tk for tk in tokens.values() if tk["status"] in FINAL_ARMS]
        done = sum(1 for tk in final if (tk["ohlcv"] or {}).get("status") == "ok")
        check("pipeline keeps up despite throttling (7-day paths collected)",
              final and done >= 0.85 * len(final), "%d/%d" % (done, len(final)))
        npass = sum(1 for tk in final if tk["status"] == "pass")
        check("both arms populated in simulation", npass >= 5 and len(final) - npass >= 5,
              "%d pass, %d reject" % (npass, len(final) - npass))

        cfiles = glob.glob(os.path.join(tmp, "candles", "*.gz"))
        per = sum(os.path.getsize(f) for f in cfiles) / max(1, len(cfiles))
        ev = sum(os.path.getsize(f) for f in glob.glob(os.path.join(tmp, "events", "*")))
        check("candle files stay small (git-friendly)", per < 12000,
              "%.1f KB per tracked token, %.0f KB events total" % (per / 1024, ev / 1024))
        tk0 = next(t for t in tokens.values() if (t["ohlcv"] or {}).get("status") == "ok")
        back = read_candles(tmp, tk0["pool_id"])
        check("stored candles read back cleanly", back is not None and len(back) == tk0["ohlcv"]["n"])
        print("    (sim: %d pools, %d scored, %d runs, %d throttled calls)"
              % (len(tokens), len(final), len(runs), sum(r["stats"]["gt_429"] for r in runs)))

        print("-- scorers run end to end on simulated data --")
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_status(cfg, None, data_dir=tmp, now=world.now)
            cmd_score(cfg, None, data_dir=tmp)
            small = dict(cfg, min_paths_for_ladder=10, bootstraps=500)
            cmd_ladder(small, argparse.Namespace(arm="all"), data_dir=tmp)
        text = buf.getvalue()
        check("status, score and ladder all run without error",
              "Q1" in text and "Q2" in text and "paired against" in text)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nselftest: %s" % ("ALL PASS" if not fails else "FAILED: " + ", ".join(fails)))
    return 0 if not fails else 1


# ============================================================================

def main():
    ap = argparse.ArgumentParser(description="ethfilter v3")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run")
    sub.add_parser("status")
    sub.add_parser("score")
    lp = sub.add_parser("ladder")
    lp.add_argument("--arm", default="all", choices=["all", "pass", "reject"])
    sub.add_parser("selftest")
    args = ap.parse_args()
    cfg = load_config()
    fn = {"run": cmd_run, "status": cmd_status, "score": cmd_score,
          "ladder": cmd_ladder, "selftest": cmd_selftest}[args.cmd]
    rc = fn(cfg, args)
    sys.exit(rc if isinstance(rc, int) else 0)


if __name__ == "__main__":
    main()
