"""Falcon v9: top-down, as the user trades it (strategy/falcon-top-down-process.md). Entry timeframe 15m.
1) DAILY bias: latest daily impulse (not yet broken by the correction) OR overall daily trend direction. No bias = no trade.
2) 4H structure: correction channel against the bias (for shorts an ascending upper line from the last two 4H pivots, >=2 touches, real channel height).
3) ZONE: price touches/overshoots that upper line. 4) 15m: impulse away from the zone, then a correction flag (>=6 candles, relative tightness).
Entry stop-order beyond the flag, stop beyond the flag, target = start of the correction (4H structure low), needs >=3R room. Re-entries on later flags
in the same move while the structure top holds. Parameters frozen, nothing tuned. Buys = mirrored sells."""
import sys, json, os, time
import numpy as np, pandas as pd
import falcon_engine as fe
import falcon_v7_deriv as v7
import falcon_v8 as v8

P = dict(v7.P)
P.update(imp_mult=3.0, imp_max=24, bear_frac=0.55, min_flag=6, max_flag=24, flat_ratio=0.65, tight_candle=1.5, drift_max=0.4, entry_off=2, stop_off=3,
         min_stop=15, max_stop=120, order_life=24, target_r=3.0, hold_max=960, range_win=240, zone_hi=1.5, d_imp=2.5, d_trend=1.0, move_max=400, min_touch=2, first_gap=48)

def daily_bias(df, sign, p):
    g = df.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    gh, gl, gc = (g.high.values, g.low.values, g.close.values) if sign > 0 else (-g.low.values, -g.high.values, -g.close.values)
    md = np.searchsorted((g.index + pd.Timedelta(days=1)).values, df.index.values, side="right")
    k = 2; piv = [q for q in range(k, len(g) - k) if gh[q] == gh[q - k:q + k + 1].max()]; cache = {}
    def at(d):
        if d in cache: return cache[d]
        res = None
        if d >= 30:
            atr = float(np.median(gh[d - 30:d] - gl[d - 30:d])); ps = [q for q in piv if d - 60 <= q <= d - 1 - k]
            if ps:
                q = ps[-1]; H = gh[q]; lo = float(gl[q:d].min())
                if H - lo >= p["d_imp"] * atr and gc[d - 1] < H: res = dict(src="impulse", q=q, H=H, lo=lo)
            if res is None and gc[d - 1] - gc[d - 21] <= -p["d_trend"] * atr: res = dict(src="trend", q=None, H=None, lo=None)
        cache[d] = res; return res
    return md, at

def run(df, sym, spread, pip, gap):
    p = dict(P); p["spread"] = spread; rows = []
    for side, sg in (("sell", 1), ("buy", -1)):
        a = [df[x].values.astype(float) for x in ("open", "high", "low", "close")]
        o, h, l, c = (a[0], a[1], a[2], a[3]) if sg > 0 else (-a[0], -a[2], -a[1], -a[3])
        mm, at4 = v8.structure(df, sg); md, atd = daily_bias(df, sg, p); n = len(c); lz = np.full(n, -1); zi = {}; last = -1
        for i in range(n):
            b = atd(md[i]); s = at4(mm[i])
            if b and s and s["asc"] and s["touches"] >= p["min_touch"]:
                line = s["a"] + s["slope"] * (i - s["pos"])
                if line - s["tol"] <= h[i] <= line + p["zone_hi"] * s["atr"] and s["low"] < line - 1.5 * s["atr"]:
                    last = i; zi[i] = (s, b)
            lz[i] = last
        for x in v7.find(o, h, l, c, pip, p):
            tz = lz[x["s"]]
            if tz < 0 or x["s"] - tz > p["move_max"] or atd(md[x["s"]]) is None: continue
            s, b = zi[tz]; xs = np.arange(tz, x["j"] + 1)
            if not (h[tz:x["j"] + 1] <= s["a"] + s["slope"] * (xs - s["pos"]) + p["zone_hi"] * s["atr"]).all(): continue
            risk = x["risk_pips"] * pip
            if x["entry"] - s["low"] < p["target_r"] * risk: continue
            row = dict(symbol=sym, side=side, s=x["s"], j=x["j"], nf=x["nf"], tz=tz, touches=s["touches"], bias=b["src"], first=bool(x["s"] - tz <= p["first_gap"]),
                       nest=bool(x["nest"]), entry=x["entry"], stop=x["stop"], risk_pips=x["risk_pips"], lp=(s["pos"], s["a"], s["slope"]), slow=s["low"],
                       dq=(None if b["q"] is None else (b["q"], b["H"], b["lo"])), ok=False)
            for mn, (tm, ber) in MODES.items():
                tp = s["low"] if tm == "struct" else x["entry"] - p["target_r"] * risk
                r = v8.sim2(x, o, h, l, c, pip, p, tp, ber, gap)
                if r is None: row["r_" + mn] = np.nan; continue
                row["r_" + mn] = r["r"]; row["ok"] = True
                if mn == "struct_A": row.update(time=df.index[r["fill"]], fill=r["fill"], exit=r["exit"], target=tp, why=r["why"])
            if row["ok"] and "fill" in row: rows.append(row)
    return pd.DataFrame(rows)

