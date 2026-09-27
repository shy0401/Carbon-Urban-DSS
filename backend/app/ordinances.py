"""시·군 도시·군계획 조례의 용도지역별 건폐율·용적률 (법제처 국가법령정보 자치법규 DRF API).

국토계획법 제77·78조: 용도지역의 건폐율·용적률은 시행령(제84·85조) 범위에서 특별시·광역시·특별자치시·
특별자치도·시·군의 조례로 정한다. 그래서 지역마다 값이 다르고, 어느 조례를 따르는지는 다음 규칙으로 정한다.

* 특별시·광역시의 자치구와 군 → 그 특별시·광역시 조례 (광역시 관할 군은 도시·군계획을 광역시가 세움, 법 제2조 제2호)
* 세종특별자치시 → 세종특별자치시 조례, 제주시·서귀포시(행정시) → 제주특별자치도 조례
* 전남광주통합특별시의 자치구 → 통합특별시 조례(아직 없으면 옛 광주광역시 조례), 그 밖의 시·군 → 그 시·군 조례

조례 본문은 원문 XML 그대로 ``data/raw/ordinances/`` 에 두고, 용도지역 조문(건폐율·용적률)의 첫 항에서
"용도지역명 : N퍼센트" / "100분의 N" 목록을 읽는다. 단서의 공동주택·주거복합 상한과 "대지면적 N제곱미터 초과 시"
상한도 따로 읽는다. 읽은 값이 시행령 상한을 넘으면 시행령 상한을 쓰고 그 사실을 남긴다(조례는 시행령 범위 안).
"""
from __future__ import annotations

import html
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from sqlalchemy import JSON, DateTime, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

Log = Callable[[str], None]

SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"
SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"
VIEW_URL = "https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq={mst}"
USER_AGENT = "Carbon-Urban-DSS/1.0 public-data-research"
REFRESH_DAYS = 30

# 특별시·광역시: 자치구·군 모두 시 조례 (코드 앞 두 자리)
METRO_SIDO = {"11", "26", "27", "28", "29", "30", "31"}
PROVINCE_ISSUER = {"36": "세종특별자치시", "50": "제주특별자치도"}
# 통합특별시의 자치구: 통합 조례가 없으면 옛 광역시 조례를 찾는다
FALLBACK_ISSUERS = {"12": ["광주광역시"]}

ZONES = [
    "제1종전용주거지역", "제2종전용주거지역", "제1종일반주거지역", "제2종일반주거지역", "제3종일반주거지역", "준주거지역",
    "중심상업지역", "일반상업지역", "근린상업지역", "유통상업지역", "전용공업지역", "일반공업지역", "준공업지역",
    "보전녹지지역", "생산녹지지역", "자연녹지지역", "보전관리지역", "생산관리지역", "계획관리지역", "농림지역", "자연환경보전지역",
]
_ZONE_GROUPS = {
    "녹지지역": ["보전녹지지역", "생산녹지지역", "자연녹지지역"],
    "관리지역": ["보전관리지역", "생산관리지역", "계획관리지역"],
}
_EXCLUDE_TITLE = ("완화", "특례", "강화", "경관", "방화", "취락", "지구단위", "밖의", "기존", "성장관리", "산업", "기반시설",
                  "공공시설", "리모델링", "학교", "시장", "공지", "기부", "임대", "적용특례", "개발진흥", "보호지구", "특정용도")
_HOUSING = ("공동주택", "주거복합", "주거용")
_EXCLUDE_BEFORE = ("재건축은", "재개발은", "정비사업은", "재건축의경우", "재개발의경우")

