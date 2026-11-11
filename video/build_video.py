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


def timeline() -> dict:
    scenes = json.loads((DEMO / "script.json").read_text())
    t = LEAD
    out = []
    for s in scenes:
        audio = BUILD / "audio" / f"{s['id']}.mp3"
        d = duration(audio)
        parts = s["sentences"]
        total_chars = sum(len(p) for p in parts)
        cur, sents = t, []
        for p in parts:
            span = d * len(p) / total_chars
            sents.append({"text": p, "start": round(cur, 3), "end": round(cur + span, 3)})
            cur += span
        out.append({"id": s["id"], "start": t, "audio_dur": d, "audio": str(audio), "sentences": sents})
        t += d + GAP
    total = t - GAP + TAIL
    return {"scenes": out, "total": total}


def main() -> int:
    stills = "--stills" in sys.argv
    run = json.loads((BUILD / "rg_run.json").read_text())
    import base64
    cert = "data:image/png;base64," + base64.b64encode((BUILD / "certificate.png").read_bytes()).decode()
    tl = timeline()
    card = "data:image/png;base64," + base64.b64encode((BUILD / "card.png").read_bytes()).decode()
    data = {**tl, "transcript": run["transcript"], "runs": run["runs"], "cert_img": cert, "card_img": card}
    (BUILD / "timeline.json").write_text(json.dumps({k: v for k, v in data.items() if k not in ("cert_img", "card_img")}, indent=2))
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