MODES = {"struct_A": ("struct", 1.0), "struct_B": ("struct", 2.0), "3R_A": ("3R", 1.0)}
TIERS = {"all": lambda t: t.touches >= 0, "touch3": lambda t: t.touches >= 3, "bias_impulse": lambda t: t.bias == "impulse", "bias_trend": lambda t: t.bias == "trend",
         "first_entry": lambda t: t["first"], "re_entry": lambda t: ~t["first"], "nested_flag": lambda t: t.nest, "impulse_first_touch3": lambda t: (t.bias == "impulse") & t["first"] & (t.touches >= 3)}

def table(t):
    return {k: {m: v8.summ(t[f(t)], "r_" + m) for m in MODES} for k, f in TIERS.items()} if len(t) else {}

def candles(ax, d):
    for xi, (_, r) in enumerate(d.iterrows()):
        col = "#2e9e5b" if r.close >= r.open else "#d04a4a"
        ax.vlines(xi, r.low, r.high, color=col, lw=1); ax.bar(xi, max(abs(r.close - r.open), 1e-9), bottom=min(r.open, r.close), width=0.7, color=col)

def chart(df, row, path):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    sg = 1 if row.side == "sell" else -1; t = df.index[row.fill]
    gD = df.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    g4 = df.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    fig, ax = plt.subplots(3, 1, figsize=(9, 10), dpi=70)
    d1 = gD[(gD.index >= t - pd.Timedelta(days=45)) & (gD.index <= t + pd.Timedelta(days=3))]; candles(ax[0], d1)
    if row.dq is not None:
        q, H, lo = row.dq; H, lo = sg * H, sg * lo
        ax[0].axhline(H, color="orange", ls="--", lw=1); ax[0].axhline(lo, color="orange", ls=":", lw=1)
    ax[0].axvline(d1.index.searchsorted(t.floor("D")), color="black", lw=1)
    ax[0].set_title(f"DAILY  bias {'SHORT' if row.side=='sell' else 'LONG'} from {row.bias}  (orange = impulse start / low)", fontsize=9)
    d2 = g4[(g4.index >= t - pd.Timedelta(days=14)) & (g4.index <= t + pd.Timedelta(days=2))]; candles(ax[1], d2)
    pos4 = np.searchsorted(df.index.values, d2.index.values, side="left"); pos, av, sl = row.lp
    ax[1].plot(np.arange(len(d2)), sg * (av + sl * (pos4 - pos)), color="gray", lw=1.5); ax[1].axhline(sg * row.slow, color="green", ls="--", lw=1)
    ax[1].axvline(d2.index.searchsorted(t.floor("4h")), color="black", lw=1)
    ax[1].set_title(f"4H  structure upper line, touches={row.touches}  (green dashed = start of correction = target)", fontsize=9)
    a, b = max(0, row.s - 40), min(len(df), row.exit + 40); d3 = df.iloc[a:b]; candles(ax[2], d3); sgp = sg
    ax[2].axvspan(row.s - a, row.j - a, color="#e8c547", alpha=0.18); ax[2].axvspan(row.j + 1 - a, row.j + row.nf - a, color="#5b9bd5", alpha=0.2)
    ax[2].axhline(sgp * row.entry, color="black", lw=1); ax[2].axhline(sgp * row.stop, color="red", ls="--", lw=1); ax[2].axhline(sgp * row.target, color="green", ls="--", lw=1)
    ax[2].scatter([row.fill - a], [sgp * row.entry], marker=">", s=70, color="black", zorder=5); ax[2].scatter([row.exit - a], [df.close.iloc[row.exit]], marker="x", s=70, color="purple", zorder=5)
    ax[2].set_title(f"15m  {row.symbol} {row.side.upper()} R={row.r_struct_A:+.2f} ({row.why})  {'first' if row['first'] else 're-entry'}{' nested' if row.nest else ''}  yellow=impulse blue=flag", fontsize=9)
    for x in ax: x.grid(alpha=0.2)
    fig.tight_layout(); fig.savefig(path); plt.close(fig)