_PCT = re.compile(r"100분의(\d+(?:\.\d+)?)|(\d{1,2}천\d{0,3}|천\d{1,3}|\d[\d,]*(?:\.\d+)?)(?:퍼센트|%|프로)")
_SITE_RULE = re.compile(r"대지면적(?:이)?(\d{1,2}천\d{0,3}|\d[\d,]*)(?:제곱미터|㎡|m2)(초과|이상)")
_ANNOTATIONS = [re.compile(p) for p in (
    r"<[^<>]*>", r"〈[^〈〉]*〉", r"\[[^\[\]]*\]",
    r"\((?:개정|신설|본조|종전|조제목|제목|전문|항신설|호신설|이동|삭제)[^()]*\)",
)]
_CIRCLED = "②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def now() -> datetime:
    return datetime.now(timezone.utc)


class ZoningOrdinance(Base):
    """One 조례 issuer's 용도지역 limits (a 시·군, or the 특별·광역시/특별자치시·도 for its 구·군·행정시)."""
    __tablename__ = "zoning_ordinances"
    issuer_code: Mapped[str] = mapped_column(String, primary_key=True)   # region code (시·군) or "<시도>000"
    issuer_name: Mapped[str] = mapped_column(String)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    mst: Mapped[str | None] = mapped_column(String, nullable=True)       # 자치법규일련번호
    agency: Mapped[str | None] = mapped_column(String, nullable=True)    # 지자체기관명 as law.go.kr lists it
    promulgated: Mapped[str | None] = mapped_column(String, nullable=True)
    promulgation_no: Mapped[str | None] = mapped_column(String, nullable=True)
    effective: Mapped[str | None] = mapped_column(String, nullable=True)
    articles: Mapped[dict] = mapped_column(JSON, default=dict)          # {"bcr": "제66조(…)", "far": "제70조(…)"}
    limits: Mapped[dict] = mapped_column(JSON, default=dict)            # {zone: {bcr, far, bcr_housing, far_housing, …}}
    zones_bcr: Mapped[int] = mapped_column(Integer, default=0)
    zones_far: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="NOT_COLLECTED")  # PARSED | PARTIAL | PARSE_FAILED | NOT_FOUND | ERROR
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_path: Mapped[str | None] = mapped_column(String, nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# --------------------------------------------------------------------------- which 조례 applies
def issuer_for(region_code: str, region_name: str, sido_name: str | None = None) -> dict[str, Any]:
    """The 조례 issuer of a study region: {code, name, names (search order), rule}."""
    sido = region_code[:2]
    parts = (region_name or "").split()
    sido_full = sido_name or (parts[0] if parts else region_name)
    local = parts[-1] if parts else region_name
    if sido in METRO_SIDO:
        return {"code": f"{sido}000", "name": sido_full, "names": [sido_full], "rule": "특별시·광역시의 구·군은 시 조례를 따릅니다 (국토계획법 제2조 제2호·제77·78조)"}
    if sido in PROVINCE_ISSUER:
        name = sido_full if sido_full.startswith(PROVINCE_ISSUER[sido][:2]) else PROVINCE_ISSUER[sido]
        rule = "세종특별자치시 조례" if sido == "36" else "제주시·서귀포시는 행정시이므로 제주특별자치도 조례를 따릅니다"
        return {"code": f"{sido}000", "name": name, "names": [name], "rule": rule}
    if sido in FALLBACK_ISSUERS and local.endswith("구"):
        return {"code": f"{sido}000", "name": sido_full, "names": [sido_full, *FALLBACK_ISSUERS[sido]],
                "rule": "통합특별시의 자치구는 특별시 조례를 따릅니다 (통합 조례가 없으면 옛 광역시 조례)"}
    return {"code": region_code, "name": region_name, "names": [region_name], "rule": "시·군 도시·군계획 조례"}


def _title_ok(title: str, local: str) -> bool:
    text = (title or "").replace(" ", "")
    return bool(re.fullmatch(re.escape(local.replace(" ", "")) + r"(?:도시|군|도시[·ㆍ]군)?계획조례", text))


def _same_agency(agency: str, issuer_name: str) -> bool:
    """'전남광주통합특별시 강진군' vs '전라남도 강진군': same last word and a compatible 시도."""
    from .regions import sido_keys
    a, b = (agency or "").split(), (issuer_name or "").split()
    if not a or not b:
        return False
    if len(b) == 1:  # 시도 issuer
        return len(a) == 1 and bool(set(sido_keys(a[0])) & set(sido_keys(b[0])))
    return a[-1] == b[-1] and len(a) > 1 and bool(set(sido_keys(a[0])) & set(sido_keys(b[0])))


def pick_search_hit(hits: list[dict[str, Any]], issuer_name: str, today: str | None = None) -> dict[str, Any] | None:
    """The current 조례 among law.go.kr search hits (규칙·위원회 조례 are ignored)."""
    local = issuer_name.split()[-1]
    today = today or datetime.now(timezone.utc).strftime("%Y%m%d")
    good = [h for h in hits if (h.get("kind") or "조례") == "조례" and _title_ok(h.get("title", ""), local) and _same_agency(h.get("agency", ""), issuer_name)]
    if not good:
        return None
    current = [h for h in good if (h.get("effective") or "0") <= today] or good
    return max(current, key=lambda h: (h.get("effective") or "", h.get("mst") or ""))


def _parse_search(body: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(body)
    return [{"title": x.findtext("자치법규명") or "", "mst": x.findtext("자치법규일련번호"), "agency": x.findtext("지자체기관명") or "",
             "promulgated": x.findtext("공포일자"), "effective": x.findtext("시행일자"), "kind": x.findtext("자치법규종류")} for x in root.findall("law")]


# --------------------------------------------------------------------------- parser
def _num(text: str) -> float:
    text = text.replace(",", "")
    if "천" in text:
        head, tail = text.split("천", 1)
        return float((int(head) if head else 1) * 1000 + (int(tail) if tail else 0))
    return float(text)


def _pct_value(match: re.Match[str]) -> float:
    return float(match.group(1)) if match.group(1) else _num(match.group(2))


def _clean(text: str) -> str:
    text = html.unescape(html.unescape(text or ""))
    for pattern in _ANNOTATIONS:
        text = pattern.sub("", text)
    return text


def _article_lines(jo: ET.Element) -> list[str]:
    lines: list[str] = []

    def add(value: str | None) -> None:
        lines.extend(line.strip() for line in html.unescape(value or "").splitlines() if line.strip())

    add(jo.findtext("조내용"))
    for hang in jo.findall("항"):
        add(hang.findtext("항내용"))
        for ho in hang.findall("호"):
            add(ho.findtext("호내용"))
            for mok in ho.findall("목"):
                add(mok.findtext("목내용"))
    for ho in jo.findall("호"):
        add(ho.findtext("호내용"))
        for mok in ho.findall("목"):
            add(mok.findtext("목내용"))
    return lines


def _first_paragraph(lines: list[str]) -> list[str]:
    """Lines of ① (the base limits); ② and later are exceptions or relaxations."""
    out = []
    for index, line in enumerate(lines):
        if index and line[:1] in _CIRCLED:
            break
        out.append(line)
    return out


def _items(lines: list[str]) -> list[str]:
    """'N. …' items of a paragraph, each with its 목 (가. 나. …) and continuation lines."""
    items: list[str] = []
    current: list[str] | None = None
    for line in lines:
        if re.match(r"^\d{1,2}\s*\.\s*\S", line) and not re.match(r"^\d{4}\s*\.", line):
            if current is not None:
                items.append(" ".join(current))
            current = [re.sub(r"^\d{1,2}\s*\.\s*", "", line)]
        elif current is not None:
            current.append(line)
    if current is not None:
        items.append(" ".join(current))
    if not items and lines:  # everything on one line: "… 같다. 1. 제1종전용주거지역: 50퍼센트 2. …"
        joined = " ".join(lines)
        parts = re.split(r"(?:(?<=\s)|^)\d{1,2}\s*\.\s+(?=(?:제\d종|준|중심|일반|근린|유통|전용|보전|생산|자연|계획|농림))", joined)
        items = [p for p in parts[1:] if p.strip()]
    return items


def _zones_in_head(head: str) -> list[str]:
    found = [z for z in sorted(ZONES, key=len, reverse=True) if z in head]
    # "제1종전용주거지역" contains no other zone name, but "자연녹지지역" must not also claim "녹지지역" groups
    zones = [z for z in ZONES if z in found]
    if not zones:
        for group, members in _ZONE_GROUPS.items():
            if head.startswith(group):
                return list(members)
    return zones


def _housing_value(item: str, head_end: int, main: float) -> float | None:
    """Lowest limit the 단서 gives to 공동주택·주거복합 (None when the item has no such 단서)."""
    if not any(word in item for word in _HOUSING):
        return None
    candidates = []
    matches = list(_PCT.finditer(item, head_end))
    previous_end = head_end
    for match in matches:
        window = item[previous_end:match.start()]
        previous_end = match.end()
        if any(word in window[-12:] for word in _EXCLUDE_BEFORE):
            continue
        if any(word in window for word in _HOUSING):
            candidates.append(_pct_value(match))
    # "(다만, 각 목의 어느 하나에 해당하는 경우 500퍼센트 이하로 한다) 가. 공동주택 …"
    each = re.search(r"각목의?(?:어느하나에)?해당하는경우(?:에는)?", item)
    if each:
        after = _PCT.search(item, each.end())
        if after and after.start() - each.end() < 8:
            candidates.append(_pct_value(after))
    values = [v for v in candidates if 0 < v <= main]
    return min(values) if values else None


def _site_rules(item: str, head_end: int, main: float) -> list[dict[str, Any]]:
    """'(단, 대지면적 1천제곱미터 초과 시 200퍼센트 이하)' → [{"min_site_m2": 1000, "inclusive": False, "value": 200}]."""
    rules = []
    for match in _SITE_RULE.finditer(item, head_end):
        after = _PCT.search(item, match.end())
        if after and after.start() - match.end() < 12:
            value = _pct_value(after)
            if 0 < value < main:
                rules.append({"min_site_m2": _num(match.group(1)), "inclusive": match.group(2) == "이상", "value": value})
    return rules


def parse_limit_items(lines: list[str]) -> dict[str, dict[str, Any]]:
    """{zone: {value, housing, site_rules, text}} from the first paragraph of a 건폐율/용적률 article."""
    out: dict[str, dict[str, Any]] = {}
    for raw in _items(_first_paragraph(lines)):
        item = re.sub(r"\s+", "", _clean(raw))
        first = _PCT.search(item)
        if not first:
            continue
        colon = re.search(r"[:：]", item)
        head_end = colon.start() if colon and colon.start() < first.start() else first.start()
        head = item[:head_end]
        zones = _zones_in_head(head)
        if not zones or len(head) > 60:  # an exception clause that only mentions zones
            continue
        main = _pct_value(first)
        tail = item[first.end():]
        info = {"value": main, "housing": _housing_value(item, head_end, main), "site_rules": _site_rules(item, head_end, main),
                "text": re.sub(r"\s+", " ", _clean(raw)).strip()[:400], "proviso": bool(re.search(r"다만|단[,，]|\(", tail))}
        for zone in zones:
            out.setdefault(zone, info)
    return out


def _article_label(jo: ET.Element) -> str:
    """조문번호 "006600" = 제66조, "001202" = 제12조의2."""
    raw = (jo.findtext("조문번호") or "").strip()
    title = jo.findtext("조제목") or ""
    if raw.isdigit() and len(raw) == 6:
        number, branch = int(raw[:4]), int(raw[4:])
        return f"제{number}조{'의' + str(branch) if branch else ''}({title})"
    return f"제{raw.lstrip('0')}조({title})"


def _candidate_articles(root: ET.Element, word: str) -> list[ET.Element]:
    found = []
    for jo in (root.find("조문") or []):
        if (jo.findtext("조문여부") or "Y") not in ("Y", ""):
            continue
        title = (jo.findtext("조제목") or "").replace(" ", "")
        if word in title and not any(x in title for x in _EXCLUDE_TITLE):
            found.append(jo)
    return found


def _table_lines(root: ET.Element, word: str) -> list[str]:
    lines: list[str] = []
    for unit in (root.find("별표") or []):
        if word in (unit.findtext("별표제목") or ""):
            lines.extend(line.strip() for line in html.unescape(unit.findtext("별표내용") or "").splitlines() if line.strip())
    return lines


def _best(root: ET.Element, word: str) -> tuple[str | None, dict[str, dict[str, Any]]]:
    best: tuple[str | None, dict[str, dict[str, Any]]] = (None, {})
    for jo in _candidate_articles(root, word):
        parsed = parse_limit_items(_article_lines(jo))
        if len(parsed) > len(best[1]):
            best = (_article_label(jo), parsed)
    if not best[1]:
        parsed = _table_zone_scan(_table_lines(root, word))
        if parsed:
            best = (f"별표({word})", parsed)
    return best


def _table_zone_scan(lines: list[str]) -> dict[str, dict[str, Any]]:
    """별표 text: a zone name followed closely by a percentage."""
    out: dict[str, dict[str, Any]] = {}
    text = re.sub(r"\s+", "", _clean(" ".join(lines)))
    for zone in sorted(ZONES, key=len, reverse=True):
        for match in re.finditer(re.escape(zone), text):
            if zone in out:
                break
            pct = _PCT.search(text, match.end())
            if pct and pct.start() - match.end() <= 6:
                out[zone] = {"value": _pct_value(pct), "housing": None, "site_rules": [], "text": text[match.start():pct.end()], "proviso": False}
    return out


def parse_ordinance(body: bytes) -> dict[str, Any]:
    """Meta and per-zone 건폐율·용적률 of one 도시·군계획 조례 XML (law.go.kr lawService, target=ordin)."""
    from .zoning_limits import DECREE_LIMITS
    root = ET.fromstring(body)
    info = root.find("자치법규기본정보")

    def meta(tag: str) -> str | None:
        return (info.findtext(tag) or None) if info is not None else None

    def date(value: str | None) -> str | None:
        return f"{value[:4]}-{value[4:6]}-{value[6:8]}" if value and len(value) == 8 else value

    bcr_article, bcr = _best(root, "건폐율")
    far_article, far = _best(root, "용적률")
    limits: dict[str, dict[str, Any]] = {}
    issues = []
    for zone in ZONES:
        decree_bcr, decree_far = DECREE_LIMITS[zone]
        entry: dict[str, Any] = {}
        for key, parsed, bound in (("bcr", bcr.get(zone), decree_bcr), ("far", far.get(zone), decree_far)):
            if not parsed:
                continue
            value = parsed["value"]
            if value < 5:  # "100분의 N" misread or a clause about something else
                issues.append(f"{zone} {key} {value}% 무시")
                continue
            entry[key] = value
            entry[f"{key}_housing"] = parsed["housing"] if parsed["housing"] is not None else value
            entry[f"{key}_text"] = parsed["text"]
            if parsed["site_rules"]:
                entry[f"{key}_site_rules"] = parsed["site_rules"]
            if value > bound:
                entry[f"{key}_over_decree"] = True
                issues.append(f"{zone} {key} {value:g}% > 시행령 {bound:g}%")
        if entry:
            limits[zone] = entry
    zones_bcr = sum(1 for e in limits.values() if "bcr" in e)
    zones_far = sum(1 for e in limits.values() if "far" in e)
    if zones_bcr and zones_far:
        status = "PARSED" if zones_bcr >= 13 and zones_far >= 13 else "PARTIAL"
    else:
        status = "PARSE_FAILED"
    return {"title": meta("자치법규명"), "mst": meta("자치법규일련번호"), "agency": meta("지자체기관명"),
            "promulgated": date(meta("공포일자")), "promulgation_no": meta("공포번호"), "effective": date(meta("시행일자")),
            "articles": {"bcr": bcr_article, "far": far_article}, "limits": limits, "zones_bcr": zones_bcr, "zones_far": zones_far,
            "status": status, "issues": issues}


# --------------------------------------------------------------------------- collection
def _root_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "data"))


