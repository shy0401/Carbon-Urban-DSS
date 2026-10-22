"""사용 영상 합성: 화면(1920×1080 JPG) + 강조 상자 + 커서 + 자막 + 카드 → 줄별 mp4 → 이어 붙이기, 나레이션·음악 섞기.

python render.py <spec.json> <shots_dir> <audio_dir> <out_dir> [--only id,id] [--jobs 2]
- 줄 길이 = 나레이션 길이 + 앞 0.5초 + 뒤 0.7초 (최소 3.5초). 장(chapter)이 바뀌는 줄 앞에 2.2초 장 제목 카드.
- 화면: 처음 전체 → 0.4초부터 강조 상자 쪽으로 천천히 확대(최대 1.75배) → 상자 테두리·바깥 어둡게.
- pre 화면이 있으면: 커서가 누를 곳으로 이동 → 물결 → 바뀐 화면으로 0.3초 겹쳐 넘어감.
"""
import json
import math
import os
import subprocess
import sys
import wave
from concurrent.futures import ProcessPoolExecutor

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1920, 1080, 30
FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-{w}.ttc"
C = {"nav": (31, 58, 51), "primary": (47, 93, 80), "ink": (28, 38, 34), "canvas": (243, 243, 238), "accent": (226, 160, 63),
     "hl": (233, 150, 40), "white": (255, 255, 255), "mint": (159, 181, 171), "warn": (138, 90, 0)}
LEAD, TAIL, MIN_LEN, CHAPTER_LEN = 0.5, 0.7, 3.5, 2.4


def font(size, weight="Medium"):
    return ImageFont.truetype(FONT.format(w=weight), size, index=1)