def fetch15(sym, days=365, gran=900):
    from falcon_deriv import connect
    ws = connect(); end = "latest"; rows = {}; floor = time.time() - days * 86400
    for _ in range(30):
        ws.send(json.dumps({"ticks_history": sym, "adjust_start_time": 1, "count": 5000, "end": end, "granularity": gran, "style": "candles"}))
        r = json.loads(ws.recv())
        if "error" in r: raise RuntimeError(r["error"].get("message", "error"))
        c = r.get("candles", [])
        if not c: break
        for x in c: rows[x["epoch"]] = (x["open"], x["high"], x["low"], x["close"])
        first = min(x["epoch"] for x in c)
        if first <= floor: break
        end = first - 1; time.sleep(1)
    ws.close(); d = pd.DataFrame.from_dict(rows, orient="index", columns=["open", "high", "low", "close"]).sort_index()
    d.index = pd.to_datetime(d.index, unit="s", utc=True); return d

def load(src, sym):
    if src == "deriv": return fe.prep(fetch15(sym))
    import yfinance as yf
    d = yf.download(sym + ("=X" if src == "forex" else ""), interval="15m", period="60d", auto_adjust=False, progress=False)
    d.columns = [x[0] if isinstance(x, tuple) else x for x in d.columns]; return fe.prep(d)

if __name__ == "__main__":
    src, syms = sys.argv[1], sys.argv[2].split(","); cdir = sys.argv[3] if len(sys.argv) > 3 else None; maxc = int(sys.argv[4]) if len(sys.argv) > 4 else 6
    out = {}; pool = {}
    for sym in syms:
        df = None
        for attempt in range(4):
            try: df = load(src, sym); break
            except Exception as e: err = str(e)[:120]; time.sleep(20 * (attempt + 1))
        if df is None or len(df) < 3000: out[sym] = {"error": err if df is None else f"too little data {len(df)}"}; continue
        pip = fe.pipsize(sym) if src == "forex" else float(np.median((df.high - df.low).values)) / 12.0
        out[sym] = {"candles": len(df), "costs": {}}
        for sp in (0.0, 1.0, 2.0):
            t = run(df, sym, sp, pip, src != "deriv"); pool.setdefault(str(sp), []).append(t)
            if sp == 1.0:
                out[sym]["costs"]["1.0"] = table(t)
                if cdir and len(t):
                    os.makedirs(cdir, exist_ok=True); sel = t.sort_values(["first", "time"], ascending=[False, True]).head(maxc)
                    for i, (_, row) in enumerate(sel.iterrows()): chart(df, row, f"{cdir}/{sym}_{i+1}_{row.side}.png")
        time.sleep(3)
    out["POOLED"] = {sp: table(pd.concat(l)) for sp, l in pool.items() if any(len(x) for x in l)}
    print(json.dumps(out, indent=1, default=str))