def _oc() -> str:
    return os.getenv("LAW_GO_KR_OC", "test").strip() or "test"


def issuers(db: Any, region_codes: Iterable[str] | None = None) -> dict[str, dict[str, Any]]:
    """Issuer → {issuer…, regions: [codes]} for the given regions (default: every region in the catalog)."""
    from .regions import catalog
    wanted = set(region_codes) if region_codes else None
    out: dict[str, dict[str, Any]] = {}
    for region in catalog(db):
        if wanted is not None and region["code"] not in wanted:
            continue
        issuer = issuer_for(region["code"], region["name"], region.get("sido_name"))
        out.setdefault(issuer["code"], dict(issuer, regions=[]))["regions"].append(region["code"])
    return out


def collect_ordinance(db: Any, client: Any, issuer: dict[str, Any], *, log: Log = print, delay_s: float = 0.4) -> ZoningOrdinance:
    """Find, download and parse one issuer's 도시·군계획 조례 (raw XML kept under data/raw/ordinances)."""
    row = db.get(ZoningOrdinance, issuer["code"]) or ZoningOrdinance(issuer_code=issuer["code"], issuer_name=issuer["name"])
    row.issuer_name = issuer["name"]
    row.checked_at = now()
    hit = None
    try:
        for name in issuer["names"]:
            local = name.split()[-1]
            for query in (f"{local} 도시계획 조례", f"{local} 계획 조례"):
                response = client.get(SEARCH_URL, params={"OC": _oc(), "target": "ordin", "type": "XML", "query": query, "display": 100})
                response.raise_for_status()
                hit = pick_search_hit(_parse_search(response.content), name)
                time.sleep(delay_s)
                if hit:
                    break
            if hit:
                break
        if not hit:
            row.status, row.message = "NOT_FOUND", f"law.go.kr에서 '{issuer['name']}' 도시·군계획 조례를 찾지 못했습니다"
            db.add(row)
            db.commit()
            log(f"{issuer['name']}: 조례 못 찾음")
            return row
        response = client.get(SERVICE_URL, params={"OC": _oc(), "target": "ordin", "MST": hit["mst"], "type": "XML"})
        response.raise_for_status()
        time.sleep(delay_s)
        raw_dir = _root_dir() / "raw" / "ordinances"
        raw_dir.mkdir(parents=True, exist_ok=True)
        path = raw_dir / f"{issuer['code']}-{hit['mst']}.xml"
        path.write_bytes(response.content)
        parsed = parse_ordinance(response.content)
    except Exception as exc:  # noqa: BLE001 - one issuer must not stop the national run
        db.rollback()
        row = db.get(ZoningOrdinance, issuer["code"]) or ZoningOrdinance(issuer_code=issuer["code"], issuer_name=issuer["name"])
        row.checked_at, row.status, row.message = now(), "ERROR", f"{type(exc).__name__}: {str(exc)[:300]}"
        db.add(row)
        db.commit()
        log(f"{issuer['name']}: 오류 {row.message}")
        return row
    for field in ("title", "mst", "agency", "promulgated", "promulgation_no", "effective", "articles", "limits", "zones_bcr", "zones_far", "status"):
        setattr(row, field, parsed[field])
    row.raw_path = str(path)
    row.message = "; ".join(parsed["issues"]) or None
    db.add(row)
    db.commit()
    log(f"{issuer['name']}: {parsed['title']} ({parsed['effective']}) 건폐율 {parsed['zones_bcr']}·용적률 {parsed['zones_far']}개 용도지역 [{parsed['status']}]")
    return row


