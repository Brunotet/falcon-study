# falcon-study

Turns a folder of strategy videos into text a model can study: timestamped transcripts plus chart screenshots paired with what the speaker said at that moment.

## Run
Actions tab > **Study videos** > Run workflow.
- `mega_url`: MEGA folder or file link (one subfolder per run, e.g. S1)
- `label`: short name for the output folder (e.g. S1)
- `whisper_model`: tiny / base / small (default small, CPU)
- `callback_url`: optional n8n URL that receives a short JSON summary

## Output (committed to the repo)
- `out/<label>/<video>/transcript.md` timestamped transcript
- `out/<label>/<video>/pairs.md` each screenshot with the transcript around it
- `out/<label>/<video>/frames/` small jpgs (max 40 per video)
- `status/<label>.json` counts, timings, errors

Videos are deleted after processing and never committed.
