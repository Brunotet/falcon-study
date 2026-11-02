"""Falcon v10: rebuilt after auditing v9 trades against the course and the user's USDJPY examples (strategy/falcon-top-down-process.md).
v9 errors fixed: (1) 4H 'structure' was one loose line through far-apart pivots; now a real CHANNEL (upper + lower line, >=2 touches each, real height, recent pivots).
(2) 'zone' touch could be 400 bars old / line already broken; now the impulse must START at the touch (<=8 bars) for first entries, structure top must hold.
(3) the 15m 'impulse' was noise (3x median range); now it must be large vs the channel AND break the recent 15m swing low (structure break).
(4) flag must retrace 20-70% of the impulse; (5) 'trend' bias contradicted the daily chart; now lower-highs/lower-lows structure (or an unbroken daily impulse).
Target = start of the correction (lowest low of the 4H correction), needs >=3R room. Buys mirror sells. Nothing tuned."""
import sys, json, os, time
import numpy as np, pandas as pd
import falcon_engine as fe
import falcon_v8 as v8
import falcon_v9 as v9

P = dict(v8.P)
P.update(k=2, tol=0.35, over=0.75, win4=60, min_h=2.0, imp_mult=3.0, imp_chan=0.12, imp_max=24, bear_frac=0.55, min_flag=6, max_flag=24, ret_lo=0.20, ret_hi=0.70,
         bos_first=48, bos_re=24, first_gap=8, move_max=200, entry_off=2, stop_off=3, min_stop=15, max_stop=120, order_life=24, target_r=3.0, hold_max=960,
         d_imp=2.5, range_win=240)

def bias_fn(df, sign, p):
    g = df.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    gh, gl, gc = (g.high.values, g.low.values, g.close.values) if sign > 0 else (-g.low.values, -g.high.values, -g.close.values)
    md = np.searchsorted((g.index + pd.Timedelta(days=1)).values, df.index.values, side="right")
    k = 2; pH = [q for q in range(k, len(g) - k) if gh[q] == gh[q - k:q + k + 1].max()]; pL = [q for q in range(k, len(g) - k) if gl[q] == gl[q - k:q + k + 1].min()]; cache = {}
    def at(d):
        if d in cache: return cache[d]
        res = None
        if d >= 30:
            atr = float(np.median(gh[d - 30:d] - gl[d - 30:d])); ps = [q for q in pH if d - 60 <= q <= d - 1 - k]
            if ps:
                q = ps[-1]; H = gh[q]; lo = float(gl[q:d].min())
                if H - lo >= p["d_imp"] * atr and gc[d - 1] < H: res = dict(src="impulse", q=q, H=H, lo=lo)
            if res is None:
                a = [q for q in pH if q <= d - 1 - k][-2:]; b = [q for q in pL if q <= d - 1 - k][-2:]
                if len(a) == 2 and len(b) == 2 and gh[a[1]] < gh[a[0]] and gl[b[1]] < gl[b[0]] and gc[d - 1] < gh[a[1]]: res = dict(src="structure", q=None, H=None, lo=None)
        cache[d] = res; return res
    return md, at

def chan(df, sign):
    g = df.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    gh, gl = (g.high.values, g.low.values) if sign > 0 else (-g.low.values, -g.high.values); rg = g.high.values - g.low.values
    mm = np.searchsorted((g.index + pd.Timedelta(hours=4)).values, df.index.values, side="right"); pos = np.searchsorted(df.index.values, g.index.values, side="left")
    k = P["k"]; pH = [p for p in range(k, len(g) - k) if gh[p] == gh[p - k:p + k + 1].max()]; pL = [p for p in range(k, len(g) - k) if gl[p] == gl[p - k:p + k + 1].min()]; cache = {}
    def at(m):
        if m in cache: return cache[m]
        res = None; a = [p for p in pH if m - P["win4"] <= p <= m - k - 1]; b = [p for p in pL if m - P["win4"] <= p <= m - k - 1]
        if len(a) >= 2 and len(b) >= 2:
            p1, p2 = a[-2], a[-1]; q1, q2 = b[-2], b[-1]
            if 3 <= p2 - p1 <= 30 and 3 <= q2 - q1 <= 30 and pos[p2] > pos[p1] and pos[q2] > pos[q1]:
                su = (gh[p2] - gh[p1]) / (pos[p2] - pos[p1]); sl = (gl[q2] - gl[q1]) / (pos[q2] - pos[q1]); atr = float(np.median(rg[max(0, m - 50):m])); tol = P["tol"] * atr
                if su > 0 and sl > 0:
                    tu = sum(1 for p in a[-4:] if abs(gh[p] - (gh[p2] + su * (pos[p] - pos[p2]))) <= tol); tl = sum(1 for q in b[-4:] if abs(gl[q] - (gl[q2] + sl * (pos[q] - pos[q2]))) <= tol)
                    height = (gh[p2] + su * (pos[q2] - pos[p2])) - gl[q2]
                    if tu >= 2 and tl >= 2 and height >= P["min_h"] * atr:
                        res = dict(U=(pos[p2], gh[p2], su), L=(pos[q2], gl[q2], sl), atr=atr, tol=tol, tu=tu, tl=tl, height=height, low=float(gl[min(p1, q1):m].min()))
        cache[m] = res; return res
    return mm, at

