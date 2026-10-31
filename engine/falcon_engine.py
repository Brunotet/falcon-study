"""Falcon scanner + backtester, stage 1: tight flags (1H) with rulebook stops, entry orders, 3R target.
Rules come from strategy/falcon.md (draft). Everything is a parameter, nothing is tuned on results.
Sells are detected; buys are found by mirroring prices (multiply by -1)."""
import sys, json
import numpy as np, pandas as pd

P = dict(
    imp_mult=6.0,      # impulse size >= imp_mult x median candle range
    imp_max=24,        # impulse lasts at most this many candles
    bear_frac=0.55,    # share of impulse candles closing in impulse direction
    min_flag=6, max_flag=14,   # flat correction length in 1H candles (rulebook: 6-8, up to 12-14)
    flat_ratio=0.5,    # flag range <= flat_ratio x impulse
    drift_max=0.2,     # |close drift| across flag <= drift_max x impulse (flat, not steep)
    entry_off=2, stop_off=3,   # pips beyond flag extreme
    min_stop=15, max_stop=55,  # rulebook: never under 15, skip above ~55-60
    order_life=24,     # entry order valid for this many candles
    target_r=3.0,      # rulebook: ~3:1 minimum
    be_at_r=1.0,       # break even after a close 1R in profit (~1% on 1% risk)
    spread=1.0,        # pips, cost per trade
    hold_max=240,
    range_win=240,     # lookback used for location-in-range (outer structure proxy)
)

def pipsize(sym): return 0.01 if "JPY" in sym.upper() else 0.0001

def prep(df):
    df = df.rename(columns=str.lower)[["open","high","low","close"]].dropna()
    return df[~df.index.duplicated()].sort_index()

def mirror(a): return -a

def find_setups(o, h, l, c, pip, p=P):
    """Return sell setups from candle arrays. Uses only data up to the signal candle."""
    n = len(c); out = []
    rng = pd.Series(h - l).rolling(200, min_periods=50).median().values
    used_start = -1
    for j in range(60, n - p["max_flag"] - 1):
        L = p["imp_max"]
        s = j - L + int(np.argmax(h[j - L:j + 1]))      # impulse start = highest high in window
        if s >= j or s <= used_start: continue
        if l[j] > l[max(0, j - L):j + 1].min(): continue   # j must be the window low
        size = h[s] - l[j]
        if np.isnan(rng[s]) or size < p["imp_mult"] * rng[s]: continue
        seg = slice(s, j + 1)
        if np.mean(c[seg] < o[seg]) < p["bear_frac"]: continue
        for nf in range(p["min_flag"], p["max_flag"] + 1):
            w = slice(j + 1, j + nf + 1)
            fh, fl = h[w].max(), min(l[w].min(), l[j])
            if fh >= h[s]: break
            if fl < l[j] - 0.1 * size: break                 # impulse still running
            if (fh - fl) > p["flat_ratio"] * size: continue
            if abs(c[j + nf] - c[j + 1]) > p["drift_max"] * size: continue
            entry = fl - p["entry_off"] * pip
            stop = fh + p["stop_off"] * pip
            risk = (stop - entry) / pip
            if risk < p["min_stop"]: stop = entry + p["min_stop"] * pip; risk = p["min_stop"]
            if risk > p["max_stop"]: break
            lo, hi = l[max(0, j - p["range_win"]):j + 1].min(), h[max(0, j - p["range_win"]):j + 1].max()
            loc = (fh - lo) / max(hi - lo, 1e-9)               # 1 = top of recent range
            prev_hi = h[max(0, s - 24):s].max(); old_hi = h[max(0, s - p["range_win"]):max(0, s - 24)]
            broke = bool(len(old_hi) and prev_hi >= old_hi.max())  # previous high was broken before the drop
            out.append(dict(t_idx=j + nf, entry=entry, stop=stop, risk_pips=risk, impulse_pips=size / pip,
                            flag_len=nf, loc=loc, high_prob=bool(loc >= 0.65 and broke), flag_high=fh))
            used_start = j
            break
    return out

def simulate(setup, o, h, l, c, pip, p=P):
    """Walk forward from the signal candle. Conservative: stop is checked before target in the same candle."""
    entry, stop, risk = setup["entry"], setup["stop"], setup["risk_pips"] * pip
    n = len(c); k = setup["t_idx"] + 1; end = min(n, k + p["order_life"])
    filled = None
    while k < end:
        if h[k] > setup["flag_high"] + p["stop_off"] * pip and l[k] > entry: return None   # invalidated before entry
        if l[k] <= entry: filled = k; break
        k += 1
    if filled is None: return None
    cur_stop = stop; r_exit = None; k = filled
    if h[k] >= cur_stop: return dict(i=filled, r=-1 - p["spread"] * pip / risk, why="stop_same_candle")
    target = entry - p["target_r"] * risk
    for k in range(filled + 1, min(n, filled + p["hold_max"])):
        if h[k] >= cur_stop:
            r_exit = (entry - cur_stop) / risk; why = "stop" if cur_stop == stop else "be"; break
        if l[k] <= target: r_exit = p["target_r"]; why = "target"; break
        if p["be_at_r"] and cur_stop == stop and c[k] <= entry - p["be_at_r"] * risk: cur_stop = entry
    else:
        kk = min(n, filled + p["hold_max"]) - 1; r_exit = (entry - c[kk]) / risk; why = "timeout"
    return dict(i=filled, r=r_exit - p["spread"] * pip / risk, why=why)

def run(df, sym, p=P):
    df = prep(df); pip = pipsize(sym); rows = []
    for side in ("sell", "buy"):
        a = [df[x].values.astype(float) for x in ("open", "high", "low", "close")]
        if side == "buy":
            o, h, l, c = -a[0], -a[2], -a[1], -a[3]
        else:
            o, h, l, c = a
        for s in find_setups(o, h, l, c, pip, p):
            r = simulate(s, o, h, l, c, pip, p)
            if r: rows.append(dict(symbol=sym, side=side, time=df.index[r["i"]], r=r["r"], why=r["why"],
                                   risk_pips=s["risk_pips"], flag_len=s["flag_len"], high_prob=s["high_prob"]))
    return pd.DataFrame(rows)

def summarize(t):
    if t.empty: return {"trades": 0}
    w = t.r[t.r > 0].sum(); lo = -t.r[t.r < 0].sum()
    return dict(trades=len(t), win_rate=round((t.r > 0).mean() * 100, 1), avg_r=round(t.r.mean(), 3),
                total_r=round(t.r.sum(), 1), profit_factor=round(w / lo, 2) if lo else None)

def fetch(sym, interval="1h", period="730d"):
    import yfinance as yf
    d = yf.download(sym + "=X", interval=interval, period=period, auto_adjust=False, progress=False)
    d.columns = [x[0] if isinstance(x, tuple) else x for x in d.columns]
    return d

if __name__ == "__main__":
    syms = sys.argv[1].split(",") if len(sys.argv) > 1 else ["GBPUSD", "EURUSD", "USDJPY"]
    allt = []
    for s in syms:
        try: allt.append(run(fetch(s), s))
        except Exception as e: print("fail", s, e)
    t = pd.concat(allt) if allt else pd.DataFrame()
    out = {"all": summarize(t)}
    if not t.empty:
        out["high_prob"] = summarize(t[t.high_prob]); out["valid_only"] = summarize(t[~t.high_prob])
        out["by_symbol"] = {k: summarize(g) for k, g in t.groupby("symbol")}
        out["by_exit"] = t.why.value_counts().to_dict()
    print(json.dumps(out, indent=1, default=str))
