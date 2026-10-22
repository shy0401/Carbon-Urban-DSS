"""나레이션 합성: python tts.py <lines.json> <out_dir> [speed]
lines.json = [{"id": "s01_01", "text": "..."}]. 이미 있는 wav는 건너뜀. 끝나면 Whisper(small)로 받아써서 check.json에 남김."""
import json
import os
import sys

from melo.api import TTS

lines = json.load(open(sys.argv[1], encoding="utf-8"))
out = sys.argv[2]
speed = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
os.makedirs(out, exist_ok=True)
model = TTS(language="KR", device="cpu")
spk = model.hps.data.spk2id["KR"]
for i, line in enumerate(lines):
    path = os.path.join(out, f"{line['id']}.wav")
    if os.path.exists(path):
        continue
    model.tts_to_file(line["text"], spk, path, speed=speed, quiet=True)
    print(f"{i + 1}/{len(lines)} {line['id']}", flush=True)

try:
    import whisper
except ImportError as e:  # 받아쓰기 점검 도구가 없으면 합성만 끝낸다
    print("whisper unavailable:", e, flush=True)
    sys.exit(0)
asr = whisper.load_model("small")
check = []
for line in lines:
    path = os.path.join(out, f"{line['id']}.wav")
    r = asr.transcribe(path, language="ko", fp16=False)
    check.append({"id": line["id"], "text": line["text"], "heard": r["text"].strip()})
json.dump(check, open(os.path.join(out, "check.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("checked", len(check), flush=True)
