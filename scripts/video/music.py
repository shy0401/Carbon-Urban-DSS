"""배경음악 직접 합성(저작권 걱정 없는 원곡). 부드러운 패드 + 전자피아노 아르페지오 + 낮은 베이스 + 아주 옅은 리듬.

usage: python music.py <seconds> <out.wav>
- 84 BPM, F장조 IV–V–iii–vi 진행 (Fmaj7 · G6 · Em7 · Am7 → Dm9 · G · Cmaj7 · Am7 변주)
- 사인·삼각파 위주로 귀가 편하게, 저역 통과, 합성 잔향. 나레이션 밑에 깔릴 것이라 중역(1~4 kHz)을 비운다.
"""
import sys

import numpy as np
from scipy.signal import butter, fftconvolve, sosfilt

SR = 44100
BPM = 84
BEAT = 60 / BPM
BAR = 4 * BEAT
rng = np.random.default_rng(7)


def midi(n):
    return 440.0 * 2 ** ((n - 69) / 12)


# 화음(미디 번호). A: 기본 진행, B: 변주
A = [[53, 57, 60, 64], [55, 59, 62, 64], [52, 55, 59, 62], [57, 60, 64, 67]]
B = [[50, 53, 57, 60, 64], [55, 59, 62, 65], [48, 52, 55, 59], [57, 60, 64, 67]]
ROOT_A = [41, 43, 40, 45]
ROOT_B = [38, 43, 36, 45]


def env_adsr(n, a, d, s, r, sr=SR):
    a, d, r = int(a * sr), int(d * sr), int(r * sr)
    e = np.ones(n) * s
    a = min(a, n)
    e[:a] = np.linspace(0, 1, a, endpoint=False)
    dd = min(d, max(n - a, 0))
    e[a:a + dd] = np.linspace(1, s, dd, endpoint=False)
    if r > 0 and n > r:
        e[-r:] *= np.linspace(1, 0, r)
    return e


def pad_note(f, dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    sig = np.zeros(n)
    for det in (-0.12, 0.0, 0.11):          # 살짝 어긋난 세 소리 → 넓은 패드
        ff = f * 2 ** (det / 12)
        sig += np.sin(2 * np.pi * ff * t) + 0.18 * np.sin(2 * np.pi * 2 * ff * t) + 0.06 * np.sin(2 * np.pi * 3 * ff * t)
    trem = 1 + 0.06 * np.sin(2 * np.pi * 0.25 * t)
    return sig * trem * env_adsr(n, 1.2, 0.8, 0.85, 1.4) / 3


def epiano(f, dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    mod = 0.9 * np.exp(-t * 6) * np.sin(2 * np.pi * f * 2 * t)     # 짧은 FM으로 종소리 같은 머리
    sig = np.sin(2 * np.pi * f * t + mod) + 0.25 * np.sin(2 * np.pi * f * 2 * t) * np.exp(-t * 3)
    return sig * np.exp(-t * 2.2) * env_adsr(n, 0.004, 0.05, 1.0, 0.25)


def bass(f, dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    sig = np.sin(2 * np.pi * f * t) + 0.12 * np.sin(2 * np.pi * 2 * f * t)
    return sig * env_adsr(n, 0.02, 0.3, 0.7, 0.3)


def kick(dur=0.35):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 55 + 70 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)


def shaker(dur=0.09):
    n = int(dur * SR)
    noise = rng.standard_normal(n)
    sos = butter(4, [5000, 11000], btype="band", fs=SR, output="sos")
    return sosfilt(sos, noise) * np.exp(-np.arange(n) / SR * 45)


def add(buf, sig, start, pan=0.0, gain=1.0):
    s = int(start * SR)
    if s >= buf.shape[1]:
        return
    sig = sig[: buf.shape[1] - s]
    l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    buf[0, s:s + len(sig)] += sig * gain * l
    buf[1, s:s + len(sig)] += sig * gain * r


def reverb(buf, seconds=2.6, wet=0.28):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    out = np.zeros_like(buf)
    for ch in range(2):
        ir = rng.standard_normal(n) * np.exp(-t * 3.2)
        ir = sosfilt(butter(2, 5500, fs=SR, output="sos"), ir)
        ir /= np.sqrt((ir ** 2).sum())
        out[ch] = fftconvolve(buf[ch], ir)[: buf.shape[1]]
    return buf * (1 - wet) + out * wet


def compose(total):
    bars = int(np.ceil(total / BAR)) + 2
    buf = np.zeros((2, int((bars * BAR + 4) * SR)))
    for b in range(bars):
        section = (b // 8) % 4                  # 8마디마다: 0 패드만, 1 +아르페지오, 2 +베이스·리듬, 3 변주(B)
        chords, roots = (B, ROOT_B) if section == 3 else (A, ROOT_A)
        ch, root = chords[b % 4], roots[b % 4]
        t0 = b * BAR
        for k, n in enumerate(ch):
            add(buf, pad_note(midi(n), BAR + 1.2), t0, pan=(-0.5 + k / max(len(ch) - 1, 1)), gain=0.10)
        if b < 2 or b >= bars - 3:
            continue                            # 시작·끝은 패드만
        if section >= 1:
            pattern = [0, 2, 1, 3, 2, 1, 3, 2]  # 8분음표 아르페지오, 한 옥타브 위
            for i, idx in enumerate(pattern):
                note = ch[idx % len(ch)] + 12
                vel = 0.10 if i % 2 == 0 else 0.07
                add(buf, epiano(midi(note), BEAT * 1.5), t0 + i * BEAT / 2, pan=0.25 * np.sin(i), gain=vel)
        if section >= 2:
            add(buf, bass(midi(root), BEAT * 1.8), t0, gain=0.20)
            add(buf, bass(midi(root), BEAT * 0.9), t0 + 2.5 * BEAT, gain=0.14)
            for beat in (0, 2):
                add(buf, kick(), t0 + beat * BEAT, gain=0.20)
            for i in range(8):
                add(buf, shaker(), t0 + i * BEAT / 2, pan=0.3, gain=0.035 if i % 2 else 0.02)
    buf = reverb(buf)
    # 나레이션 자리(1~4 kHz)를 3 dB쯤 비우고, 아주 낮은 소리는 걷어 냄
    hp = butter(2, 45, btype="high", fs=SR, output="sos")
    lp = butter(2, 9000, fs=SR, output="sos")
    mid = butter(2, [1000, 4000], btype="band", fs=SR, output="sos")
    for c in range(2):
        x = sosfilt(hp, buf[c])
        x = sosfilt(lp, x)
        buf[c] = x - 0.3 * sosfilt(mid, x)
    n = int(total * SR)
    buf = buf[:, :n]
    fade_in, fade_out = int(3 * SR), int(6 * SR)
    buf[:, :fade_in] *= np.linspace(0, 1, fade_in)
    buf[:, -fade_out:] *= np.linspace(1, 0, fade_out)
    peak = np.abs(buf).max()
    return buf / peak * 0.85


if __name__ == "__main__":
    seconds, out = float(sys.argv[1]), sys.argv[2]
    audio = compose(seconds)
    import wave
    data = (audio.T * 32767).astype("<i2").tobytes()
    with wave.open(out, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(data)
    print("wrote", out, seconds, "s")
