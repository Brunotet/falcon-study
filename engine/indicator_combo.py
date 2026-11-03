"""Indicator-combo baselines, fixed standard parameters, NOT tuned, to compare against Falcon on the same data (1H candles).
A trend+RSI pullback (EMA50>EMA200, RSI14 back through 35/65; stop 1.5 ATR, target 1.5 ATR)  B MACD+RSI (hist cross, RSI14>50, EMA200 trend; stop 1.5 ATR, target 3 ATR)
C Bollinger+RSI mean reversion (close outside BB(20,2) and RSI14<30/>70; exit at the middle band; stop 2 ATR)  D Connors RSI(2) (close>SMA200 and RSI2<5; exit close>SMA5; stop 3 ATR)
Entry at the next open, 1 position at a time, max hold 100 bars. Cost = 1 scaled pip per trade (median range/12; real pips for forex). R = result / stop distance. Reports both halves of the data."""
import sys, json, time
import numpy as np, pandas as pd
import falcon_engine as fe
import falcon_v8 as v8

def rsi(c, n):
    d = c.diff(); up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))

def signals(df):
    c, h, l = df.close, df.high, df.low; atr = (h - l).rolling(14).mean(); e50 = c.ewm(span=50, adjust=False).mean(); e200 = c.ewm(span=200, adjust=False).mean()
    r14 = rsi(c, 14); r2 = rsi(c, 2); ema12 = c.ewm(span=12, adjust=False).mean(); ema26 = c.ewm(span=26, adjust=False).mean(); macd = ema12 - ema26; hist = macd - macd.ewm(span=9, adjust=False).mean()
    mid = c.rolling(20).mean(); sd = c.rolling(20).std(); lo, up = mid - 2 * sd, mid + 2 * sd; s5 = c.rolling(5).mean(); s200 = c.rolling(200).mean()
    S = {}
    S["A_trend_rsi_pullback"] = dict(long=(e50 > e200) & (r14 > 35) & (r14.shift(1) <= 35), short=(e50 < e200) & (r14 < 65) & (r14.shift(1) >= 65), stop=1.5, tgt=1.5)
    S["B_macd_rsi"] = dict(long=(hist > 0) & (hist.shift(1) <= 0) & (r14 > 50) & (c > e200), short=(hist < 0) & (hist.shift(1) >= 0) & (r14 < 50) & (c < e200), stop=1.5, tgt=3.0)
    S["C_bollinger_rsi_mr"] = dict(long=(c < lo) & (r14 < 30), short=(c > up) & (r14 > 70), stop=2.0, tgt=None, mid=mid)
    S["D_connors_rsi2"] = dict(long=(c > s200) & (r2 < 5), short=(c < s200) & (r2 > 95), stop=3.0, tgt=None, ma=s5)
    return S, atr

def backtest(df, sig, atr, pip, spread=1.0, hold=100):
    o, h, l, c = [df[x].values for x in ("open", "high", "low", "close")]; a = atr.values; n = len(c); L = sig["long"].fillna(False).values; Sh = sig["short"].fillna(False).values; out = []; i = 210
    while i < n - 2:
        d = 1 if L[i] else (-1 if Sh[i] else 0)
        if d == 0 or np.isnan(a[i]) or a[i] <= 0: i += 1; continue
        e = o[i + 1]; risk = sig["stop"] * a[i]; stop = e - d * risk; tg = None if sig["tgt"] is None else e + d * sig["tgt"] * a[i]; r = None
        for k in range(i + 1, min(n, i + 1 + hold)):
            if d == 1 and l[k] <= stop or d == -1 and h[k] >= stop: r = -1.0; break
            if tg is not None and (d == 1 and h[k] >= tg or d == -1 and l[k] <= tg): r = sig["tgt"] / sig["stop"]; break
            if "mid" in sig and ((d == 1 and c[k] >= sig["mid"].values[k]) or (d == -1 and c[k] <= sig["mid"].values[k])): r = d * (c[k] - e) / risk; break
            if "ma" in sig and ((d == 1 and c[k] > sig["ma"].values[k]) or (d == -1 and c[k] < sig["ma"].values[k])): r = d * (c[k] - e) / risk; break
        if r is None: k = min(n, i + 1 + hold) - 1; r = d * (c[k] - e) / risk
        out.append(dict(i=i, r=r - spread * pip / risk)); i = k + 1
    return pd.DataFrame(out)

def summ(t):
    if t is None or len(t) == 0: return {"trades": 0}
    w = t.r[t.r > 0].sum(); ls = -t.r[t.r < 0].sum()
    return {"trades": len(t), "win_rate": round(float((t.r > 0).mean() * 100), 1), "avg_r": round(float(t.r.mean()), 3), "profit_factor": round(float(w / ls), 2) if ls > 0 else None}

if __name__ == "__main__":
    src, syms = sys.argv[1], sys.argv[2].split(","); out = {}; pool = {}
    for sym in syms:
        df = None
        for att in range(4):
            try: df = v8.load(src, sym); break
            except Exception as e: err = str(e)[:100]; time.sleep(20 * (att + 1))
        if df is None or len(df) < 1500: out[sym] = {"error": err if df is None else f"little data {len(df)}"}; continue
        pip = fe.pipsize(sym.replace("=X", "")) if src == "forex" else float(np.median((df.high - df.low).values)) / 12.0
        S, atr = signals(df); out[sym] = {"candles": len(df)}; half = len(df) // 2
        for name, sig in S.items():
            t = backtest(df, sig, atr, pip); first, second = t[t.i < half], t[t.i >= half]
            out[sym][name] = {"all": summ(t), "first_half": summ(first), "second_half": summ(second)}
            pool.setdefault(name, []).append(t.assign(h=(t.i >= half).astype(int)))
        time.sleep(2)
    out["POOLED"] = {n: {"all": summ(pd.concat(l)), "first_half": summ(pd.concat(l)[lambda x: x.h == 0]), "second_half": summ(pd.concat(l)[lambda x: x.h == 1])} for n, l in pool.items() if len(l)}
    print(json.dumps(out, indent=1, default=str))
