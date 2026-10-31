"""Falcon stage 2: tight flags only at the top of a 4H structure, target = next 4H structure low (>= 3R away),
management: no quick break even at the top of a structure. Rules from strategy/falcon.md.
Protocol (written before running): mode 'dev' = first year only, mode 'holdout' = second year, run once after freeze."""
import sys, json
import numpy as np, pandas as pd
from falcon_engine import P, prep, pipsize, find_setups, summarize, fetch

P2 = dict(piv_n=3, look=150, min_gap=6, tol_mult=0.3, area_below=1.5, area_above=0.5, min_r=3.0, be_at_r=1.5,
          spread=1.0, order_life=24, hold_max=240, stop_off=3)

def to4h(df):
    return df.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()

def pivots(arr, n, kind):
    """Swing points; on a flat plateau only the first point counts (no duplicates)."""
    out = []
    for i in range(n, len(arr) - n):
        L, R = arr[i - n:i], arr[i + 1:i + n + 1]
        if kind == "high" and arr[i] > L.max() and arr[i] >= R.max(): out.append(i)
        if kind == "low" and arr[i] < L.min() and arr[i] <= R.min(): out.append(i)
    return out

def htf_context(h4, t, flag_high, entry, risk, p=P2):
    """Using only 4H candles completed before t. Returns (at_top, target_price) or None."""
    m = h4.index.searchsorted(t - pd.Timedelta(hours=4), side="right")
    lo = max(0, m - p["look"]); H = h4.iloc[lo:m]
    if len(H) < 40: return None
    hi, lw = H["high"].values, H["low"].values
    med = np.median(hi - lw); tol = p["tol_mult"] * med
    ph = [i for i in pivots(hi, p["piv_n"], "high") if i + p["piv_n"] < len(H)]   # confirmed only
    pl = [i for i in pivots(lw, p["piv_n"], "low") if i + p["piv_n"] < len(H)]
    if len(ph) < 2: return None
    t1, t2 = ph[-2], ph[-1]
    if t2 - t1 < p["min_gap"]: return None
    p1, p2 = hi[t1], hi[t2]
    if p2 < p1 - tol: return None                       # lower high: no top of structure
    slope = max(0.0, (p2 - p1) / (t2 - t1))             # ascending or flat resistance line
    line_now = p2 + slope * (len(H) - t2)
    if not (line_now - p["area_below"] * med <= flag_high <= line_now + p["area_above"] * med): return None   # in the top area
    need = entry - p["min_r"] * risk
    lows = [lw[i] for i in pl if lw[i] <= need]
    if not lows: return None
    return True, max(lows)                               # nearest structure low that is >= 3R away

def simulate2(s, target, o, h, l, c, pip, p=P2):
    entry, stop, risk = s["entry"], s["stop"], s["risk_pips"] * pip
    n = len(c); k = s["t_idx"] + 1; end = min(n, k + p["order_life"]); filled = None
    while k < end:
        if h[k] > s["flag_high"] + p["stop_off"] * pip and l[k] > entry: return None
        if l[k] <= entry: filled = k; break
        k += 1
    if filled is None: return None
    cur = stop; cost = p["spread"] * pip / risk
    if h[filled] >= cur: return dict(i=filled, r=-1 - cost, why="stop_same_candle")
    for k in range(filled + 1, min(n, filled + p["hold_max"])):
        if h[k] >= cur: return dict(i=filled, r=(entry - cur) / risk - cost, why="stop" if cur == stop else "be")
        if l[k] <= target: return dict(i=filled, r=(entry - target) / risk - cost, why="target")
        if cur == stop and c[k] <= entry - p["be_at_r"] * risk: cur = entry
    kk = min(n, filled + p["hold_max"]) - 1
    return dict(i=filled, r=(entry - c[kk]) / risk - cost, why="timeout")

def run2(df, sym, start, p=P2):
    df = prep(df); pip = pipsize(sym); rows = []
    for side in ("sell", "buy"):
        d = df if side == "sell" else pd.DataFrame({"open": -df.open, "high": -df.low, "low": -df.high, "close": -df.close}, index=df.index)
        h4 = to4h(d)
        o, h, l, c = (d[x].values.astype(float) for x in ("open", "high", "low", "close"))
        for s in find_setups(o, h, l, c, pip, P):
            t = d.index[s["t_idx"]]
            if t < start: continue
            ctx = htf_context(h4, t, s["flag_high"], s["entry"], s["risk_pips"] * pip, p)
            if not ctx: continue
            r = simulate2(s, ctx[1], o, h, l, c, pip, p)
            if r: rows.append(dict(symbol=sym, side=side, time=d.index[r["i"]], r=r["r"], why=r["why"], risk_pips=s["risk_pips"]))
    return pd.DataFrame(rows)

if __name__ == "__main__":
    mode = sys.argv[1]; syms = sys.argv[2].split(",")
    allt = []
    for s in syms:
        try:
            df = prep(fetch(s)); mid = df.index[0] + (df.index[-1] - df.index[0]) / 2
            warm = mid - pd.Timedelta(days=30)
            if mode == "dev": d, start = df[df.index < mid], df.index[0]
            else: d, start = df[df.index >= warm], mid
            allt.append(run2(d, s, start))
        except Exception as e: print("fail", s, e)
    t = pd.concat(allt) if allt else pd.DataFrame()
    out = {"mode": mode, "all": summarize(t)}
    if not t.empty:
        out["by_symbol"] = {k: summarize(g) for k, g in t.groupby("symbol")}
        out["by_exit"] = t.why.value_counts().to_dict()
    print(json.dumps(out, indent=1, default=str))
