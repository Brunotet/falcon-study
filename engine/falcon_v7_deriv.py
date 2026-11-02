"""Falcon v7 backtest on Deriv synthetics (1H). Rules: strategy/falcon-rulebook-v7.md. Parameters frozen, nothing tuned.
1 'pip' = median 1H range / 12 (same scale as falcon_deriv.py). Costs swept 0/1/2 pips. Buys = mirrored sells.
Tiers (each one a filter on top of the previous idea): base = relative tight first flag after an impulse;
loc = impulse starts in the top zone of the 240-candle range; broke = prior high broken first; nest = rising outer
structure AND rising flag (ascending in ascending proxy); room = 3R target still inside the structure."""
import sys, json, os, time
import numpy as np, pandas as pd
import falcon_engine as fe

P = dict(fe.P)
P.update(imp_mult=4.0, imp_max=24, bear_frac=0.55, min_flag=6, max_flag=14, flat_ratio=0.40, tight_candle=1.0,
         drift_max=0.2, entry_off=2, stop_off=3, min_stop=15, max_stop=55, order_life=24, target_r=3.0, be_at_r=1.0,
         hold_max=240, range_win=240, top_zone=0.80)

def find(o, h, l, c, pip, p):
    n = len(c); out = []; rng = pd.Series(h - l).rolling(200, min_periods=50).median().values
    cr = h - l; used = -1; W = p["range_win"]
    for j in range(W + 30, n - p["max_flag"] - 1):
        L = p["imp_max"]; s = j - L + int(np.argmax(h[j - L:j + 1]))
        if s >= j or s <= used or l[j] > l[j - L:j + 1].min(): continue
        size = h[s] - l[j]
        if np.isnan(rng[s]) or size < p["imp_mult"] * rng[s]: continue
        sg = slice(s, j + 1)
        if np.mean(c[sg] < o[sg]) < p["bear_frac"]: continue
        mean_c = cr[sg].mean()
        for nf in range(p["min_flag"], p["max_flag"] + 1):
            w = slice(j + 1, j + nf + 1); fh = h[w].max(); fl = min(l[w].min(), l[j])
            if fh >= h[s]: break
            if fl < l[j] - 0.1 * size: break
            if (fh - fl) > p["flat_ratio"] * size: continue
            if cr[w].max() > p["tight_candle"] * mean_c: continue
            if abs(c[j + nf] - c[j + 1]) > p["drift_max"] * size: continue
            entry = fl - p["entry_off"] * pip; stop = fh + p["stop_off"] * pip; risk = (stop - entry) / pip
            if risk < p["min_stop"]: stop = entry + p["min_stop"] * pip; risk = p["min_stop"]
            if risk > p["max_stop"]: break
            lo = l[s - W:j + 1].min(); hi = h[s - W:j + 1].max()
            loc = (h[s] - lo) / max(hi - lo, 1e-9)
            prev_hi = h[max(0, s - 24):s].max(); old = h[s - W:s - 24]
            broke = bool(len(old) and prev_hi >= old.max())
            outer = np.polyfit(np.arange(W + 1), c[s - W:s + 1], 1)[0]
            flagsl = np.polyfit(np.arange(nf), c[j + 1:j + nf + 1], 1)[0]
            nest = bool(outer > 0 and flagsl > 0)
            room = bool((entry - lo) >= p["target_r"] * risk * pip)
            out.append(dict(s=s, j=j, nf=nf, t_idx=j + nf, entry=entry, stop=stop, risk_pips=risk, flag_high=fh,
                            top=bool(loc >= p["top_zone"]), broke=broke, nest=nest, room=room))
            used = j; break
    return out

def sim(st, o, h, l, c, pip, p):
    entry, stop, risk = st["entry"], st["stop"], st["risk_pips"] * pip
    n = len(c); k = st["t_idx"] + 1; end = min(n, k + p["order_life"]); fill = None
    while k < end:
        if h[k] > st["flag_high"] + p["stop_off"] * pip and l[k] > entry: return None
        if l[k] <= entry: fill = k; break
        k += 1
    if fill is None: return None
    cost = p["spread"] * pip / risk
    if h[fill] >= stop: return dict(fill=fill, exit=fill, r=-1 - cost, why="stop_same_candle", target=entry - p["target_r"] * risk)
    cur = stop; target = entry - p["target_r"] * risk; ex = None
    for k in range(fill + 1, min(n, fill + p["hold_max"])):
        if h[k] >= cur: r = (entry - cur) / risk; why = "stop" if cur == stop else "be"; ex = k; break
        if l[k] <= target: r = p["target_r"]; why = "target"; ex = k; break
        if p["be_at_r"] and cur == stop and c[k] <= entry - p["be_at_r"] * risk: cur = entry
    if ex is None:
        ex = min(n, fill + p["hold_max"]) - 1; r = (entry - c[ex]) / risk; why = "timeout"
    return dict(fill=fill, exit=ex, r=r - cost, why=why, target=target)