def collect_ordinances(db: Any, region_codes: Iterable[str] | None = None, *, force: bool = False, log: Log = print,
                       delay_s: float = 0.4) -> dict[str, Any]:
    """조례 for the issuers of the given regions (default: all). Recently checked issuers are skipped unless ``force``."""
    import httpx

    from .national import _source
    from .settings import offline_mode
    if offline_mode():
        raise RuntimeError("오프라인 모드: 조례를 받지 않습니다")
    _source(db, "zoning_ordinances", "시·군 도시·군계획 조례 (용도지역 건폐율·용적률)", "법제처 국가법령정보센터", "https://www.law.go.kr", "규제")
    db.commit()
    targets = issuers(db, region_codes)
    counts: dict[str, int] = {}
    client = httpx.Client(timeout=40, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    try:
        for index, issuer in enumerate(targets.values(), 1):
            existing = db.get(ZoningOrdinance, issuer["code"])
            fresh = existing and existing.checked_at and existing.status in ("PARSED", "PARTIAL") and \
                (now() - (existing.checked_at if existing.checked_at.tzinfo else existing.checked_at.replace(tzinfo=timezone.utc))).days < REFRESH_DAYS
            if fresh and not force:
                counts[existing.status] = counts.get(existing.status, 0) + 1
                continue
            row = collect_ordinance(db, client, issuer, log=lambda m, i=index: log(f"[{i}/{len(targets)}] {m}"), delay_s=delay_s)
            counts[row.status] = counts.get(row.status, 0) + 1
    finally:
        client.close()
    from .collectors import update_source
    usable = counts.get("PARSED", 0) + counts.get("PARTIAL", 0)
    update_source(db, "zoning_ordinances", usable, len(targets),
                  quality=f"조례 {len(targets)}곳 중 용도지역 상한을 읽은 곳 {usable} (" + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) + ")",
                  missing=len(targets) - usable)
    return {"issuers": len(targets), "counts": counts}


