"""Falcon v12: SAME rules as v10/v11 (nothing weakened), only the timeframe stack changes: BIAS and STRUCTURE from 1H (impulse/structure bias, channel with 2 touches per line,
real height), ENTRY on the 5m chart (impulse from the touch, structure break, retrace-bounded flag, stop above the flag, target = start of the correction, >=3R room).
The bar-count rules are counted on the 1H structure bars and scaled x3 on 5m (same as v11). Deriv synthetics only. Indicator confirmation (RSI2 overbought, EMA200 trend) still reported.
Bug fix vs v10: if the stop-order is cancelled because the flag kept extending, the next longer flag window is tried instead of discarding the setup (v9-v11 counts were understated by this)."""
import sys, json, os, time, inspect, re
import numpy as np, pandas as pd
import falcon_engine as fe
import falcon_v8 as v8
import falcon_v9 as v9
import falcon_v10 as v10
import falcon_v11 as v11

def patch(fn, **rep):
    src = inspect.getsource(fn)
    for a, b in rep.items(): src = src.replace(a.replace("__", " ").replace("Q", '"'), b)
    return src

TFS, TFB = "1h", "1h"
ns = v10.__dict__; ns["TFS"] = TFS; ns["TFB"] = TFB
chan_src = inspect.getsource(v10.chan).replace('resample("4h")', "resample(TFS)").replace("pd.Timedelta(hours=4)", "pd.Timedelta(TFS)")
bias_src = inspect.getsource(v10.bias_fn).replace('resample("1D")', "resample(TFB)").replace("pd.Timedelta(days=1)", "pd.Timedelta(TFB)")
chart_src = (inspect.getsource(v10.chart).replace('resample("1D")', "resample(TFB)").replace('resample("4h")', "resample(TFS)").replace('t.floor("D")', "t.floor(TFB)").replace('t.floor("4h")', "t.floor(TFS)")
             .replace("days=45", "days=6").replace("days=16", "days=3").replace("days=3))]", "days=1))]").replace('f"15m ', 'f"5m ').replace("DAILY", "1H BIAS").replace("4H  channel", "1H  channel"))
chart_src = chart_src.replace("days=3))]; v9.candles(ax[0]", "days=1))]; v9.candles(ax[0]")
run_src = re.sub(r'if row\["ok"\] and "fill" in row: rows\.append\(row\)\s*\n\s*used = j; break', 'if row["ok"] and "fill" in row:\n                    rows.append(row); used = j; break', inspect.getsource(v10.run))
assert run_src != inspect.getsource(v10.run), "run patch failed"
import collections
_L = run_src.split("\n"); _j = [k for k, x in enumerate(_L) if "for j in range(W" in x][0]; _o = []
for k, x in enumerate(_L):
    if k > _j and ("continue" in x or "break" in x):
        key = re.sub(r"[^A-Za-z0-9_<>=\[\]\"\.\(\)\* +-]", "", x.split(":")[0].strip())[:80].replace('"', "'")
        x = x.replace("continue", f'CNT["{key}"] += 1; continue').replace("break", f'CNT["{key}"] += 1; break')
    _o.append(x)
ns["CNT"] = collections.Counter()
exec(chan_src, ns); exec(bias_src, ns); exec(chart_src, ns); exec("\n".join(_o), ns)   # FIX: a flag order cancelled before filling no longer kills the setup; the next, longer flag window is tried

def funnel(df):
    p = dict(v10.P); res = {}
    for side, sg in (("sell", 1), ("buy", -1)):
        mm, at4 = v10.chan(df, sg); md, atd = v10.bias_fn(df, sg, p); h = df.high.values if sg > 0 else -df.low.values; nb = nc = nz = 0
        for i in range(len(df)):
            b = atd(md[i]); s = at4(mm[i]); nb += b is not None; nc += s is not None
            if s and b:
                up = s["U"][1] + s["U"][2] * (i - s["U"][0])
                if up - s["tol"] <= h[i] <= up + p["over"] * s["atr"]: nz += 1
        res[side] = dict(bars=len(df), bias_bars=nb, channel_bars=nc, zone_bars=nz)
    return res

if __name__ == "__main__":
    src, syms = sys.argv[1], sys.argv[2].split(","); cdir = sys.argv[3] if len(sys.argv) > 3 else None; maxc = int(sys.argv[4]) if len(sys.argv) > 4 else 6
    out = {}; pool = {}; alltr = []
    for sym in syms:
        df = None
        for att in range(4):
            try: df = v11.load5(src, sym); break
            except Exception as e: err = str(e)[:120]; time.sleep(20 * (att + 1))
        if df is None or len(df) < 5000: out[sym] = {"error": err if df is None else f"too little data {len(df)}"}; continue
        pip = float(np.median((df.high - df.low).values)) / 12.0; out[sym] = {"candles": len(df), "costs": {}, "funnel": funnel(df)}; ns["CNT"].clear()
        for sp in (1.0, 2.0):
            t = v11.add_filters(df, v10.run(df, sym, sp, pip, False)); pool.setdefault(str(sp), []).append(t)
            if sp == 1.0:
                out[sym]["costs"]["1.0"] = v11.table(t); out[sym]["rejects"] = dict(ns["CNT"])
                if len(t): alltr.append(t.drop(columns=["lpU", "lpL", "dq"]))
                if cdir and len(t):
                    os.makedirs(cdir, exist_ok=True)
                    for i, (_, row) in enumerate(t.sort_values("time").head(maxc).iterrows()): v10.chart(df, row, f"{cdir}/{sym}_{i+1}_{row.side}.png")
        time.sleep(3)
    out["POOLED"] = {sp: v11.table(pd.concat(l)) for sp, l in pool.items() if any(len(x) for x in l)}
    if cdir and alltr: pd.concat(alltr).to_csv(cdir + "_trades.csv", index=False)
    print(json.dumps(out, indent=1, default=str))
