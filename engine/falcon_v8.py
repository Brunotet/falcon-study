"""Falcon v8: fuller implementation of strategy/falcon-rulebook-v7.md on 1H data (4H structure built from it).
Setups: T = relative tight first flag (reduced risk); R = risk entry at the touch of the 4H ascending line (retrace candle, 2nd/3rd touch,
double top, nesting). Structure: 4H pivot highs -> line through last two pivots, touches counted. Targets: fixed 3R or the structure low (90% rule
proxy, only if >= 3R away). Management A = break even after a close 1R in profit; B = after 2R (lenient at the top). Nothing tuned.
src: deriv | forex (Yahoo, real pips) | indices (Yahoo, pip = median range/12). Real-market gap rule: skip if the fill candle opens through the entry."""
import sys, json, os, time
import numpy as np, pandas as pd
import falcon_engine as fe
import falcon_v7_deriv as v7

P = dict(v7.P); P.update(order_life=12, cooldown=12, touch_tol=0.35, k=2)

def structure(df, sign):
    """per-1H-bar structure lookups using only completed 4H bars. sign=-1 mirrors (buys)."""
    g = df.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    gh, gl = (g.high.values, g.low.values) if sign > 0 else (-g.low.values, -g.high.values)
    st = g.index + pd.Timedelta(hours=4)
    mm = np.searchsorted(st.values, df.index.values, side="right")            # completed 4H bars at each 1H bar
    pos = np.searchsorted(df.index.values, g.index.values, side="left")        # 1H index of each 4H bar start
    k = P["k"]; piv = [p for p in range(k, len(g) - k) if gh[p] == gh[p - k:p + k + 1].max()]
    cache = {}
    def at(m):
        if m in cache: return cache[m]
        ps = [p for p in piv if p <= m - k - 1 and p >= m - 150]; res = None
        if len(ps) >= 2:
            p1, p2 = ps[-2], ps[-1]; dx = pos[p2] - pos[p1]
            if dx > 0:
                slope = (gh[p2] - gh[p1]) / dx
                atr = float(np.median(gh[max(0, m - 50):m] - np.minimum.reduce([gl[max(0, m - 50):m]]))) if m > 5 else 0
                atr = float(np.median(np.abs(g.high.values[max(0, m - 50):m] - g.low.values[max(0, m - 50):m])))
                tol = P["touch_tol"] * atr
                touches = sum(1 for p in ps[-5:] if abs(gh[p] - (gh[p2] + slope * (pos[p] - pos[p2]))) <= tol)
                res = dict(slope=slope, a=gh[p2], pos=pos[p2], atr=atr, tol=tol, touches=touches, low=float(gl[p1:m].min()), asc=slope > 0)
        cache[m] = res; return res
    return mm, at

def find_R(o, h, l, c, pip, mm, at, p):
    n = len(c); out = []; last = -999; W = p["range_win"]
    for i in range(W, n - 2):
        s = at(mm[i])
        if not s or not s["asc"] or s["touches"] < 2 or i - last < p["cooldown"]: continue
        line = s["a"] + s["slope"] * (i - s["pos"])
        if h[i] < line - s["tol"] or h[i] > line + 1.5 * s["atr"]: continue
        if not (c[i] < o[i] and c[i - 1] > o[i - 1] and (o[i] - c[i]) >= 0.5 * (c[i - 1] - o[i - 1])): continue
        entry = l[i] - p["entry_off"] * pip; stop = max(h[i - 2:i + 1].max(), line) + p["stop_off"] * pip; risk = (stop - entry) / pip
        if risk < p["min_stop"]: stop = entry + p["min_stop"] * pip; risk = p["min_stop"]
        if risk > p["max_stop"]: continue
        dbl = any(abs(h[q] - h[i]) <= 0.25 * s["atr"] and h[q] >= line - 2 * s["tol"] for q in range(max(0, i - 40), i - 5))
        nest = bool(np.polyfit(np.arange(31), h[i - 30:i + 1], 1)[0] > 0)
        out.append(dict(kind="R", s=max(0, i - 30), j=i - 1, nf=0, t_idx=i, entry=entry, stop=stop, risk_pips=risk, flag_high=stop - p["stop_off"] * pip,
                        at_line=True, touches=s["touches"], dbl=dbl, nest=nest, low=s["low"], lp=(s["pos"], s["a"], s["slope"])))
        last = i
    return out

