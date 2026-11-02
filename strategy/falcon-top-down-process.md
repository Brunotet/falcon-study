# Falcon: the user's top-down process (from his own USDJPY backtest screenshots, Aug-Sep 2024)

This is the reference for what a valid trade looks like. It overrides how v7/v8 scanned (single 1H line, no bias). Source: 4 screenshots (1D, 4H, 15m x2) with his drawings.

## What the screenshots show
1. **Daily (1D):** long uptrend to about 164, then an **impulse down** (white arrow), a big break of structure. That sets the bias: **short**.
2. **Daily/4H correction:** after the impulse the market **corrects up inside an ascending channel / rising wedge** with **three touches on the upper line** (boxed). The lower line runs from the impulse low. The trade zone is the **top of this structure**.
3. **4H:** same structure, clearer: touch 1 mid-Aug, touch 2 end of Aug, touch 3 on Sep 2, then the structure breaks down (impulse). The structure is the correction; the trade is the continuation of the earlier impulse.
4. **15m (entry timeframe):** at the third touch, price drops (first impulse), then a **small ascending channel / flag** forms (correction, "does not have to be beautiful, just enough correction to see we are consolidating"). Entry on the break of that flag, **stop just above the flag**, **target far below** (start of the correction / the impulse low, about 4R or more). After the next impulse down, **another flag forms and is traded again** (his two trades in one move were both wins).
5. Nested: the 15m flags are ascending channels inside the larger ascending 4H structure (ascending within ascending).

## Algorithm (to build as v9, top-down, no trade without all levels)
1. **Bias (daily/weekly):** most recent clear impulse leg (large, mostly one-direction candles, breaks the last swing). Bias = direction of that impulse until the correction breaks it. No impulse, no trade.
2. **Correction structure (4H):** after the impulse, an opposite-direction channel/wedge/flag: >= 2 pivots on each line, upper line (for shorts) with 2-3 touches, low momentum candles (80/20). Mark its upper line and its start (impulse low).
3. **Zone:** only trade when price is at the top zone (touch or small overshoot of the upper line) of that structure.
4. **Trigger (15m, 5m later):** first impulse away from the line (>= relative size), then a correction of >= 6 candles (flag) of any reasonable shape, relative tightness only. Entry stop order beyond the flag extreme, stop beyond the flag high (min 15 pips), no market orders.
5. **Target/management:** at least 3R, aiming for the start of the correction (90% rule) when the break is impulsive. Break even after about 1R mid-structure; lenient at the top. Re-enter on each new flag after the next impulse in the same move.
6. **Chart output for review:** every trade chart must show the daily bias leg, the 4H structure lines, the 15m flag, entry, stop, target (three panels).
