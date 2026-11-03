"""Falcon v11: Falcon v10 rules with entries on the 5m chart + indicator confirmation (Connors-style RSI(2) and EMA200 trend), pre-registered, not tuned.
Daily bias and 4H channel are unchanged; the 15m bar counts of v10 are scaled x3 for 5m (impulse, flag, break-of-structure, hold). Confirmation (sell; buy mirrors):
F1 = RSI(2) reached >=90 inside the flag (the correction rally was overbought)   F2 = close below the 5m EMA200 at the end of the flag (trend aligned)   F12 = both.
Reports Falcon-5m alone vs each filter. Costs 1 and 2 scaled pips. Entry/exit trades are drawn on the 3-panel charts."""
import sys, json, os, time
import numpy as np, pandas as pd
import falcon_engine as fe
import falcon_v8 as v8
import falcon_v9 as v9
import falcon_v10 as v10

S = 3
v10.P.update(imp_max=24 * S, min_flag=6 * S, max_flag=24 * S, bos_first=48 * S, bos_re=24 * S, first_gap=8 * S, move_max=200 * S, order_life=24 * S, hold_max=960 * S, range_win=240 * S)

def rsi(c, n):
    d = c.diff(); up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))

def add_filters(df, t):
    if not len(t): return t
    r2 = rsi(df.close, 2).values; ema = df.close.ewm(span=200, adjust=False).mean().values; c = df.close.values; f1 = []; f2 = []
    for _, r in t.iterrows():
        w = slice(int(r.j) + 1, int(r.j) + int(r.nf) + 1); e = int(r.j) + int(r.nf)
        if r.side == "sell": f1.append(bool(np.nanmax(r2[w]) >= 90)); f2.append(bool(c[e] < ema[e]))
        else: f1.append(bool(np.nanmin(r2[w]) <= 10)); f2.append(bool(c[e] > ema[e]))
    t = t.copy(); t["F1"] = f1; t["F2"] = f2; return t

TIERS = {"falcon_5m_alone": lambda t: t.tu >= 0, "+F1_rsi2_overbought": lambda t: t.F1, "+F2_ema200_trend": lambda t: t.F2, "+F1_and_F2": lambda t: t.F1 & t.F2,
         "alone_first_entry": lambda t: t["first"], "F1F2_first_entry": lambda t: t.F1 & t.F2 & t["first"]}

def table(t):
    return {k: {m: v8.summ(t[f(t)], "r_" + m) for m in v9.MODES} for k, f in TIERS.items()} if len(t) else {}

def load5(src, sym):
    if src == "deriv": return fe.prep(v9.fetch15(sym, days=365, gran=300))
    import yfinance as yf
    d = yf.download(sym + ("=X" if src == "forex" else ""), interval="5m", period="60d", auto_adjust=False, progress=False)
    d.columns = [x[0] if isinstance(x, tuple) else x for x in d.columns]; return fe.prep(d)

if __name__ == "__main__":
    src, syms = sys.argv[1], sys.argv[2].split(","); cdir = sys.argv[3] if len(sys.argv) > 3 else None; maxc = int(sys.argv[4]) if len(sys.argv) > 4 else 6
    out = {}; pool = {}; alltr = []
    for sym in syms:
        df = None
        for att in range(4):
            try: df = load5(src, sym); break
            except Exception as e: err = str(e)[:120]; time.sleep(20 * (att + 1))
        if df is None or len(df) < 5000: out[sym] = {"error": err if df is None else f"too little data {len(df)}"}; continue
        pip = fe.pipsize(sym) if src == "forex" else float(np.median((df.high - df.low).values)) / 12.0
        out[sym] = {"candles": len(df), "costs": {}}
        for sp in (1.0, 2.0):
            t = add_filters(df, v10.run(df, sym, sp, pip, src != "deriv")); pool.setdefault(str(sp), []).append(t)
            if sp == 1.0:
                out[sym]["costs"]["1.0"] = table(t)
                if len(t): alltr.append(t.drop(columns=["lpU", "lpL", "dq"]))
                if cdir and len(t):
                    os.makedirs(cdir, exist_ok=True); sel = pd.concat([t[t.F1 & t.F2], t[~(t.F1 & t.F2)]]).head(maxc)
                    for i, (_, row) in enumerate(sel.iterrows()): v10.chart(df, row, f"{cdir}/{sym}_{i+1}_{row.side}{'_F12' if (row.F1 and row.F2) else ''}.png")
        time.sleep(3)
    out["POOLED"] = {sp: table(pd.concat(l)) for sp, l in pool.items() if any(len(x) for x in l)}
    if cdir and alltr: pd.concat(alltr).to_csv(cdir + "_trades.csv", index=False)
    print(json.dumps(out, indent=1, default=str))
