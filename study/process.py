import json, re, subprocess, sys, time, traceback
from pathlib import Path

from faster_whisper import WhisperModel

VIDEO_EXT = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}
MAX_FRAMES = 40
SCENE = 0.3
FALLBACK_EVERY = 45  # seconds, used when scene detection finds too little


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def slug(s):
    return re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()[:60] or "video"


def fmt(t):
    t = int(t)
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"


def extract_audio(video, wav):
    r = run(["ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(wav)])
    if r.returncode != 0:
        raise RuntimeError("audio extract failed: " + r.stderr[-300:])


def extract_frames(video, fdir):
    fdir.mkdir(parents=True, exist_ok=True)
    for p in fdir.glob("*.jpg"):
        p.unlink()
    vf = f"select='gt(scene,{SCENE})',showinfo,scale=800:-2"
    r = run(["ffmpeg", "-y", "-i", str(video), "-vf", vf, "-vsync", "vfr", "-q:v", "6", str(fdir / "f_%04d.jpg")])
    times = [float(x) for x in re.findall(r"pts_time:([0-9.]+)", r.stderr)]
    files = sorted(fdir.glob("f_*.jpg"))
    if len(files) < 3:
        for p in files:
            p.unlink()
        run(["ffmpeg", "-y", "-i", str(video), "-vf", f"fps=1/{FALLBACK_EVERY},scale=800:-2", "-q:v", "6", str(fdir / "f_%04d.jpg")])
        files = sorted(fdir.glob("f_*.jpg"))
        times = [i * FALLBACK_EVERY for i in range(len(files))]
    times = times[: len(files)]
    if len(files) > MAX_FRAMES:
        step = len(files) / MAX_FRAMES
        keep = {int(i * step) for i in range(MAX_FRAMES)}
        for i, p in enumerate(files):
            if i not in keep:
                p.unlink()
        files = [p for i, p in enumerate(files) if i in keep]
        times = [t for i, t in enumerate(times) if i in keep]
    return list(zip(times, files))


def transcribe(model, wav):
    segs, info = model.transcribe(str(wav), vad_filter=True, beam_size=1)
    out = [(s.start, s.end, s.text.strip()) for s in segs]
    return out, info.duration


def write_outputs(vdir, name, segs, frames):
    vdir.mkdir(parents=True, exist_ok=True)
    with open(vdir / "transcript.md", "w") as f:
        f.write(f"# {name}\n\n")
        for s, e, t in segs:
            f.write(f"[{fmt(s)}] {t}\n")
    with open(vdir / "pairs.md", "w") as f:
        f.write(f"# {name}: screenshots with transcript\n\n")
        for i, (t, p) in enumerate(frames):
            nxt = frames[i + 1][0] if i + 1 < len(frames) else t + 90
            end = min(nxt, t + 90)
            text = " ".join(x for s, e, x in segs if e >= t and s < end)
            f.write(f"## [{fmt(t)}] frames/{p.name}\n{text or '(no speech)'}\n\n")


def main():
    raw = Path(sys.argv[1])
    out = Path(sys.argv[2])
    model_name = sys.argv[3] if len(sys.argv) > 3 else "small"
    label = out.name
    status = {"label": label, "model": model_name, "videos": [], "errors": []}
    Path("status").mkdir(exist_ok=True)
    videos = sorted(p for p in raw.rglob("*") if p.suffix.lower() in VIDEO_EXT)
    status["found"] = len(videos)
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    for v in videos:
        t0 = time.time()
        name = v.stem
        vdir = out / slug(name)
        wav = v.with_suffix(".wav")
        try:
            extract_audio(v, wav)
            segs, dur = transcribe(model, wav)
            frames = extract_frames(v, vdir / "frames")
            write_outputs(vdir, name, segs, frames)
            status["videos"].append({"name": name, "minutes": round(dur / 60, 1), "segments": len(segs), "frames": len(frames), "seconds_taken": round(time.time() - t0)})
        except Exception as e:
            status["errors"].append({"name": name, "error": str(e)[:300], "trace": traceback.format_exc()[-400:]})
        finally:
            for p in (v, wav):
                if p.exists():
                    p.unlink()
        with open(f"status/{label}.json", "w") as f:
            json.dump(status, f, indent=1)
    with open(f"status/{label}.json", "w") as f:
        json.dump(status, f, indent=1)


if __name__ == "__main__":
    main()