# --------------------------------------------------------------------------- lookup
def ordinance_for_region(db: Any, region_code: str) -> dict[str, Any] | None:
    """The 조례 that applies to a region: {issuer, status, row} (row None when not collected)."""
    from .regions import catalog_entry
    entry = catalog_entry(db, region_code)
    if not entry:
        return None
    issuer = issuer_for(region_code, entry["name"], entry.get("sido_name"))
    try:
        row = db.get(ZoningOrdinance, issuer["code"])
    except Exception:  # noqa: BLE001 - table not created yet
        db.rollback()
        row = None
    result: dict[str, Any] = {"issuer": issuer, "status": row.status if row else "NOT_COLLECTED", "row": None}
    if row is not None:
        result["row"] = {"title": row.title, "mst": row.mst, "agency": row.agency, "promulgated": row.promulgated,
                         "promulgation_no": row.promulgation_no, "effective": row.effective, "articles": row.articles or {},
                         "limits": row.limits or {}, "zones_bcr": row.zones_bcr, "zones_far": row.zones_far,
                         "status": row.status, "message": row.message,
                         "checked": row.checked_at.date().isoformat() if row.checked_at else None,
                         "url": VIEW_URL.format(mst=row.mst) if row.mst else None}
    return result


def ordinance_summary(db: Any) -> dict[str, Any]:
    """Counts per status for the national page."""
    try:
        rows = list(db.scalars(select(ZoningOrdinance)))
    except Exception:  # noqa: BLE001
        db.rollback()
        return {"issuers": 0, "counts": {}}
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return {"issuers": len(rows), "counts": counts}