def run(df, sym, spread):
    p = dict(P); p["spread"] = spread
    pip = float(np.median((df.high - df.low).values)) / 12.0
    rows = []
    for side in ("sell", "buy"):
        a = [df[x].values.astype(float) for x in ("open", "high", "low", "close")]
        o, h, l, c = (a[0], a[1], a[2], a[3]) if side == "sell" else (-a[0], -a[2], -a[1], -a[3])
        for st in find(o, h, l, c, pip, p):
            r = sim(st, o, h, l, c, pip, p)
            if r: rows.append(dict(symbol=sym, side=side, time=df.index[r["fill"]], **{k: st[k] for k in ("s", "j", "nf", "top", "broke", "nest", "room")},
                                   entry=st["entry"], stop=st["stop"], target=r["target"], fill=r["fill"], exit=r["exit"], r=r["r"], why=r["why"], risk_pips=st["risk_pips"]))
    return pd.DataFrame(rows), pip

TIERS = {"base": lambda t: t.top | ~t.top, "top": lambda t: t.top, "top_broke": lambda t: t.top & t.broke,
         "top_nest": lambda t: t.top & t.nest, "top_broke_nest": lambda t: t.top & t.broke & t.nest,
         "top_broke_nest_room": lambda t: t.top & t.broke & t.nest & t.room}

def summ(t):
    return fe.summarize(t) if len(t) else {"trades": 0}

def chart(df, row, pip, path):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    sell = row.side == "sell"; sg = -1 if not sell else 1
    a, b = max(0, row.s - 25), min(len(df), row.exit + 12)
    d = df.iloc[a:b]; x = np.arange(a, b)
    fig, ax = plt.subplots(figsize=(9, 5), dpi=80)
    for xi, (_, r) in zip(x, d.iterrows()):
        up = r.close >= r.open; col = "#2e9e5b" if up else "#d04a4a"
        ax.vlines(xi, r.low, r.high, color=col, lw=1); ax.bar(xi, max(abs(r.close - r.open), 1e-9), bottom=min(r.open, r.close), width=0.7, color=col)
    e, s_, tg = (row.entry, row.stop, row.target) if sell else (-row.entry, -row.stop, -row.target)
    ax.axvspan(row.s, row.j, color="#e8c547", alpha=0.18); ax.axvspan(row.j + 1, row.j + row.nf, color="#5b9bd5", alpha=0.18)
    ax.axhline(e, color="black", lw=1); ax.axhline(s_, color="red", ls="--", lw=1); ax.axhline(tg, color="green", ls="--", lw=1)
    ax.scatter([row.fill], [e], marker=">", s=70, color="black", zorder=5); ax.scatter([row.exit], [e - (e - tg) * (row.r / 3.0) if False else df.close.iloc[row.exit]], marker="x", s=70, color="purple", zorder=5)
    tag = "+".join(k for k in ("top", "broke", "nest", "room") if row[k]) or "base"
    ax.set_title(f"{row.symbol} {row.side.upper()}  R={row.r:+.2f} ({row.why})  [{tag}]  yellow=impulse blue=flag", fontsize=9)
    ax.set_xlim(a, b); ax.grid(alpha=0.2); fig.tight_layout(); fig.savefig(path); plt.close(fig)

if __name__ == "__main__":
    from falcon_deriv import fetch_deriv
    syms = sys.argv[1].split(","); chart_dir = sys.argv[2] if len(sys.argv) > 2 else None
    maxc = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    out = {}; pool = {}
    for sym in syms:
        df = None
        for attempt in range(4):
            try: df = fe.prep(fetch_deriv(sym)); break
            except Exception as e: err = str(e)[:120]; time.sleep(20 * (attempt + 1))
        if df is None: out[sym] = {"error": err}; continue
        out[sym] = {"candles": len(df), "costs": {}}
        for sp in (0.0, 1.0, 2.0):
            t, pip = run(df, sym, sp)
            out[sym]["costs"][str(sp)] = {k: summ(t[f(t)]) if len(t) else {"trades": 0} for k, f in TIERS.items()}
            pool.setdefault(str(sp), []).append(t)
            if sp == 1.0 and chart_dir and len(t):
                os.makedirs(chart_dir, exist_ok=True)
                sel = t[t.top].sort_values("time") if t.top.any() else t.sort_values("time")
                sel = pd.concat([sel[sel.broke & sel.nest], sel[~(sel.broke & sel.nest)]]).head(maxc)
                for i, (_, row) in enumerate(sel.iterrows()):
                    chart(df, row, pip, f"{chart_dir}/{sym}_{i+1}_{row.side}.png")
        time.sleep(3)
    out["POOLED"] = {}
    for sp, lst in pool.items():
        t = pd.concat(lst)
        out["POOLED"][sp] = {k: summ(t[f(t)]) if len(t) else {"trades": 0} for k, f in TIERS.items()}
        if sp == "1.0" and len(t):
            out["POOLED"]["by_side_top_broke_nest_cost1"] = {sd: summ(g[g.top & g.broke & g.nest]) for sd, g in t.groupby("side")}
    print(json.dumps(out, indent=1, default=str))
