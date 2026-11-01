"""Re-run the Falcon scanner, record every trade it takes, and draw each trade as a chart.
Set A = stage 2 (variant C) dev year on the 8 forex pairs (all trades). Set B = random sample (seed 1) of stage 1 trades."""
import sys, os, json, random
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import falcon_engine as fe
import falcon_stage2 as f2

LOG = []; CUR = {"sym": "", "tag": ""}

def core(s, target, o, h, l, c, pip, spread, be_r, life, hold, soff):
    entry, stop, risk = s["entry"], s["stop"], s["risk_pips"] * pip
    n = len(c); k = s["t_idx"] + 1; end = min(n, k + life); fill = None
    while k < end:
        if h[k] > s["flag_high"] + soff * pip and l[k] > entry: return None
        if l[k] <= entry: fill = k; break
        k += 1
    if fill is None: return None
    cost = spread * pip / risk; cur = stop; be_i = None; exit_i = None; why = None; r = None
    if h[fill] >= cur: exit_i, why, r = fill, "stop_same_candle", -1 - cost
    else:
        for k in range(fill + 1, min(n, fill + hold)):
            if h[k] >= cur: exit_i, why, r = k, ("stop" if cur == stop else "break even"), (entry - cur) / risk - cost; break
            if l[k] <= target: exit_i, why, r = k, "target", (entry - target) / risk - cost; break
            if cur == stop and c[k] <= entry - be_r * risk: cur = entry; be_i = k
        else:
            exit_i = min(n, fill + hold) - 1; why = "timeout"; r = (entry - c[exit_i]) / risk - cost
    LOG.append(dict(sym=CUR["sym"], tag=CUR["tag"], mirrored=bool(c[0] < 0), s=dict(s), target=target, fill=fill, exit=exit_i,
                    be_i=be_i, r=r, why=why, pip=pip))
    return dict(i=fill, r=r, why=why)

def sim1(s, o, h, l, c, pip, p=fe.P):
    tgt = s["entry"] - p["target_r"] * s["risk_pips"] * pip
    return core(s, tgt, o, h, l, c, pip, p["spread"], p["be_at_r"], p["order_life"], p["hold_max"], p["stop_off"])

def sim2(s, target, o, h, l, c, pip, p=f2.P2):
    return core(s, target, o, h, l, c, pip, p["spread"], p["be_at_r"], p["order_life"], p["hold_max"], p["stop_off"])

fe.simulate = sim1; f2.simulate2 = sim2

def draw(t, df, path, n):
    sg = -1 if t["mirrored"] else 1
    a = max(0, t["s"]["t_idx"] - 70); b = min(len(df) - 1, t["exit"] + 25)
    d = df.iloc[a:b + 1]; x = np.arange(len(d))
    fig, ax = plt.subplots(figsize=(10, 5.2), dpi=90)
    for i, (o, h, l, c) in enumerate(zip(d.open, d.high, d.low, d.close)):
        col = "#2e9e6b" if c >= o else "#d9534f"
        ax.vlines(i, l, h, color=col, lw=0.8); ax.bar(i, abs(c - o) or 1e-9, bottom=min(o, c), width=0.7, color=col)
    E, S, T, F = (sg * t["s"][k] if k != "target" else sg * t["target"] for k in ("entry", "stop", "target", "flag_high"))
    sig = t["s"]["t_idx"] - a; fi = t["fill"] - a; xi = t["exit"] - a
    for y, col, lab in ((E, "#1f77b4", "entry"), (S, "#d62728", "stop"), (T, "#2ca02c", "target"), (F, "#888888", "flag " + ("low" if t["mirrored"] else "high"))):
        ax.hlines(y, sig, xi + 3, colors=col, linestyles="--", lw=1.1); ax.text(xi + 3.5, y, lab, color=col, fontsize=8, va="center")
    ax.axvspan(sig - t["s"]["flag_len"], sig, color="#999", alpha=0.15)
    ax.plot(fi, E, marker="v" if not t["mirrored"] else "^", color="#1f77b4", ms=9, zorder=5)
    ax.plot(xi, {"target": T, "stop": S, "stop_same_candle": S}.get(t["why"], E if t["why"] == "break even" else d.close.iloc[xi]), marker="X", color="black", ms=9, zorder=5)
    side = "BUY" if t["mirrored"] else "SELL"
    ax.set_title(f"#{n} {t['sym']} {side} [{t['tag']}]  result {t['r']:+.2f}R ({t['why']})  stop {t['s']['risk_pips']:.0f} pips  flag {t['s']['flag_len']}h", fontsize=10)
    step = max(1, len(d) // 8); ax.set_xticks(x[::step]); ax.set_xticklabels([str(ts)[5:13] for ts in d.index[::step]], fontsize=7, rotation=20)
    ax.grid(alpha=0.15); fig.tight_layout(); fig.savefig(path); plt.close(fig)

def render(trades, dfs, outdir):
    os.makedirs(outdir, exist_ok=True); rows = []
    for n, t in enumerate(trades, 1):
        draw(t, dfs[t["sym"]], f"{outdir}/{n:02d}_{t['sym']}_{'buy' if t['mirrored'] else 'sell'}_{t['r']:+.1f}R.png", n)
        rows.append(dict(n=n, sym=t["sym"], side="buy" if t["mirrored"] else "sell", fill_time=str(dfs[t["sym"]].index[t["fill"]]),
                         exit_time=str(dfs[t["sym"]].index[t["exit"]]), r=round(t["r"], 3), why=t["why"], risk_pips=round(t["s"]["risk_pips"], 1)))
    pd.DataFrame(rows).to_csv(outdir + "/trades.csv", index=False); return rows

if __name__ == "__main__":
    syms = (sys.argv[1] if len(sys.argv) > 1 else "GBPUSD,EURUSD,USDJPY,GBPJPY,AUDUSD,NZDCAD,GBPCAD,USDCAD").split(",")
    out = sys.argv[2] if len(sys.argv) > 2 else "results/charts"
    fetch = fe.fetch if len(sys.argv) <= 3 else None
    dfs = {}; A = []; B = []
    for s in syms:
        try: df = fe.prep(fe.fetch(s))
        except Exception as e: print("fail", s, e); continue
        dfs[s] = df; CUR["sym"] = s
        mid = df.index[0] + (df.index[-1] - df.index[0]) / 2
        # Set A: stage 2 variant C, dev year
        f2.P2["area_frac"] = 0.5; fe.P["imp_mult"] = 3.5; CUR["tag"] = "stage2"; LOG.clear()
        f2.run2(df[df.index < mid], s, df.index[0]); A += [dict(x) for x in LOG]
        # Set B: stage 1 default, full 2 years
        fe.P["imp_mult"] = 6.0; CUR["tag"] = "stage1"; LOG.clear(); fe.run(df, s); B += [dict(x) for x in LOG]
    random.Random(1).shuffle(B); B = sorted(B[:16], key=lambda t: (t["sym"], t["fill"]))
    ra = render(A, dfs, out + "/stage2"); rb = render(B, dfs, out + "/stage1_sample")
    print(json.dumps({"stage2_trades": len(A), "stage2_total_R": round(sum(t["r"] for t in A), 2), "stage1_sample": len(B)}, indent=1))
