# Falcon study: handoff (read this first)

**Owner:** Creaty (GitHub: Brunotet). **Goal:** learn the "Falcon" trendline trading strategy from a 34-video course, write a precise rulebook, then turn it into a scanner/backtester that finds entries. No indicators, just structure and trendlines. Nothing here is trading advice.

## How to continue in a new chat
Paste this to the assistant:

> Read https://github.com/Brunotet/falcon-study, start with HANDOFF.md, then strategy/falcon.md and strategy/falcon-part2.md. Continue learning the lessons marked Condensed or Not read in the table, and update the rulebook.

The repo is public: clone it with `git clone https://github.com/Brunotet/falcon-study` (works in the assistant's sandbox) and read the files. To push changes the assistant needs the user's n8n workflows (GitHub Writer / GitHub Reader helpers, found with `search_workflows`). Writes are `PUT /repos/Brunotet/falcon-study/contents/<path>` with base64 content (and the current `sha` when replacing a file). GitHub Actions runs are triggered with `POST .../actions/workflows/<file>/dispatches`.

## Repo map
- `out/<S1|S2|S3|F1|F2>/<lesson>/transcript.md`: full timestamped transcripts (Whisper small). `pairs.md`: screenshots paired with the speech around them. `frames/`: small jpgs.
- `strategy/falcon.md` (rulebook v6) and `strategy/falcon-part2.md` (additions from condensed reads; merge into falcon.md later).
- `status/*.json`: per-folder processing summaries.
- `.github/workflows/study.yml`: download one MEGA folder with MEGAcmd, transcribe, screenshot, commit (needs repo secret `MEGA_URL`; never paste the MEGA link into chat or inputs).
- `engine/falcon_engine.py` (stage 1 flag scanner + backtest), `falcon_stage2.py` (adds 4H structure top and structure-low target), `falcon_deriv.py` (Deriv synthetics), `falcon_indices.py` (index futures), `falcon_charts.py` (draws every trade).
- `results/`: backtest JSON and trade chart images.
- Google Sheet "Falcon Notes": one row per lesson (folder, title, minutes, read status, key rules, transcript link).
- Course folder layout (MEGA): foundation series (13 videos), quick tips S1/S2/S3 (7 each), Weekly Content (11 recaps, not processed yet).

## Reading progress (34 processed lessons)

Full read (23): S1E1, S1E2, S1E3, S1E4, S1E6, S1E7, S2E1, S2E2, S2E3, S2E4, S2E5, S3E1, S3E3, S3E4, S3E5, S3E6, S3E7, foundation ep 3 pt 1, ep 3 pt 2, ep 4, ep 5, ep 8, ep 10. Key-passage extraction (rule sentences only, 11): S1E5, S2E6, S2E7, S2 "Long Term Holds" (in folder S3), foundation ep 3 pt 3, ep 2 (technical analysis, mostly TradingView setup), ep 6 (broker), ep 7 (journaling), ep 9 (psychology), ep 1, trailer. These are in `falcon-part6.md`; anything marked there as extraction can be re-read in full if a rule looks thin. Not downloaded: the 11 Weekly Content trade recaps (real example trades, useful to validate the scanner).

Rulebook files: `strategy/falcon.md` (v6) plus `falcon-part2.md` to `falcon-part6.md`. Part 3: S1E1, S1E2, S1E6, S1E7, ten go-to setups (S3E3), running channel (S3E6). Part 4: 15m chart checklist (S3E1), multi-touch (S1E3). Part 5: entry types (ep 3 pt 2), probability (ep 4). Part 6: phase, forecasting, mass psychology, 90% rule, long-term holds, candles, orders, journaling. Merge them into one file when ready. Key finding so far: the scanner lacks his location and nesting filters (top/bottom of a structure, same pattern inside the pattern, 6-8 corrective candles, 15m only in the impulsive phase).

## What the rulebook covers (see the files for details)
Structure and multi-touch trendlines, impulse vs corrective, phases, valid vs high-probability trades (80/20), entry types (risk vs reduced risk), 1H retrace candle, the arc, flag types (tight, steep, larger, running channel, Falcon flag), pattern separation/evolving, 90% rule, order placement (entry stop orders), stops (min 15 pips, typically 25-35), 1% risk and 2% total open risk, minimum about 3:1 reward, management (break even after about 1-1.3% in mid-structure flags, but not quickly at the top/bottom of a structure; use candle closes).
Still open: how flat a "tight flag" must be in candle terms, the "3-step process", sessions/pairs, details lost in condensed reads.

## Backtest findings so far (be honest with the user)
- The scanner is unbiased on random walks (average about 0R, margin about 0.1R over 900+ trades). Single results on a few dozen trades are noise.
- Forex (8 pairs, 2 years, 690 trades): average -0.12R. Stage 2 (flags at 4H structure top): only 4-14 trades per year, too few to judge. Real index futures (501 trades): about -0.02R before costs. Charts show the scanner often labels ordinary pullbacks as flags, so it likely does not match what the instructor draws.
- Deriv synthetic indices are algorithm-generated random simulations, so no edge is expected; one cannot test "market psychology" on them. Deriv's new public API (`wss://api.derivws.com/trading/v1/options/ws/public`, no login for price history) is used by `falcon_deriv.py`.
- Next validation idea: compare scanner signals to the instructor's real trades in the weekly recaps.

## Working preferences
Short mobile-friendly answers, lead with the answer, plain honest results (including bad ones), build only when asked, never recommend Oracle Cloud or Google Cloud as hosting.