def run(df, sym, spread, pip, gap):
    p = dict(P); p["spread"] = spread; rows = []; W = p["range_win"]
    for side, sg in (("sell", 1), ("buy", -1)):
        a = [df[x].values.astype(float) for x in ("open", "high", "low", "close")]
        o, h, l, c = (a[0], a[1], a[2], a[3]) if sg > 0 else (-a[0], -a[2], -a[1], -a[3])
        mm, at4 = chan(df, sg); md, atd = bias_fn(df, sg, p); n = len(c); lz = np.full(n, -1); zi = {}; last = -1
        rng = pd.Series(h - l).rolling(200, min_periods=50).median().values
        for i in range(n):
            s = at4(mm[i])
            if s and atd(md[i]):
                up = s["U"][1] + s["U"][2] * (i - s["U"][0])
                if up - s["tol"] <= h[i] <= up + p["over"] * s["atr"]: last = i; zi[i] = s
            lz[i] = last
        used = -1
        for j in range(W, n - p["max_flag"] - 2):
            L = p["imp_max"]; s0 = j - L + int(np.argmax(h[j - L:j + 1]))
            if s0 >= j or s0 <= used or l[j] > l[j - L:j + 1].min(): continue
            tz = lz[s0]
            if tz < 0 or s0 - tz > p["move_max"]: continue
            S = zi[tz]; b = atd(md[s0])
            if b is None: continue
            first = (s0 - tz) <= p["first_gap"]; size = h[s0] - l[j]
            if np.isnan(rng[s0]) or size < max(p["imp_mult"] * rng[s0], p["imp_chan"] * S["height"]): continue
            if np.mean(c[s0:j + 1] < o[s0:j + 1]) < p["bear_frac"]: continue
            lb = p["bos_first"] if first else p["bos_re"]; bos = l[max(0, s0 - lb):max(1, s0 - 2)].min()
            if not l[j] < bos: continue
            xs = np.arange(tz, j + 1)
            if not (h[tz:j + 1] <= S["U"][1] + S["U"][2] * (xs - S["U"][0]) + p["over"] * S["atr"]).all(): continue
            for nf in range(p["min_flag"], p["max_flag"] + 1):
                w = slice(j + 1, j + nf + 1); fh = h[w].max(); fl = min(l[w].min(), l[j])
                if fh >= h[s0] or fl < l[j] - 0.1 * size: break
                ret = (fh - l[j]) / size
                if not (p["ret_lo"] <= ret <= p["ret_hi"]): continue
                entry = fl - p["entry_off"] * pip; stop = fh + p["stop_off"] * pip; risk = (stop - entry) / pip
                if risk < p["min_stop"]: stop = entry + p["min_stop"] * pip; risk = p["min_stop"]
                if risk > p["max_stop"]: break
                if entry - S["low"] < p["target_r"] * risk * pip: break
                st = dict(t_idx=j + nf, entry=entry, stop=stop, risk_pips=risk, flag_high=fh)
                row = dict(symbol=sym, side=side, s=s0, j=j, nf=nf, tz=tz, tu=S["tu"], tl=S["tl"], bias=b["src"], first=bool(first), bos=bos, entry=entry, stop=stop, risk_pips=risk,
                           lpU=S["U"], lpL=S["L"], slow=S["low"], dq=(None if b["q"] is None else (b["q"], b["H"], b["lo"])), nest=bool(np.polyfit(np.arange(nf), c[j + 1:j + nf + 1], 1)[0] >= 0), ok=False)
                for mn, (tm, ber) in v9.MODES.items():
                    tp = S["low"] if tm == "struct" else entry - p["target_r"] * risk * pip
                    r = v8.sim2(st, o, h, l, c, pip, p, tp, ber, gap)
                    if r is None: row["r_" + mn] = np.nan; continue
                    row["r_" + mn] = r["r"]; row["ok"] = True
                    if mn == "struct_A": row.update(time=df.index[r["fill"]], fill=r["fill"], exit=r["exit"], target=tp, why=r["why"])
                if row["ok"] and "fill" in row: rows.append(row)
                used = j; break
    return pd.DataFrame(rows)

TIERS = {"all": lambda t: t.tu >= 0, "touch3_top": lambda t: t.tu >= 3, "first_entry": lambda t: t["first"], "re_entry": lambda t: ~t["first"], "bias_impulse": lambda t: t.bias == "impulse",
         "bias_structure": lambda t: t.bias == "structure", "nested_flag": lambda t: t.nest, "first_impulse_bias": lambda t: t["first"] & (t.bias == "impulse")}

