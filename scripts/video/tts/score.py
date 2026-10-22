"""Whisper 받아쓰기와 대본 비교 점수(숫자·영문 표기 차이는 읽는 소리로 맞춤)."""
import difflib
import re

DIG = "영일이삼사오육칠팔구"


def sino(n: int) -> str:
    if n == 0:
        return "영"
    out = ""
    for unit, name in ((10**8, "억"), (10**4, "만"), (1000, "천"), (100, "백"), (10, "십")):
        q, n = divmod(n, unit)
        if q:
            out += ("" if (q == 1 and unit < 10**4) else sino(q) if unit >= 10**4 else DIG[q]) + name
    if n:
        out += DIG[n]
    return out


WORDS = {"DSS": "디에스에스", "DS": "디에스", "AI": "에이아이", "GitHub": "깃허브", "CSV": "씨에스브이", "SGIS": "에스지아이에스",
         "K-apt": "케이아파트", "KMA": "케이엠에이", "PDF": "피디에프", "m²": "제곱미터", "km": "킬로미터"}


def speak(s: str) -> str:
    for k, v in WORDS.items():
        s = s.replace(k, v)
    s = re.sub(r"(\d+)\s*m\b", lambda m: m.group(1) + "미터", s)
    s = re.sub(r"\d[\d,]*", lambda m: sino(int(m.group(0).replace(",", ""))), s)
    return re.sub(r"[\s\.,·!?~\-'\"()%:]", "", s)


def score(text: str, heard: str) -> float:
    return difflib.SequenceMatcher(None, speak(text), speak(heard)).ratio()
