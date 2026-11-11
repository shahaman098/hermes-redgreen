#!/usr/bin/env python3
"""Generate per-scene narration with ElevenLabs. Key comes from $ELEVENLABS_API_KEY only."""
import json, os, subprocess, sys, urllib.request
from pathlib import Path

HERE = Path(__file__).parent
KEY = os.environ["ELEVENLABS_API_KEY"]
VOICE = os.environ.get("VOICE_ID", "ktkP7Nsj67dw2zcplQYt")  # Lawrence
scenes = json.loads((HERE / "script.json").read_text())
(HERE / "build" / "audio").mkdir(parents=True, exist_ok=True)
prev = ""
for i, s in enumerate(scenes):
    text = " ".join(s["sentences"])
    nxt = " ".join(scenes[i + 1]["sentences"]) if i + 1 < len(scenes) else ""
    body = {"text": text, "model_id": "eleven_multilingual_v2", "previous_text": prev, "next_text": nxt,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.05,
                               "use_speaker_boost": True, "speed": 1.05}}
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}?output_format=mp3_44100_128",
        data=json.dumps(body).encode(), headers={"xi-api-key": KEY, "Content-Type": "application/json"})
    out = HERE / "build" / "audio" / f"{s['id']}.mp3"
    out.write_bytes(urllib.request.urlopen(req).read())
    d = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)]).decode().strip()
    print(s["id"], d)
    prev = text