def ease(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def ease_out(t):
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


def wav_len(path):
    with wave.open(path) as w:
        return w.getnframes() / w.getframerate()


def plain(text):
    return str(text).replace("₂", "2").replace("²", "²")


def wrap(draw, text, fnt, width):
    """Wrap Korean text by words (spaces), falling back to characters."""
    text = plain(text)
    lines, cur = [], ""
    for word in text.split(" "):
        trial = (cur + " " + word).strip()
        if draw.textlength(trial, font=fnt) <= width:
            cur = trial
            continue
        if cur:
            lines.append(cur)
        cur = word
        while draw.textlength(cur, font=fnt) > width:      # very long token
            for k in range(len(cur), 0, -1):
                if draw.textlength(cur[:k], font=fnt) <= width:
                    lines.append(cur[:k]); cur = cur[k:]; break
    if cur:
        lines.append(cur)
    return lines


def subtitle_layer(text):
    """Bottom subtitle on a soft dark plate (RGBA, full frame)."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fnt = font(38, "Medium")
    lines = wrap(d, text, fnt, 1500)[:3]
    lh = 54
    tw = max(d.textlength(l, font=fnt) for l in lines)
    bw, bh = tw + 72, lh * len(lines) + 34
    x0, y0 = (W - bw) / 2, H - 70 - bh
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=16, fill=(16, 24, 21, 205))
    for i, l in enumerate(lines):
        lw = d.textlength(l, font=fnt)
        d.text(((W - lw) / 2, y0 + 15 + i * lh), l, font=fnt, fill=(255, 255, 255, 255))
    return img


def chip_layer(text):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if not text:
        return img
    d = ImageDraw.Draw(img)
    fnt = font(26, "Bold")
    text = plain(text)
    tw = d.textlength(text, font=fnt)
    x0, y0 = 24, 20
    d.rounded_rectangle([x0, y0, x0 + tw + 58, y0 + 52], radius=26, fill=(*C["nav"], 238), outline=(*C["hl"], 255), width=2)
    d.ellipse([x0 + 18, y0 + 20, x0 + 30, y0 + 32], fill=(*C["hl"], 255))
    d.text((x0 + 40, y0 + 9), text, font=fnt, fill=(240, 245, 242, 255))
    return img


def progress_layer(frac):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, H - 6, W, H], fill=(0, 0, 0, 70))
    d.rectangle([0, H - 6, int(W * frac), H], fill=(*C["hl"], 230))
    return img


# ── cards ────────────────────────────────────────────────────────────
def card_base():
    img = Image.new("RGB", (W, H), C["nav"])
    d = ImageDraw.Draw(img)
    # subtle diagonal grid like a city plan
    for x in range(-H, W, 60):
        d.line([(x, H), (x + H, 0)], fill=(36, 66, 58), width=1)
    for y in range(0, H, 60):
        d.line([(0, y), (W, y)], fill=(34, 63, 55), width=1)
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    return img


def leaf(d, cx, cy, r, color):
    """A leaf (two arcs meeting at the tips) with a midrib, tilted 45°."""
    pts = []
    for k in range(41):
        u = k / 40
        pts.append((u, 0.42 * math.sin(math.pi * u)))
    pts += [(u, -w) for u, w in reversed(pts)]
    ang = -math.pi / 4
    xy = [(cx + (u - 0.5) * 2 * r * math.cos(ang) - w * 2 * r * math.sin(ang), cy + (u - 0.5) * 2 * r * math.sin(ang) + w * 2 * r * math.cos(ang)) for u, w in pts]
    d.polygon(xy, fill=color)
    a, b = (cx - r * math.cos(ang), cy - r * math.sin(ang)), (cx + r * 0.7 * math.cos(ang), cy + r * 0.7 * math.sin(ang))
    d.line([a, b], fill=C["nav"], width=4)
    d.line([(a[0] - r * 0.25, a[1] + r * 0.25), a], fill=color, width=5)


def render_card(card, chapter=None):
    img = card_base()
    d = ImageDraw.Draw(img)
    kind = card["kind"]
    white, mint, hl = (240, 245, 242), (159, 181, 171), C["hl"]
    if kind == "title":
        leaf(d, W / 2, 360, 54, hl)
        for text, size, weight, y, col in ((card["title"], 104, "Bold", 450, white), (card["subtitle"], 54, "Medium", 590, mint), (card.get("foot", ""), 30, "Regular", 700, mint)):
            f = font(size, weight); tw = d.textlength(text, font=f); d.text(((W - tw) / 2, y), text, font=f, fill=col)
    elif kind == "chapter":
        f = font(30, "Medium"); d.text((160, 400), "CHAPTER", font=f, fill=hl)
        f = font(84, "Bold"); d.text((160, 450), card["title"], font=f, fill=white)
        d.rectangle([160, 590, 300, 596], fill=hl)
    elif kind == "chapters":
        f = font(60, "Bold"); d.text((160, 120), card["title"], font=f, fill=white)
        f = font(38, "Medium")
        for i, item in enumerate(card["items"]):
            col, row = i // 5, i % 5
            x, y = 160 + col * 820, 270 + row * 120
            d.rounded_rectangle([x, y, x + 760, y + 92], radius=18, fill=(40, 74, 64))
            d.ellipse([x + 22, y + 22, x + 70, y + 70], fill=hl)
            n = str(i + 1); fw = d.textlength(n, font=font(28, "Bold"))
            d.text((x + 46 - fw / 2, y + 26), n, font=font(28, "Bold"), fill=C["nav"])
            d.text((x + 96, y + 20), plain(item), font=f, fill=white)
    elif kind == "power":
        d.text((160, 110), card.get("chapter", ""), font=font(56, "Bold"), fill=white)
        blocks = [("on", "Carbon DSS 켜기", "Docker → DB·API·화면·공개 연결 (2~4분)", "http://localhost:5173"),
                  ("pages", "안내 주소 (밖에서)", "바뀌는 시연 서버로 연결 · 시연 계정 로그인", "shy0401.github.io/Carbon-Urban-DSS"),
                  ("off", "Carbon DSS 끄기", "DB 안전 종료 → Docker 끄기 · 수집 중에는 켜 두기", "재부팅해도 스스로 켜지지 않음")]
        for i, (key, head, body, foot) in enumerate(blocks):
            x, y = 160 + i * 540, 300
            on = card.get("focus") == key
            d.rounded_rectangle([x, y, x + 500, y + 470], radius=26, fill=(52, 92, 80) if on else (38, 70, 61), outline=hl if on else (60, 98, 87), width=5 if on else 2)
            d.rounded_rectangle([x + 40, y + 50, x + 460, y + 150], radius=18, fill=hl if on else (70, 110, 98))
            fw = d.textlength(head, font=font(40, "Bold")); d.text((x + 250 - fw / 2, y + 74), head, font=font(40, "Bold"), fill=C["nav"] if on else white)
            for j, l in enumerate(wrap(d, body, font(32, "Regular"), 420)):
                d.text((x + 40, y + 200 + j * 48), l, font=font(32, "Regular"), fill=white)
            for j, l in enumerate(wrap(d, foot, font(28, "Medium"), 420)):
                d.text((x + 40, y + 360 + j * 40), l, font=font(28, "Medium"), fill=mint)
    elif kind == "restricted":
        d.text((160, 110), card.get("chapter", ""), font=font(56, "Bold"), fill=white)
        d.text((160, 200), "이 PC에서만 보이는 기능", font=font(40, "Medium"), fill=hl)
        for i, (head, body) in enumerate(card["items"]):
            y = 285 + i * 155
            d.rounded_rectangle([160, y, W - 160, y + 135], radius=20, fill=(40, 74, 64))
            d.rectangle([160, y, 172, y + 135], fill=hl)
            d.text((210, y + 22), plain(head), font=font(40, "Bold"), fill=white)
            d.text((210, y + 80), plain(body), font=font(30, "Regular"), fill=mint)
        for j, l in enumerate(wrap(d, card.get("foot", ""), font(30, "Medium"), W - 320)):
            d.text((160, 770 + j * 44), l, font=font(30, "Medium"), fill=(240, 205, 150))
    elif kind == "end":
        leaf(d, W / 2, 250, 46, hl)
        f = font(90, "Bold"); tw = d.textlength(card["title"], font=f); d.text(((W - tw) / 2, 330), card["title"], font=f, fill=white)
        f = font(36, "Medium")
        for i, l in enumerate(card["lines"]):
            tw = d.textlength(l, font=f); d.text(((W - tw) / 2, 500 + i * 70), l, font=f, fill=mint)
    return img


# ── screenshot motion ───────────────────────────────────────────────
def target_view(box):
    """Crop rect (x0, y0, w, h) in source pixels that frames the focus box."""
    if not box:
        return (0, 0, W, H)
    x, y, w, h = box
    pad = 70
    need_w, need_h = w + 2 * pad, h + 2 * pad + 150      # room for the subtitle at the bottom
    scale = max(need_w / W, need_h / H)
    scale = min(max(scale, 1 / 1.75), 1.0)                # zoom between 1.0x and 1.75x
    vw, vh = W * scale, H * scale
    cx, cy = x + w / 2, y + h / 2 + 50
    x0 = min(max(cx - vw / 2, 0), W - vw)
    y0 = min(max(cy - vh / 2, 0), H - vh)
    return (x0, y0, vw, vh)


def lerp_view(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(4))


def to_out(box, view):
    x0, y0, vw, vh = view
    sx, sy = W / vw, H / vh
    x, y, w, h = box
    return ((x - x0) * sx, (y - y0) * sy, w * sx, h * sy)


def draw_cursor(d, x, y, scale=1.0):
    pts = [(0, 0), (0, 34), (9, 26), (16, 41), (22, 38), (15, 24), (27, 24)]
    pts = [(x + px * scale, y + py * scale) for px, py in pts]
    d.polygon([(px + 2, py + 3) for px, py in pts], fill=(0, 0, 0, 90))
    d.polygon(pts, fill=(255, 255, 255, 255), outline=(20, 20, 20, 255))


def render_segment(job):
    seg, out_path = job["seg"], job["out"]
    dur = seg["dur"]
    n = int(round(dur * FPS))
    sub = subtitle_layer(seg["sub"]) if seg.get("sub") else None
    chip = chip_layer(seg.get("chip"))
    proc = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                             "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-r", str(FPS), out_path], stdin=subprocess.PIPE)
    if seg["type"] == "card":
        base = render_card(seg["card"]).convert("RGB")
        for i in range(n):
            t = i / FPS
            z = 1 + 0.03 * (t / max(dur, 0.1))
            vw, vh = W / z, H / z
            frame = base.resize((W, H), Image.BICUBIC, box=((W - vw) / 2, (H - vh) / 2, (W + vw) / 2, (H + vh) / 2)).convert("RGBA")
            if sub is not None and seg.get("card_sub", True):
                frame.alpha_composite(sub)
            frame.alpha_composite(progress_layer(seg["p0"] + (seg["p1"] - seg["p0"]) * i / max(n, 1)))
            fade = min(1.0, t / 0.35, (dur - t) / 0.35)
            arr = np.asarray(frame.convert("RGB"), dtype=np.float32)
            if fade < 1:
                arr *= max(fade, 0)
            proc.stdin.write(arr.astype(np.uint8).tobytes())
    else:
        post = Image.open(seg["img"]).convert("RGB").resize((W, H))
        pre = Image.open(seg["pre"]).convert("RGB").resize((W, H)) if seg.get("pre") else None
        focus, click = seg.get("focus"), seg.get("click")
        t_switch = 1.6 if pre is not None else 0.0          # pre → post crossfade at this time
        view_end = target_view(focus)
        full = (0, 0, W, H)
        for i in range(n):
            t = i / FPS
            # which image
            if pre is not None and t < t_switch + 0.3:
                k = 0.0 if t < t_switch else (t - t_switch) / 0.3
                src = pre if k <= 0 else Image.blend(pre, post, ease(k))
            else:
                src = post
            zt = ease((t - (t_switch + 0.4)) / 1.3) if focus else 0.0
            view = lerp_view(full, view_end, zt) if focus else (lambda z: ((W - W / z) / 2, (H - H / z) / 2, W / z, H / z))(1 + 0.035 * t / max(dur, 0.1))
            x0, y0, vw, vh = view
            frame = src.resize((W, H), Image.BICUBIC, box=(x0, y0, x0 + vw, y0 + vh)).convert("RGBA")
            ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            od = ImageDraw.Draw(ov)
            if focus and zt > 0.05:
                fx, fy, fw, fh = to_out(focus, view)
                a = ease((t - (t_switch + 1.1)) / 0.5)
                if a > 0:
                    dim = Image.new("RGBA", (W, H), (10, 18, 15, int(95 * a)))
                    hole = Image.new("L", (W, H), 255)
                    ImageDraw.Draw(hole).rounded_rectangle([fx - 10, fy - 10, fx + fw + 10, fy + fh + 10], radius=14, fill=0)
                    dim.putalpha(Image.fromarray((np.asarray(hole, dtype=np.float32) * (95 * a / 255)).astype(np.uint8)))
                    frame.alpha_composite(dim)
                    od.rounded_rectangle([fx - 10, fy - 10, fx + fw + 10, fy + fh + 10], radius=14, outline=(*C["hl"], int(255 * a)), width=5)
            if pre is not None and click and t < t_switch + 0.6:
                cx, cy = click[0] + click[2] / 2, click[1] + click[3] / 2
                mt = ease_out(t / 1.1)
                sx, sy = W * 0.62 + (cx - W * 0.62) * mt, H * 0.92 + (cy - H * 0.92) * mt
                if 1.0 < t < 1.9:
                    r = (t - 1.0) / 0.9
                    rad = 12 + 46 * r
                    od.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], outline=(*C["hl"], int(230 * (1 - r))), width=5)
                if t < t_switch + 0.5:
                    draw_cursor(od, sx, sy, 1.15)
            frame.alpha_composite(ov)
            ca = min(1.0, t / 0.3, (3.8 - t) / 0.5)
            if ca > 0:
                c2 = chip.copy(); c2.putalpha(Image.fromarray((np.asarray(chip.getchannel("A"), dtype=np.float32) * ca).astype(np.uint8)))
                frame.alpha_composite(c2)
            if sub is not None:
                frame.alpha_composite(sub)
            frame.alpha_composite(progress_layer(seg["p0"] + (seg["p1"] - seg["p0"]) * i / max(n, 1)))
            arr = np.asarray(frame.convert("RGB"))
            fade = min(1.0, t / 0.25, (dur - t) / 0.25)
            if fade < 1:
                arr = (arr.astype(np.float32) * max(fade, 0)).astype(np.uint8)
            proc.stdin.write(arr.tobytes())
    proc.stdin.close()
    proc.wait()
    return out_path


def build_timeline(spec, shots, audio_dir, boxes):
    segs, t = [], 0.0
    chapter = None
    for line in spec:
        if line.get("chapter") and line["chapter"] != chapter:
            chapter = line["chapter"]
            if not line.get("card") or line["card"].get("kind") not in ("power", "restricted"):
                segs.append({"type": "card", "card": {"kind": "chapter", "title": chapter}, "dur": CHAPTER_LEN, "id": f"{line['id']}_ch", "audio": None})
        elif line.get("card", {}).get("chapter") and line["card"]["chapter"] != chapter:
            chapter = line["card"]["chapter"]
            segs.append({"type": "card", "card": {"kind": "chapter", "title": chapter}, "dur": CHAPTER_LEN, "id": f"{line['id']}_ch", "audio": None})
        wav = os.path.join(audio_dir, f"{line['id']}.wav")
        speech = wav_len(wav) if os.path.exists(wav) else max(3.0, len(line["say"]) / 7.0)
        dur = max(MIN_LEN, LEAD + speech + TAIL)
        seg = {"id": line["id"], "dur": dur, "sub": line["sub"], "audio": wav if os.path.exists(wav) else None, "speech": speech,
               "chip": chapter if not line.get("card") else None}
        if line.get("card"):
            seg.update(type="card", card=line["card"])
            if line["card"]["kind"] in ("title",):
                seg["card_sub"] = False
        else:
            b = boxes.get(line["id"], {})
            img = os.path.join(shots, f"{line['id']}.jpg")
            pre = os.path.join(shots, f"{line['id']}_pre.jpg")
            seg.update(type="shot", img=img, pre=pre if b.get("pre") and os.path.exists(pre) else None, focus=b.get("focus"), click=b.get("click"))
            if seg["pre"]:
                seg["dur"] = max(seg["dur"], 1.9 + speech + TAIL)
                seg["lead"] = 1.9
        segs.append(seg)
    total = sum(s["dur"] for s in segs)
    for s in segs:
        s["start"] = t
        s["p0"], s["p1"] = t / total, (t + s["dur"]) / total
        t += s["dur"]
    return segs, total


def mix_audio(segs, total, music_wav, out_wav):
    sr = 44100
    voice = np.zeros(int((total + 1) * sr), dtype=np.float32)
    for s in segs:
        if not s.get("audio"):
            continue
        tmp = s["audio"] + ".44k.wav"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", s["audio"], "-ac", "1", "-ar", str(sr), tmp], check=True)
        with wave.open(tmp) as w:
            a = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
        start = int((s["start"] + s.get("lead", LEAD)) * sr)
        voice[start:start + len(a)] += a[: len(voice) - start]
    peak = np.abs(voice).max() or 1
    voice = voice / peak * 0.89
    with wave.open(music_wav) as w:
        m = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32).reshape(-1, 2) / 32768
    m = m[: len(voice)]
    if len(m) < len(voice):
        m = np.vstack([m, np.zeros((len(voice) - len(m), 2), dtype=np.float32)])
    # ducking: music at -20 dB under speech, -11 dB in gaps, smooth 0.35 s
    env = (np.abs(voice) > 0.01).astype(np.float32)
    win = int(0.35 * sr)
    env = np.convolve(env, np.ones(win) / win, mode="same")
    env = np.clip(env * 3, 0, 1)
    gain = 10 ** ((-11 + (-20 + 11) * env) / 20)
    mix = m * gain[:, None] * 0.9 + voice[:, None]
    mix = np.clip(mix, -0.98, 0.98)
    with wave.open(out_wav, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((mix * 32767).astype("<i2").tobytes())


def srt_time(x):
    h, r = divmod(x, 3600); m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s - int(s)) * 1000)):03d}"


if __name__ == "__main__":
    spec_path, shots, audio_dir, out = sys.argv[1:5]
    only = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else None
    jobs = int(sys.argv[sys.argv.index("--jobs") + 1]) if "--jobs" in sys.argv else 2
    spec = json.load(open(spec_path, encoding="utf-8"))
    bx = os.path.join(shots, "boxes.json")
    boxes = json.load(open(bx, encoding="utf-8"))["lines"] if os.path.exists(bx) else {}
    os.makedirs(os.path.join(out, "seg"), exist_ok=True)
    segs, total = build_timeline(spec, shots, audio_dir, boxes)
    print(f"{len(segs)} segments, {total / 60:.1f} min", flush=True)
    todo = [{"seg": s, "out": os.path.join(out, "seg", f"{k:03d}_{s['id']}.mp4")} for k, s in enumerate(segs) if not only or s["id"] in only]
    with ProcessPoolExecutor(jobs) as ex:
        for path in ex.map(render_segment, todo):
            print("rendered", os.path.basename(path), flush=True)
    if only:
        sys.exit(0)
    with open(os.path.join(out, "concat.txt"), "w") as f:
        for k, s in enumerate(segs):
            f.write(f"file 'seg/{k:03d}_{s['id']}.mp4'\n")
    music = os.path.join(out, "music.wav")
    subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "music.py"), str(total + 1), music], check=True)
    mix_audio(segs, total, music, os.path.join(out, "mix.wav"))
    with open(os.path.join(out, "subtitles.srt"), "w", encoding="utf-8") as f:
        k = 1
        for s in segs:
            if s.get("sub") and s.get("audio"):
                a = s["start"] + s.get("lead", LEAD); b = a + s["speech"] + 0.2
                f.write(f"{k}\n{srt_time(a)} --> {srt_time(b)}\n{s['sub']}\n\n"); k += 1
    json.dump([{k2: v for k2, v in s.items() if k2 not in ("card",)} for s in segs], open(os.path.join(out, "timeline.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", os.path.join(out, "concat.txt"), "-i", os.path.join(out, "mix.wav"),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", "-shortest", "-movflags", "+faststart",
                    os.path.join(out, "video.mp4")], check=True)
    print("done", os.path.join(out, "video.mp4"))
