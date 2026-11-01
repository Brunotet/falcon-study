"""Falcon backtest on real stock-index data (index futures + cash indices, 1H from Yahoo via yfinance).
Same frozen rules as falcon_deriv.py (stage 1 default; stage 2 variant C). 1 'pip' = median 1H range / 12.
Gap rule: if the fill candle OPENS beyond the entry price (a gap), the trade is skipped (no unrealistic fill at entry)."""
import sys, json
import numpy as np, pandas as pd
import falcon_engine as fe
import falcon_stage2 as f2
import falcon_deriv as fd

SKIPPED = {"n": 0}
_s1, _s2 = fe.simulate, f2.simulate2

def sim1(setup, o, h, l, c, pip, p=fe.P):
    r = _s1(setup, o, h, l, c, pip, p)
    if r and o[r["i"]] < setup["entry"]: SKIPPED["n"] += 1; return None
    return r

def sim2(s, target, o, h, l, c, pip, p=f2.P2):
    r = _s2(s, target, o, h, l, c, pip, p)
    if r and o[r["i"]] < s["entry"]: SKIPPED["n"] += 1; return None
    return r

fe.simulate = sim1; f2.simulate2 = sim2

SYMS = "ES=F,NQ=F,YM=F,RTY=F,^GDAXI,^FTSE,^N225".split(",")

def fetch(sym):
    import yfinance as yf
    d = yf.download(sym, interval="1h", period="730d", auto_adjust=False, progress=False)
    d.columns = [x[0] if isinstance(x, tuple) else x for x in d.columns]
    return d

if __name__ == "__main__":
    syms = sys.argv[1].split(",") if len(sys.argv) > 1 and sys.argv[1] else SYMS
    out = {}
    for s in syms:
        try:
            df = fe.prep(fetch(s)); SKIPPED["n"] = 0
            out[s] = {"candles": len(df), "costs": {}}
            for sp in (0.0, 0.5, 1.0):
                a, b = fd.evaluate(df, s, sp)
                out[s]["costs"][str(sp)] = {"stage1_naive": a, "stage2_top": b}
            out[s]["gap_skipped_total"] = SKIPPED["n"]
        except Exception as e:
            out[s] = {"error": str(e)[:200]}
    print(json.dumps(out, indent=1, default=str))