def table(t):
    return {k: {m: v8.summ(t[f(t)], "r_" + m) for m in v9.MODES} for k, f in TIERS.items()} if len(t) else {}

def chart(df, row, path):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    sg = 1 if row.side == "sell" else -1; t = df.index[row.fill]
    gD = df.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna(); g4 = df.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    fig, ax = plt.subplots(3, 1, figsize=(9, 10), dpi=70)
    d1 = gD[(gD.index >= t - pd.Timedelta(days=45)) & (gD.index <= t + pd.Timedelta(days=3))]; v9.candles(ax[0], d1)
    if row.dq is not None: q, H, lo = row.dq; ax[0].axhline(sg * H, color="orange", ls="--", lw=1); ax[0].axhline(sg * lo, color="orange", ls=":", lw=1)
    ax[0].axvline(d1.index.searchsorted(t.floor("D")), color="black", lw=1)
    ax[0].set_title(f"DAILY  bias {'SHORT' if row.side=='sell' else 'LONG'} from {row.bias}", fontsize=9)
    d2 = g4[(g4.index >= t - pd.Timedelta(days=16)) & (g4.index <= t + pd.Timedelta(days=2))]; v9.candles(ax[1], d2); pos4 = np.searchsorted(df.index.values, d2.index.values, side="left"); xs = np.arange(len(d2))
    for lp, cc in ((row.lpU, "gray"), (row.lpL, "silver")): ax[1].plot(xs, sg * (lp[1] + lp[2] * (pos4 - lp[0])), color=cc, lw=1.5)
    ax[1].axhline(sg * row.slow, color="green", ls="--", lw=1); ax[1].axvline(d2.index.searchsorted(t.floor("4h")), color="black", lw=1)
    ax[1].set_title(f"4H  channel, upper touches={row.tu} lower touches={row.tl}  (green dashed = start of correction = target)", fontsize=9)
    a, b = max(0, row.tz - 30), min(len(df), row.exit + 40); d3 = df.iloc[a:b]; v9.candles(ax[2], d3)
    ax[2].axvline(row.tz - a, color="gray", ls=":", lw=1); ax[2].axhline(sg * row.bos, color="orange", ls=":", lw=1)
    ax[2].axvspan(row.s - a, row.j - a, color="#e8c547", alpha=0.18); ax[2].axvspan(row.j + 1 - a, row.j + row.nf - a, color="#5b9bd5", alpha=0.2)
    ax[2].axhline(sg * row.entry, color="black", lw=1); ax[2].axhline(sg * row.stop, color="red", ls="--", lw=1); ax[2].axhline(sg * row.target, color="green", ls="--", lw=1)
    ax[2].scatter([row.fill - a], [sg * row.entry], marker=">", s=70, color="black", zorder=5); ax[2].scatter([row.exit - a], [df.close.iloc[row.exit]], marker="x", s=70, color="purple", zorder=5)
    ax[2].set_title(f"15m {row.symbol} {row.side.upper()} R={row.r_struct_A:+.2f} ({row.why}) {'first' if row['first'] else 're-entry'}  gray dotted=touch  orange dotted=broken swing  yellow=impulse blue=flag", fontsize=8)
    for x in ax: x.grid(alpha=0.2)
    fig.tight_layout(); fig.savefig(path); plt.close(fig)

if __name__ == "__main__":
    src, syms = sys.argv[1], sys.argv[2].split(","); cdir = sys.argv[3] if len(sys.argv) > 3 else None; maxc = int(sys.argv[4]) if len(sys.argv) > 4 else 6
    out = {}; pool = {}; alltr = []
    for sym in syms:
        df = None
        for attempt in range(4):
            try: df = v9.load(src, sym); break
            except Exception as e: err = str(e)[:120]; time.sleep(20 * (attempt + 1))
        if df is None or len(df) < 3000: out[sym] = {"error": err if df is None else f"too little data {len(df)}"}; continue
        pip = fe.pipsize(sym) if src == "forex" else float(np.median((df.high - df.low).values)) / 12.0
        out[sym] = {"candles": len(df), "costs": {}}
        for sp in (0.0, 1.0, 2.0):
            t = run(df, sym, sp, pip, src != "deriv"); pool.setdefault(str(sp), []).append(t)
            if sp == 1.0:
                out[sym]["costs"]["1.0"] = table(t)
                if len(t): alltr.append(t.drop(columns=["lpU", "lpL", "dq"]))
                if cdir and len(t):
                    os.makedirs(cdir, exist_ok=True); sel = t.sort_values(["first", "time"], ascending=[False, True]).head(maxc)
                    for i, (_, row) in enumerate(sel.iterrows()): chart(df, row, f"{cdir}/{sym}_{i+1}_{row.side}.png")
        time.sleep(3)
    out["POOLED"] = {sp: table(pd.concat(l)) for sp, l in pool.items() if any(len(x) for x in l)}
    if cdir and alltr: pd.concat(alltr).to_csv(cdir + "_trades.csv", index=False)
    print(json.dumps(out, indent=1, default=str))
