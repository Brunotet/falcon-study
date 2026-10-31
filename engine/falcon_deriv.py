"""Falcon backtest on Deriv synthetic indices (1H candles from the public Deriv API).
Scale: 1 'pip' = median 1H range / 12, so the rulebook's pip numbers (15-55 stop, 1-3 pip offsets) keep the same
proportions they have on a typical forex pair. Costs are swept (0, 1, 2 'pips' = 0, ~8%, ~17% of a median hourly range).
Parameters are frozen (stage 1 defaults and stage 2 variant C: imp_mult 3.5, area_frac 0.5); nothing is tuned here."""
import sys, json, time
import numpy as np, pandas as pd
import falcon_engine as fe
import falcon_stage2 as f2

SYMS = "R_10,R_25,R_50,R_75,R_100,1HZ10V,1HZ25V,1HZ50V,1HZ75V,1HZ100V,BOOM500,BOOM1000,CRASH500,CRASH1000,stpRNG,JD10,JD25,JD50,JD75,JD100,RDBULL,RDBEAR".split(",")

HOSTS = ["wss://ws.derivws.com/websockets/v3?app_id=1089", "wss://ws.binaryws.com/websockets/v3?app_id=1089"]
HDRS = ["User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"]

def connect():
    import websocket
    errs = []
    for host in HOSTS:
        for origin in ("https://app.deriv.com", "https://deriv.com", None):
            try:
                kw = dict(timeout=30, header=HDRS)
                if origin: kw["origin"] = origin
                return websocket.create_connection(host, **kw)
            except Exception as e:
                errs.append(f"{host.split('/')[2]} origin={origin}: {str(e)[:60]}")
    raise RuntimeError(" | ".join(errs))

def fetch_deriv(sym, days=730):
    ws = connect()
    end = "latest"; rows = {}; floor = time.time() - days * 86400
    for _ in range(20):
        ws.send(json.dumps({"ticks_history": sym, "adjust_start_time": 1, "count": 5000, "end": end, "granularity": 3600, "style": "candles"}))
        r = json.loads(ws.recv())
        if "error" in r: raise RuntimeError(r["error"].get("message", "error"))
        c = r.get("candles", [])
        if not c: break
        for x in c: rows[x["epoch"]] = (x["open"], x["high"], x["low"], x["close"])
        first = min(x["epoch"] for x in c)
        if first <= floor: break
        end = first - 1
    ws.close()
    if not rows: raise RuntimeError("no data")
    df = pd.DataFrame.from_dict(rows, orient="index", columns=["open", "high", "low", "close"]).sort_index()
    df.index = pd.to_datetime(df.index, unit="s", utc=True)
    return df

def evaluate(df, sym, spread):
    pip = float(np.median((df.high - df.low).values)) / 12.0
    if pip <= 0: return {"trades": 0}, {"trades": 0}
    fe.pipsize = lambda s: pip; f2.pipsize = lambda s: pip
    fe.P["spread"] = spread; f2.P2["spread"] = spread
    f2.P2["area_frac"] = 0.5; fe.P["imp_mult"] = 3.5      # stage 2 variant C (frozen)
    t2 = f2.run2(df, sym, df.index[0])
    fe.P["imp_mult"] = 6.0                                # stage 1 default (frozen)
    t1 = fe.run(df, sym)
    return fe.summarize(t1), fe.summarize(t2)

if __name__ == "__main__":
    syms = sys.argv[1].split(",") if len(sys.argv) > 1 and sys.argv[1] else SYMS
    out = {}
    for s in syms:
        try:
            df = fetch_deriv(s); df = fe.prep(df)
            out[s] = {"candles": len(df), "costs": {}}
            for sp in (0.0, 1.0, 2.0):
                a, b = evaluate(df, s, sp)
                out[s]["costs"][str(sp)] = {"stage1_naive": a, "stage2_top": b}
        except Exception as e:
            out[s] = {"error": str(e)[:200]}
    print(json.dumps(out, indent=1, default=str))
