#!/usr/bin/env python3
"""Render the RedGreen demo film: real demo.py run + ElevenLabs narration -> MP4.

    python3 demo/build_video.py            # full render
    python3 demo/build_video.py --stills   # a few preview frames only

Needs: playwright (chromium), ffmpeg, and per-scene MP3s in demo/build/audio/
(generated from demo/script.json).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = Path(__file__).resolve().parent
BUILD = DEMO / "build"
FPS = 30
LEAD, GAP, TAIL = 0.6, 0.55, 2.6


def duration(path: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]
    )
    return float(out.decode().strip())


def sentence_starts(audio: Path, dur: float, parts: list[str]) -> list[float]:
    """Where each sentence begins in the clip, from the audio's own pauses.

    The n-1 longest internal pauses are the sentence breaks. If that disagrees badly with a
    character-proportional estimate, fall back to the estimate.
    """
    total = sum(len(x) for x in parts)
    est, acc = [], 0.0
    for x in parts:
        est.append(dur * acc / total)
        acc += len(x)
    if len(parts) == 1:
        return [0.0]
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(audio), "-af", "silencedetect=noise=-38dB:d=0.12", "-f", "null", "-"],
        capture_output=True, text=True).stderr
    starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", out)]
    ends = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", out)]
    pauses = [(e - st, e) for st, e in zip(starts, ends) if st > 0.3 and e < dur - 0.2]
    bounds = [0.0]
    for i in range(1, len(parts)):
        near = [(abs(e - est[i]) - 0.5 * ln, e) for ln, e in pauses if abs(e - est[i]) <= 1.3 and e > bounds[-1] + 0.4]
        bounds.append(min(near)[1] if near else est[i])
    return bounds


def timeline() -> dict:
    scenes = json.loads((DEMO / "script.json").read_text())
    t = LEAD
    out = []
    for s in scenes:
        audio = BUILD / "audio" / f"{s['id']}.mp3"
        d = duration(audio)
        parts = s["sentences"]
        bounds = sentence_starts(audio, d, parts)   # seconds inside the clip where each sentence begins
        sents = []
        for i, part in enumerate(parts):
            a = t + bounds[i]
            b = t + (bounds[i + 1] if i + 1 < len(parts) else d)
            sents.append({"text": part, "start": round(a, 3), "end": round(b, 3)})
        out.append({"id": s["id"], "start": t, "audio_dur": d, "audio": str(audio), "sentences": sents})
        t += d + GAP
    total = t - GAP + TAIL
    return {"scenes": out, "total": total}


def main() -> int:
    stills = "--stills" in sys.argv
    run = json.loads((BUILD / "rg_run.json").read_text())
    import base64
    tl = timeline()
    card = "data:image/png;base64," + base64.b64encode((BUILD / "card.png").read_bytes()).decode()
    host = json.loads((BUILD / "host_run.json").read_text())
    data = {**tl, "host": host, "transcript": run["transcript"], "runs": run["runs"], "card_img": card}
    (BUILD / "timeline.json").write_text(json.dumps({k: v for k, v in data.items() if k not in ("card_img",)}, indent=2))
    print(f"total {tl['total']:.2f}s")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto((DEMO / "film.html").as_uri())
        page.wait_for_load_state("networkidle")
        page.evaluate("document.fonts.ready")
        page.evaluate("(d) => init(d)", data)

        if stills:
            BUILD.joinpath("stills").mkdir(exist_ok=True)
            for s in tl["scenes"]:
                for k, sent in enumerate(s["sentences"]):
                    at = sent["end"] - 0.1
                    page.evaluate(f"renderAt({at})")
                    page.screenshot(path=str(BUILD / "stills" / f"{s['id']}_{k}.jpg"), type="jpeg", quality=80)
            browser.close()
            return 0

        silent = BUILD / "video_silent.mp4"
        ff = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg",
             "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", str(silent)],
            stdin=subprocess.PIPE,
        )
        n = int(tl["total"] * FPS)
        for i in range(n):
            page.evaluate(f"renderAt({i / FPS})")
            ff.stdin.write(page.screenshot(type="jpeg", quality=93))
            if i % 300 == 0:
                print(f"frame {i}/{n}", flush=True)
        ff.stdin.close()
        ff.wait()
        browser.close()

    # narration track: each scene's clip placed at its start time
    inputs, filters = [], []
    for i, s in enumerate(tl["scenes"]):
        inputs += ["-i", s["audio"]]
        ms = int(s["start"] * 1000)
        filters.append(f"[{i + 1}:a]adelay={ms}|{ms},aresample=48000[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(len(tl["scenes"])))
    filters.append(f"{mix}amix=inputs={len(tl['scenes'])}:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11,apad[aout]")
    final = ROOT / "redgreen-demo.mp4"
    subprocess.check_call(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), *inputs, "-filter_complex", ";".join(filters),
         "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
         "-movflags", "+faststart", str(final)]
    )

    # sidecar captions
    def ts(x: float) -> str:
        h, rem = divmod(x, 3600)
        m, s = divmod(rem, 60)
        return f"{int(h):02}:{int(m):02}:{s:06.3f}".replace(".", ",")

    srt, idx = [], 1
    for s in tl["scenes"]:
        for c in s["sentences"]:
            srt.append(f"{idx}\n{ts(c['start'])} --> {ts(c['end'] + 0.2)}\n{c['text']}\n")
            idx += 1
    (DEMO / "redgreen-demo.srt").write_text("\n".join(srt))
    print("wrote", final)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