def add_struct_T(sets, mm, at, h, p):
    for x in sets:
        s = at(mm[x["t_idx"]]); x["kind"] = "T"
        if s and s["asc"]:
            line = s["a"] + s["slope"] * (x["t_idx"] - s["pos"])
            x.update(at_line=bool(h[x["s"]] >= line - 2 * s["tol"]), touches=s["touches"], dbl=False, low=s["low"], lp=(s["pos"], s["a"], s["slope"]))
        else: x.update(at_line=False, touches=0, dbl=False, low=None, lp=None)
        x["nest"] = bool(x["nest"])
    return sets

def sim2(st, o, h, l, c, pip, p, tprice, be_r, gap):
    entry, stop, risk = st["entry"], st["stop"], st["risk_pips"] * pip
    n = len(c); k = st["t_idx"] + 1; end = min(n, k + p["order_life"]); fill = None
    while k < end:
        if h[k] > st["flag_high"] + p["stop_off"] * pip and l[k] > entry: return None
        if l[k] <= entry: fill = k; break
        k += 1
    if fill is None or (gap and o[fill] < entry): return None
    cost = p["spread"] * pip / risk
    if h[fill] >= stop: return dict(fill=fill, exit=fill, r=-1 - cost, why="stop_same_candle", target=tprice)
    cur = stop; ex = None
    for k in range(fill + 1, min(n, fill + p["hold_max"])):
        if h[k] >= cur: r = (entry - cur) / risk; why = "stop" if cur == stop else "be"; ex = k; break
        if l[k] <= tprice: r = (entry - tprice) / risk; why = "target"; ex = k; break
        if cur == stop and c[k] <= entry - be_r * risk: cur = entry
    if ex is None: ex = min(n, fill + p["hold_max"]) - 1; r = (entry - c[ex]) / risk; why = "timeout"
    return dict(fill=fill, exit=ex, r=r - cost, why=why, target=tprice)

MODES = {"3R_A": ("3R", 1.0), "3R_B": ("3R", 2.0), "struct_B": ("struct", 2.0)}

def run(df, sym, spread, pip, gap):
    p = dict(P); p["spread"] = spread; rows = []
    for side, sg in (("sell", 1), ("buy", -1)):
        a = [df[x].values.astype(float) for x in ("open", "high", "low", "close")]
        o, h, l, c = (a[0], a[1], a[2], a[3]) if sg > 0 else (-a[0], -a[2], -a[1], -a[3])
        mm, at = structure(df, sg)
        sets = add_struct_T(v7.find(o, h, l, c, pip, p), mm, at, h, p) + find_R(o, h, l, c, pip, mm, at, p)
        for x in sets:
            row = dict(symbol=sym, side=side, kind=x["kind"], s=x["s"], j=x["j"], nf=x["nf"], at_line=x["at_line"], touches=x["touches"], dbl=x["dbl"], nest=x["nest"],
                       entry=x["entry"], stop=x["stop"], lp=x["lp"], risk_pips=x["risk_pips"]); ok = False
            for mname, (tm, ber) in MODES.items():
                tp = x["entry"] - p["target_r"] * x["risk_pips"] * pip
                if tm == "struct":
                    if x["low"] is None or (x["entry"] - x["low"]) < p["target_r"] * x["risk_pips"] * pip: row["r_" + mname] = np.nan; continue
                    tp = x["low"]
                r = sim2(x, o, h, l, c, pip, p, tp, ber, gap)
                if r is None: row["r_" + mname] = np.nan; continue
                row["r_" + mname] = r["r"]; ok = True
                if mname == "3R_A": row.update(time=df.index[r["fill"]], fill=r["fill"], exit=r["exit"], target=tp, why=r["why"])
            if ok and "fill" in row: rows.append(row)
    return pd.DataFrame(rows)

TIERS = {"T_all": lambda t: t.kind == "T", "T_at_line": lambda t: (t.kind == "T") & t.at_line, "R_all": lambda t: t.kind == "R",
         "R_touch3_or_dbl": lambda t: (t.kind == "R") & ((t.touches >= 3) | t.dbl), "R_nest": lambda t: (t.kind == "R") & t.nest,
         "R_dbl_nest": lambda t: (t.kind == "R") & t.dbl & t.nest, "ALL_at_line": lambda t: t.at_line}

