"""약한 줄 다시 합성: python tts_best.py <lines.json> <ids.json> <out_dir> [n=3]
줄마다 n번 합성(잡음이 달라 매번 조금 다름) → Whisper(small)로 받아써 대본과 가장 가까운 것을 <out_dir>/<id>.wav로 둔다.
결과는 <out_dir>/best.json (id, 후보 점수, 받아쓴 글)."""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from score import score  # noqa: E402

import whisper  # noqa: E402
from melo.api import TTS  # noqa: E402

lines = {x["id"]: x["text"] for x in json.load(open(sys.argv[1], encoding="utf-8"))}
ids = json.load(open(sys.argv[2], encoding="utf-8"))
out = sys.argv[3]
n = int(sys.argv[4]) if len(sys.argv) > 4 else 3
tmp = os.path.join(out, "_cand")
os.makedirs(tmp, exist_ok=True)
model = TTS(language="KR", device="cpu")
spk = model.hps.data.spk2id["KR"]
asr = whisper.load_model("small")
report = []
for lid in ids:
    text = lines[lid]
    cands = []
    old = os.path.join(out, f"{lid}.wav")
    if os.path.exists(old):
        heard = asr.transcribe(old, language="ko", fp16=False)["text"].strip()
        cands.append((score(text, heard), old, heard))
    for k in range(n):
        path = os.path.join(tmp, f"{lid}_{k}.wav")
        model.tts_to_file(text, spk, path, speed=1.0, quiet=True)
        heard = asr.transcribe(path, language="ko", fp16=False)["text"].strip()
        cands.append((score(text, heard), path, heard))
    best = max(cands, key=lambda c: c[0])
    if best[1] != old:
        shutil.copyfile(best[1], old)
    report.append({"id": lid, "text": text, "scores": [round(c[0], 3) for c in cands], "best": round(best[0], 3), "heard": best[2]})
    print(lid, [round(c[0], 3) for c in cands], "->", round(best[0], 3), flush=True)
json.dump(report, open(os.path.join(out, "best.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
shutil.rmtree(tmp, ignore_errors=True)
print("done", len(report), flush=True)