def summ(t, col):
    x = t[col].dropna()
    return fe.summarize(pd.DataFrame({"r": x})) if len(x) else {"trades": 0}

def table(t):
    return {k: {m: summ(t[f(t)], "r_" + m) for m in MODES} for k, f in TIERS.items()} if len(t) else {}

def chart(df, row, pip, path):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    sell = row.side == "sell"; a, b = max(0, row.s - 10), min(len(df), row.exit + 12); d = df.iloc[a:b]; x = np.arange(a, b)
    fig, ax = plt.subplots(figsize=(9, 5), dpi=80)
    for xi, (_, r) in zip(x, d.iterrows()):
        col = "#2e9e5b" if r.close >= r.open else "#d04a4a"
        ax.vlines(xi, r.low, r.high, color=col, lw=1); ax.bar(xi, max(abs(r.close - r.open), 1e-9), bottom=min(r.open, r.close), width=0.7, color=col)
    sg = 1 if sell else -1; e, s_, tg = sg * row.entry, sg * row.stop, sg * row.target
    if row.lp is not None:
        pos, av, sl = row.lp; xs = np.array([a, b]); ax.plot(xs, sg * (av + sl * (xs - pos)), color="gray", lw=1.2, ls="-", label="4H line")
    if row.nf: ax.axvspan(row.j + 1, row.j + row.nf, color="#5b9bd5", alpha=0.2)
    ax.axhline(e, color="black", lw=1); ax.axhline(s_, color="red", ls="--", lw=1); ax.axhline(tg, color="green", ls="--", lw=1)
    ax.scatter([row.fill], [e], marker=">", s=70, color="black", zorder=5); ax.scatter([row.exit], [df.close.iloc[row.exit]], marker="x", s=70, color="purple", zorder=5)
    tag = f"{row.kind} touches={row.touches}" + (" dbl" if row.dbl else "") + (" nest" if row.nest else "") + (" at_line" if row.at_line else "")
    ax.set_title(f"{row.symbol} {row.side.upper()}  R={row.r_3R_A:+.2f} ({row.why})  [{tag}]", fontsize=9)
    ax.set_xlim(a, b); ax.grid(alpha=0.2); fig.tight_layout(); fig.savefig(path); plt.close(fig)

def load(src, sym):
    if src == "deriv":
        from falcon_deriv import fetch_deriv
        return fe.prep(fetch_deriv(sym))
    if src == "forex": return fe.prep(fe.fetch(sym))
    import yfinance as yf
    d = yf.download(sym, interval="1h", period="730d", auto_adjust=False, progress=False)
    d.columns = [x[0] if isinstance(x, tuple) else x for x in d.columns]
    return fe.prep(d)

if __name__ == "__main__":
    src, syms = sys.argv[1], sys.argv[2].split(","); cdir = sys.argv[3] if len(sys.argv) > 3 else None
    maxc = int(sys.argv[4]) if len(sys.argv) > 4 else 6
    out = {}; pool = {}
    for sym in syms:
        df = None
        for attempt in range(4):
            try: df = load(src, sym); break
            except Exception as e: err = str(e)[:120]; time.sleep(20 * (attempt + 1))
        if df is None or len(df) < 800: out[sym] = {"error": err if df is None else "too little data"}; continue
        pip = fe.pipsize(sym.replace("=X", "")) if src == "forex" else float(np.median((df.high - df.low).values)) / 12.0
        out[sym] = {"candles": len(df), "costs": {}}
        for sp in (0.0, 1.0, 2.0):
            t = run(df, sym, sp, pip, src != "deriv"); pool.setdefault(str(sp), []).append(t)
            if sp == 1.0:
                out[sym]["costs"]["1.0"] = table(t)
                if cdir and len(t):
                    os.makedirs(cdir, exist_ok=True)
                    sel = t[t.at_line].sort_values("time").head(maxc) if t.at_line.any() else t.sort_values("time").head(maxc)
                    for i, (_, row) in enumerate(sel.iterrows()): chart(df, row, pip, f"{cdir}/{sym.replace('^','').replace('=','')}_{i+1}_{row.kind}_{row.side}.png")
        time.sleep(3)
    out["POOLED"] = {sp: table(pd.concat(l)) for sp, l in pool.items() if any(len(x) for x in l)}
    print(json.dumps(out, indent=1, default=str))
