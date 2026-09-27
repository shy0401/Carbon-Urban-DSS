"""용도지역별 건폐율·용적률 상한과 계획 대지의 1차 적합성 확인 (전국, 지역마다 다른 조례).

적용 규칙 (지역마다, 용도지역마다 같은 순서):

1. 그 지역에 적용되는 도시·군계획 조례의 값. 전주시(최초 연구 지역)는 원문과 대조한 표(``LIMITS``)이고,
   그 밖의 지역은 ``ordinances.py``가 법제처 국가법령정보(law.go.kr)에서 받아 읽은 값입니다.
   특별시·광역시의 구·군은 시 조례, 제주시·서귀포시는 제주특별자치도 조례를 따릅니다.
2. 조례를 받지 못했거나 조례에 그 용도지역 값이 없으면 국토계획법 시행령 제84조(건폐율)·제85조(용적률) 상한
   (전국 공통). 조례 값이 시행령 상한을 넘으면 시행령 상한을 씁니다(조례는 시행령 범위 안).
3. 용도지역이 세분되지 않은 땅은 국토계획법 제79조: 도시지역 → 보전녹지지역(시행령 제86조), 관리지역 →
   보전관리지역, 용도지역 미지정 → 자연환경보전지역. 주거·상업·공업·녹지지역이 더 나뉘지 않았으면 같은
   지역 중 상한이 가장 낮은 세분을 씁니다(가정). 대지 일부에 용도지역 자료가 없으면 그 부분도 제79조
   제1항대로 자연환경보전지역 기준을 가정합니다. 가정한 부분은 결과에 따로 표시합니다.
4. 개발제한구역(개발제한구역법 제12조: 건축 원칙적 금지)과 지구단위계획구역(계획이 정한 건폐율·용적률이
   우선)은 대지와 겹치는지 표시하고 판정 문구에 반영합니다.

완화 규정, 경관지구 제한은 반영하지 않으므로 결과는 인허가 판단이 아니라 1차 확인입니다.
"""
from __future__ import annotations

import math
from typing import Any

ORDINANCE = {
    "name": "전주시 도시계획 조례",
    "number": "전북특별자치도전주시조례 제4369호",
    "effective": "2026-04-13",
    "articles": "제45조 제1항(건폐율), 제47조 제1항(용적률)",
    "url": "https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq=2122435",
    "checked": "2026-09-27",
    "decree": "국토의 계획 및 이용에 관한 법률 시행령 제84조·제85조(대통령령 제36587호, 2026-09-18 시행)",
}

# 용도지역 → (건폐율 %, 용적률 %, 공동주택·주거복합 용적률 %, 참고)
# 공동주택 칸: 조례 단서가 주거복합건축물·오피스텔(상업지역) 또는 공동주택(준공업지역)에 낮은 상한을 둔 경우 그 값.
LIMITS: dict[str, tuple[float | None, float | None, float | None, str | None]] = {
    "제1종전용주거지역": (40, 100, 100, None),
    "제2종전용주거지역": (40, 100, 100, None),
    "제1종일반주거지역": (60, 200, 200, None),
    "제2종일반주거지역": (60, 250, 250, None),
    "제3종일반주거지역": (50, 300, 300, None),
    "준주거지역": (60, 500, 500, None),
    "중심상업지역": (80, 1100, 700, "주거복합건축물·오피스텔은 용적률 700%"),
    "일반상업지역": (70, 900, 600, "주거복합건축물·오피스텔은 용적률 600%"),
    "근린상업지역": (60, 700, 500, "주거복합건축물·오피스텔은 용적률 500%"),
    "유통상업지역": (60, 700, None, "오피스텔 400%. 공동주택 가능 여부는 건축 제한을 따로 확인해야 합니다"),
    "전용공업지역": (60, 300, None, "공동주택 가능 여부는 건축 제한을 따로 확인해야 합니다"),
    "일반공업지역": (60, 350, None, "공동주택 가능 여부는 건축 제한을 따로 확인해야 합니다"),
    "준공업지역": (60, 400, 200, "공동주택은 용적률 200%"),
    "보전녹지지역": (20, 50, 50, None),
    "생산녹지지역": (20, 100, 100, None),
    "자연녹지지역": (20, 100, 100, None),
    "보전관리지역": (20, 50, 50, None),
    "생산관리지역": (20, 80, 80, None),
    "계획관리지역": (40, 100, 100, "성장관리계획구역은 125% 이하에서 완화 가능"),
    "농림지역": (20, 80, 80, None),
    "자연환경보전지역": (None, None, None, "조례에 규정 없음(시행령 상한 건폐율 20%·용적률 80%)"),
}

# 국토계획법 시행령 제84조 제1항(건폐율 상한)·제85조 제1항(용적률 범위의 상한). law.go.kr 조문정보에서
# 2026-09-27 확인 (제84조 2026-09-08 시행 대통령령 제36656호, 제85조 2026-09-18 시행).
DECREE = {
    "name": "국토의 계획 및 이용에 관한 법률 시행령",
    "articles": "제84조 제1항(건폐율), 제85조 제1항(용적률 범위의 상한)",
    "url": "https://www.law.go.kr/LSW/lsLawLinkInfo.do?lsJoLnkSeq=1000616219&chrClsCd=010202",
    "url_far": "https://www.law.go.kr/LSW/lsLawLinkInfo.do?chrClsCd=010202&lsJoLnkSeq=1000616250",
    "checked": "2026-09-27",
}
DECREE_LIMITS: dict[str, tuple[float, float]] = {
    "제1종전용주거지역": (50, 100), "제2종전용주거지역": (50, 150), "제1종일반주거지역": (60, 200),
    "제2종일반주거지역": (60, 250), "제3종일반주거지역": (50, 300), "준주거지역": (70, 500),
    "중심상업지역": (90, 1500), "일반상업지역": (80, 1300), "근린상업지역": (70, 900), "유통상업지역": (80, 1100),
    "전용공업지역": (70, 300), "일반공업지역": (70, 350), "준공업지역": (70, 400),
    "보전녹지지역": (20, 80), "생산녹지지역": (20, 100), "자연녹지지역": (20, 100),
    "보전관리지역": (20, 80), "생산관리지역": (20, 80), "계획관리지역": (40, 100),
    "농림지역": (20, 80), "자연환경보전지역": (20, 80),
}
DECREE_RULES = [
    "이 지역의 시·군 도시계획 조례를 아직 등록하지 않아 국토계획법 시행령 제84조(건폐율)·제85조(용적률 범위의 상한)를 씁니다.",
    "조례는 시행령 범위 안에서 더 낮게 정합니다. 시행령 상한 초과는 조례로도 초과이지만, 이내라도 조례 상한은 더 낮을 수 있습니다.",
    "여러 용도지역에 걸친 대지는 부분 면적으로 가중한 상한을 보여 줍니다.",
    "1차 확인이며 인허가 판단이 아닙니다.",
]

RULES = [
    "전주시 도시계획 조례 제45조·제47조의 기본 상한입니다. 완화 규정(제46·48조)과 경관지구 제한은 반영하지 않았습니다.",
    "대지 1만㎡ 이상 또는 300세대 이상 공동주택은 지구단위계획구역 지정 대상(조례 제12조 제3항)이며, 용적률은 전주시 지구단위계획수립지침을 따릅니다(제47조 제2항).",
    "여러 용도지역에 걸친 대지는 부분 면적으로 가중한 상한을 보여 줍니다(국토계획법 제84조 적용 여부는 대지 조건에 따라 확인).",
    "1차 확인이며 인허가 판단이 아닙니다.",
]

SITE_AREA_DISTRICT_PLAN_M2 = 10_000
HOUSEHOLDS_DISTRICT_PLAN = 300
ASSUMED_GAP_THRESHOLD = 0.05   # 대지의 5% 이상이 용도지역 자료 밖이면 그 부분을 제79조 제1항으로 가정
ZONES = list(DECREE_LIMITS)
# 시행령 별표(용도지역 안에서 건축할 수 있는 건축물): 공동주택을 지을 수 없거나 따로 확인해야 하는 곳
HOUSING_RESTRICTED = {"유통상업지역", "전용공업지역", "일반공업지역"}
HOUSING_RESTRICTED_NOTE = "공동주택은 이 용도지역에서 건축 제한 대상이라 허용 여부를 따로 확인해야 합니다"
UNDIVIDED = {
    "도시지역": ("보전녹지지역", "세부 용도지역이 없는 도시지역 → 국토계획법 제79조 제2항·시행령 제86조에 따라 보전녹지지역 기준"),
    "관리지역": ("보전관리지역", "세부 용도지역이 없는 관리지역 → 국토계획법 제79조 제2항에 따라 보전관리지역 기준"),
}
CLASS_MEMBERS = {
    "주거지역": ZONES[0:6], "상업지역": ZONES[6:10], "공업지역": ZONES[10:13], "녹지지역": ZONES[13:16],
}
GAP_NOTE = "용도지역 자료가 없는 부분 → 국토계획법 제79조 제1항(용도지역 미지정 = 자연환경보전지역) 기준 (가정)"
ORDINANCE_RULES = [
    "{name} {articles}의 기본 상한입니다. law.go.kr 원문에서 읽은 값이며({checked} 확인), 완화·강화 조항과 경관지구 제한은 반영하지 않았습니다.",
    "조례에 값이 없는 용도지역은 국토계획법 시행령 제84조·제85조 상한을 씁니다.",
    "세부 용도지역이 없는 땅은 국토계획법 제79조(도시지역 → 보전녹지, 관리지역 → 보전관리, 미지정 → 자연환경보전) 기준입니다.",
    "여러 용도지역에 걸친 대지는 부분 면적으로 가중한 상한을 보여 줍니다.",
    "1차 확인이며 인허가 판단이 아닙니다.",
]
DECREE_REASON = {
    "NOT_COLLECTED": "이 지역의 시·군 도시계획 조례를 아직 받지 않아",
    "NOT_FOUND": "law.go.kr에서 이 지역 도시·군계획 조례를 찾지 못해",
    "PARSE_FAILED": "조례 본문에서 용도지역 상한을 읽지 못해",
    "ERROR": "조례를 받는 중 오류가 나서",
}


def normalize_zone(name: str | None) -> str | None:
    """VWorld 이름("제2종일반주거지역")을 표의 키로 맞춘다. 모르는 이름은 None."""
    text = str(name or "").replace(" ", "")
    if not text:
        return None
    if not text.endswith("지역"):
        text += "지역"
    return text if text in DECREE_LIMITS else None


# --------------------------------------------------------------------------- which table applies
def _jeonju_rules() -> dict[str, Any]:
    from .regions import DEFAULT_REGION
    table = {zone: {"bcr": bcr, "far": far, "bcr_housing": bcr, "far_housing": far_housing, "note": note}
             for zone, (bcr, far, far_housing, note) in LIMITS.items() if bcr is not None}
    return {"region": DEFAULT_REGION, "kind": "ORDINANCE", "status": "VERIFIED", "table": table, "source": ORDINANCE, "rules": RULES}


def _decree_rules(region: str | None = None, status: str = "NOT_COLLECTED", issuer: dict[str, Any] | None = None) -> dict[str, Any]:
    reason = DECREE_REASON.get(status, DECREE_REASON["NOT_COLLECTED"])
    rules = [f"{reason} 국토계획법 시행령 제84조(건폐율)·제85조(용적률 범위의 상한)를 씁니다 (전국 공통 규정).", *DECREE_RULES[1:]]
    if issuer:
        rules.insert(1, f"이 지역에 적용되는 조례: {issuer['name']} 도시·군계획 조례 ({issuer['rule']}).")
    return {"region": region, "kind": "DECREE", "status": status, "table": {}, "source": DECREE, "rules": rules, "issuer": issuer}


JEONJU_RULES: dict[str, Any] | None = None


def region_rules(db: Any, region_code: str | None) -> dict[str, Any]:
    """The limits that apply in a region: the 조례 table when it could be read, else the 시행령 (per zone and field)."""
    global JEONJU_RULES
    from .regions import DEFAULT_REGION
    code = region_code or DEFAULT_REGION
    if code == DEFAULT_REGION:
        JEONJU_RULES = JEONJU_RULES or _jeonju_rules()
        return JEONJU_RULES
    from .ordinances import ordinance_for_region
    try:
        info = ordinance_for_region(db, code)
    except Exception:  # noqa: BLE001 - no catalog / table (tests)
        info = None
    row = (info or {}).get("row")
    issuer = (info or {}).get("issuer")
    if not row or row.get("status") not in ("PARSED", "PARTIAL"):
        return _decree_rules(code, (info or {}).get("status") or "NOT_COLLECTED", issuer)
    table = {}
    for zone, entry in (row.get("limits") or {}).items():
        if zone not in DECREE_LIMITS:
            continue
        item: dict[str, Any] = {}
        for key in ("bcr", "far"):
            if key in entry and not entry.get(f"{key}_over_decree"):
                item[key] = entry[key]
                item[f"{key}_housing"] = entry.get(f"{key}_housing", entry[key])
                if entry.get(f"{key}_site_rules"):
                    item[f"{key}_site_rules"] = entry[f"{key}_site_rules"]
                if entry[key] != entry.get(f"{key}_housing", entry[key]) or entry.get(f"{key}_site_rules"):
                    item.setdefault("texts", []).append(entry.get(f"{key}_text"))
            elif key in entry:
                item.setdefault("over_decree", []).append(f"조례 {'건폐율' if key == 'bcr' else '용적률'} {entry[key]:g}%가 시행령 상한을 넘어 시행령 상한을 적용")
        if item:
            table[zone] = item
    articles = row.get("articles") or {}
    source = {"name": row.get("title"), "number": f"{row.get('agency')} 조례 제{row.get('promulgation_no')}호" if row.get("promulgation_no") else None,
              "effective": row.get("effective"), "articles": ", ".join(a for a in (articles.get("bcr"), articles.get("far")) if a),
              "url": row.get("url") or DECREE["url"], "checked": row.get("checked"), "decree": DECREE["name"] + " 제84조·제85조",
              "issuer": issuer["name"] if issuer else None, "issuer_rule": issuer["rule"] if issuer else None, "parsed": True,
              "zones": len(table)}
    rules = [ORDINANCE_RULES[0].format(name=source["name"], articles=source["articles"] or "", checked=source["checked"] or "-"), *ORDINANCE_RULES[1:]]
    if issuer and issuer["code"] != code:
        rules.insert(1, f"{issuer['rule']}.")
    return {"region": code, "kind": "ORDINANCE", "status": row.get("status"), "table": table, "source": source, "rules": rules, "issuer": issuer}


def _field(rules: dict[str, Any], zone: str, key: str) -> tuple[float, str]:
    """(value, basis) of one field: the 조례 value when there is one, else the 시행령 상한."""
    value = (rules.get("table") or {}).get(zone, {}).get(key)
    if value is not None:
        return float(value), "ORDINANCE"
    decree_bcr, decree_far = DECREE_LIMITS[zone]
    return float(decree_bcr if key.startswith("bcr") else decree_far), "DECREE"


def resolve_zone(name: str | None, rules: dict[str, Any]) -> tuple[str, str | None]:
    """(table zone, assumption note or None). Unknown or undivided 용도지역 follow 국토계획법 제79조."""
    key = normalize_zone(name)
    if key:
        return key, None
    text = str(name or "").replace(" ", "")
    if text and not text.endswith("지역"):
        text += "지역"
    if text in UNDIVIDED:
        return UNDIVIDED[text]
    if text in CLASS_MEMBERS:
        members = CLASS_MEMBERS[text]
        strictest = min(members, key=lambda z: (_field(rules, z, "far")[0], _field(rules, z, "bcr")[0]))
        return strictest, f"세분되지 않은 {text} → 같은 {text} 중 상한이 가장 낮은 {strictest} 기준 (가정)"
    if not text:
        return "자연환경보전지역", GAP_NOTE
    return "자연환경보전지역", f"'{name}': 용도지역 이름을 알 수 없어 국토계획법 제79조 제1항(자연환경보전지역) 기준 (가정)"


def limits_for(zone_name: str | None, basis: str = "ORDINANCE", rules: dict[str, Any] | None = None) -> dict[str, Any]:
    """Limits of one 용도지역 under ``rules`` (default: 전주시 조례 for ``ORDINANCE``, 시행령 only for ``DECREE``)."""
    if rules is None:
        rules = region_rules(None, None) if basis == "ORDINANCE" else _decree_rules()
    zone, assumed = resolve_zone(zone_name, rules)
    bcr, bcr_basis = _field(rules, zone, "bcr")
    far, far_basis = _field(rules, zone, "far")
    entry = (rules.get("table") or {}).get(zone, {})
    bcr_housing = float(entry["bcr_housing"]) if bcr_basis == "ORDINANCE" and entry.get("bcr_housing") is not None else bcr
    far_housing: float | None = float(entry["far_housing"]) if far_basis == "ORDINANCE" and entry.get("far_housing") is not None else far
    notes = [assumed] if assumed else []
    if entry.get("note"):
        notes.append(entry["note"])
    notes.extend(entry.get("over_decree") or [])
    if zone in HOUSING_RESTRICTED:
        far_housing = None
        if not any("공동주택" in n and "확인" in n for n in notes):
            notes.append(HOUSING_RESTRICTED_NOTE)
    if bcr_basis == far_basis == "DECREE" and rules.get("kind") == "ORDINANCE" and not entry.get("over_decree"):
        notes.append("조례에 이 용도지역 값이 없어 국토계획법 시행령 상한")
    basis_zone = "ORDINANCE" if bcr_basis == far_basis == "ORDINANCE" else "DECREE" if bcr_basis == far_basis == "DECREE" else "MIXED"
    return {"zone": zone, "zone_name": zone_name, "known": True, "bcr_limit": bcr, "far_limit": far, "bcr_limit_housing": bcr_housing,
            "far_limit_housing": far_housing, "site_rules": entry.get("far_site_rules") or [] if far_basis == "ORDINANCE" else [],
            "note": " · ".join(n for n in notes if n) or None, "basis": basis_zone, "assumed": assumed,
            "texts": [t for t in entry.get("texts", []) if t]}


def basis_for(region_code: str | None) -> str:
    """Static basis without a database: 전주시 조례 표, 그 밖은 시행령 (조례 수집 여부는 ``region_rules``가 봅니다)."""
    from .regions import DEFAULT_REGION
    return "ORDINANCE" if (region_code or DEFAULT_REGION) == DEFAULT_REGION else "DECREE"


def _site_basis(rows: list[dict[str, Any]]) -> str:
    kinds = {r["basis"] for r in rows}
    return kinds.pop() if len(kinds) == 1 else "MIXED" if kinds else "DECREE"


def weighted_limits(zones: list[dict[str, Any]], site_area_m2: float, housing: bool = True, basis: str = "ORDINANCE",
                    rules: dict[str, Any] | None = None) -> dict[str, Any]:
    """Area-weighted 상한 over the site.

    ``zones``: [{"zone_name", "area_m2"}]. When 5 % or more of the site has no zoning polygon, that part follows
    국토계획법 제79조 제1항 (자연환경보전지역) as a labelled assumption; smaller gaps are ignored (edges, slivers).
    """
    if rules is None:
        rules = region_rules(None, None) if basis == "ORDINANCE" else _decree_rules()
    rows = []
    covered = 0.0
    for item in zones:
        area = float(item.get("area_m2") or 0)
        if area <= 0:
            continue
        info = limits_for(item.get("zone_name"), rules=rules)
        far = info["far_limit_housing"] if housing else info["far_limit"]
        bcr = info["bcr_limit_housing"] if housing else info["bcr_limit"]
        applied_notes = []
        for rule in info["site_rules"]:
            hit = site_area_m2 >= rule["min_site_m2"] if rule.get("inclusive") else site_area_m2 > rule["min_site_m2"]
            if hit and far is not None and rule["value"] < far:
                far = rule["value"]
                applied_notes.append(f"대지면적 {rule['min_site_m2']:,.0f}㎡ {'이상' if rule.get('inclusive') else '초과'}: 용적률 {rule['value']:g}% (조례 단서)")
        rows.append(dict(info, area_m2=round(area, 1), share=round(area / site_area_m2 * 100, 2) if site_area_m2 else None,
                         applied_bcr_limit=bcr, applied_far_limit=far, applied_notes=applied_notes))
        covered += area
    # Overlapping polygons (e.g. an unnamed 도시지역 outline under the 세부 용도지역): the named zones win,
    # the undivided/unknown ones only fill what the named ones leave, and the total never exceeds the site.
    if site_area_m2 and covered > site_area_m2 * 1.001:
        specific = sum(r["area_m2"] for r in rows if not r.get("assumed"))
        generic = sum(r["area_m2"] for r in rows if r.get("assumed"))
        spare = max(0.0, site_area_m2 - min(specific, site_area_m2))
        for r in rows:
            if r.get("assumed"):
                factor = min(1.0, spare / generic) if generic else 0.0
            else:
                factor = min(1.0, site_area_m2 / specific) if specific else 0.0
            if factor < 0.999:
                r["area_m2"] = round(r["area_m2"] * factor, 1)
                r["share"] = round(r["area_m2"] / site_area_m2 * 100, 2)
                r["applied_notes"] = [*r["applied_notes"], "겹치는 용도지역 도형은 세부 용도지역을 우선해 면적을 나눴습니다"]
        rows = [r for r in rows if r["area_m2"] > 0.05]
        covered = sum(r["area_m2"] for r in rows)
    covered_share = covered / site_area_m2 if site_area_m2 else 0.0
    gap = max(0.0, site_area_m2 - covered)
    if rows and site_area_m2 and gap / site_area_m2 >= ASSUMED_GAP_THRESHOLD:
        info = limits_for(None, rules=rules)
        rows.append(dict(info, zone_name=None, area_m2=round(gap, 1), share=round(gap / site_area_m2 * 100, 2),
                         applied_bcr_limit=info["bcr_limit_housing"] if housing else info["bcr_limit"],
                         applied_far_limit=info["far_limit_housing"] if housing else info["far_limit"], applied_notes=[], gap=True))
    rows.sort(key=lambda r: (bool(r.get("gap")), -r["area_m2"]))
    total = sum(r["area_m2"] for r in rows)
    status = "OK"
    bcr = far = None
    if not rows:
        status = "NO_ZONING"
    elif any(r["applied_bcr_limit"] is None or r["applied_far_limit"] is None for r in rows):
        status = "LIMIT_UNKNOWN"
    else:
        bcr = sum(r["applied_bcr_limit"] * r["area_m2"] for r in rows) / total
        far = sum(r["applied_far_limit"] * r["area_m2"] for r in rows) / total
    assumed_share = sum(r["share"] or 0 for r in rows if r.get("assumed"))
    return {"status": status, "zones": rows, "covered_share": round(min(covered_share, 1.0) * 100, 2),
            "bcr_limit": round(bcr, 2) if bcr is not None else None, "far_limit": round(far, 2) if far is not None else None,
            "mixed": len(rows) > 1, "basis": _site_basis(rows), "assumed_share": round(assumed_share, 2),
            "rules_kind": rules.get("kind"), "ordinance_status": rules.get("status")}


BASIS_TEXT = {"ORDINANCE": "조례", "DECREE": "시행령", "MIXED": "조례·시행령"}


def district_plan_label(name: str | None) -> str:
    """'서울 강남 보금자리주택지구 지구단' as is; a bare VWorld name '지구단위계획구역' is not repeated."""
    text = (name or "").strip()
    if not text:
        return "지구단위계획구역"
    return text if "지구단위" in text else f"지구단위계획구역({text})"


def check_plan(limits: dict[str, Any], *, bcr: float | None, far: float | None, site_area_m2: float, households: int | None) -> dict[str, Any]:
    """Compare a plan's 건폐율·용적률 (%) with the limits; adds the 지구단위계획 and 개발제한구역 flags."""
    def verdict(value: float | None, limit: float | None) -> str:
        if value is None or limit is None:
            return "UNKNOWN"
        return "OVER" if value > limit + 1e-9 else "WITHIN"

    bcr_state, far_state = verdict(bcr, limits.get("bcr_limit")), verdict(far, limits.get("far_limit"))
    basis = limits.get("basis", "ORDINANCE")
    word = BASIS_TEXT.get(basis, "조례")
    special = limits.get("special") or {}
    greenbelt = (special.get("greenbelt") or {}).get("share", 0) > 0
    plan_areas = special.get("district_plans") or []
    district_plan = site_area_m2 >= SITE_AREA_DISTRICT_PLAN_M2 or (households or 0) >= HOUSEHOLDS_DISTRICT_PLAN
    assumed = (limits.get("assumed_share") or 0) > 0
    if greenbelt:
        label = "개발제한구역 — 건축 원칙적 제한"
    elif "OVER" in (bcr_state, far_state):
        label = "시행령 상한 초과" if basis == "DECREE" else f"{word} 기본 상한 초과"
    elif bcr_state == far_state == "WITHIN":
        label = ("시행령 상한 이내 (조례 확인 필요)" if basis == "DECREE" and limits.get("rules_kind") != "ORDINANCE"
                 else f"{word} 기본 상한 이내 (1차 확인)")
    else:
        label = "법적 상한 판단 보류"
    if assumed and not greenbelt and label != "법적 상한 판단 보류":
        label += " · 일부 가정"
    if plan_areas and not greenbelt:
        label += " · 지구단위계획 우선"
    notes = []
    if greenbelt:
        notes.append(f"대지의 {special['greenbelt']['share']:.0f}%가 개발제한구역입니다. 개발제한구역법 제12조로 건축물의 건축이 원칙적으로 금지되고 "
                     "허가 대상 시설만 지을 수 있어 건폐율·용적률 판정을 하지 않습니다.")
    for area in plan_areas:
        notes.append(f"대지의 {area['share']:.0f}%가 {district_plan_label(area.get('name'))}입니다. 지구단위계획이 정한 건폐율·용적률·높이가 우선하므로 이 확인은 참고용입니다.")
    if basis == "DECREE" and limits.get("rules_kind") != "ORDINANCE":
        notes.append("이 지역 조례를 받지 못해(또는 읽지 못해) 국토계획법 시행령 상한으로 확인했습니다. 조례 상한은 더 낮을 수 있습니다.")
    elif basis in ("DECREE", "MIXED") and limits.get("rules_kind") == "ORDINANCE":
        notes.append("조례에 값이 없는 용도지역은 국토계획법 시행령 상한을 썼습니다.")
    if district_plan and not plan_areas:
        notes.append("지구단위계획 수립 대상 규모일 수 있습니다. 용적률은 지구단위계획 지침을 따르므로 이 확인과 다를 수 있습니다."
                     if basis != "ORDINANCE" or limits.get("ordinance_status") != "VERIFIED"
                     else "지구단위계획 수립 대상 규모입니다. 용적률은 전주시 지구단위계획수립지침을 따르므로 이 확인과 다를 수 있습니다.")
    if limits.get("mixed"):
        notes.append("대지가 여러 용도지역에 걸쳐 있어 면적 가중 상한을 썼습니다.")
    if limits.get("status") == "LIMIT_UNKNOWN":
        notes.append("조례에 수치가 없거나 공동주택 허용 여부 확인이 필요한 용도지역이 있습니다.")
    seen = set()
    for zone in limits.get("zones", []):
        for text in [zone.get("note"), *(zone.get("applied_notes") or [])]:
            if text and text not in seen:
                seen.add(text)
                notes.append(f"{zone['zone']}: {text}" if not zone.get("gap") else text)
    return {"label": label, "bcr": bcr_state, "far": far_state, "bcr_value": bcr, "far_value": far,
            "bcr_limit": limits.get("bcr_limit"), "far_limit": limits.get("far_limit"),
            "district_plan": district_plan or bool(plan_areas), "district_plan_areas": plan_areas, "greenbelt": greenbelt,
            "assumed": assumed, "notes": notes, "basis": basis}


def site_square_sql() -> str:
    """Zoning parts of a square site (EPSG:5179 metres) centred on a lon/lat point, rotated clockwise."""
    return (
        "WITH c AS (SELECT ST_Transform(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 5179) AS p), "
        "s AS (SELECT ST_Rotate(ST_MakeEnvelope(ST_X(p) - :h, ST_Y(p) - :h, ST_X(p) + :h, ST_Y(p) + :h, 5179), :rad, p) AS g FROM c) "
        "SELECT z.zone_name, sum(ST_Area(ST_Intersection(ST_MakeValid(z.geom), s.g))) AS area_m2 "
        "FROM vworld_zoning_areas z, s WHERE ST_Intersects(z.geom, s.g) GROUP BY z.zone_name ORDER BY area_m2 DESC"
    )


SPECIAL_SQL = (
    "WITH c AS (SELECT ST_Transform(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 5179) AS p), "
    "s AS (SELECT ST_Rotate(ST_MakeEnvelope(ST_X(p) - :h, ST_Y(p) - :h, ST_X(p) + :h, ST_Y(p) + :h, 5179), :rad, p) AS g FROM c) "
    "SELECT a.kind, a.name, sum(ST_Area(ST_Intersection(ST_MakeValid(a.geom), s.g))) AS area_m2 "
    "FROM vworld_special_areas a, s WHERE ST_Intersects(a.geom, s.g) GROUP BY a.kind, a.name ORDER BY area_m2 DESC"
)
LAYER_SQL = "SELECT dataset FROM vworld_grid_coverage WHERE grid_id = :g AND dataset IN ('zoning', 'zoning_management', 'greenbelt', 'district_plan')"


def _site_cell(lon: float, lat: float) -> str | None:
    try:
        from pyproj import Transformer
        x, y = Transformer.from_crs(4326, 5179, always_xy=True).transform(lon, lat)
    except Exception:  # noqa: BLE001
        return None
    return f"cell_{int(x // 500 * 500)}_{int(y // 500 * 500)}"


def special_areas(db: Any, lon: float, lat: float, side: float, rotation_deg: float, site_area_m2: float) -> dict[str, Any]:
    """개발제한구역·지구단위계획구역 overlapping the site, and which layers were collected around it."""
    from sqlalchemy import text

    params = {"lon": lon, "lat": lat, "h": side / 2, "rad": -math.radians(rotation_deg)}
    layers: set[str] = set()
    cell = _site_cell(lon, lat)
    try:
        if cell:
            layers = {row[0] for row in db.execute(text(LAYER_SQL), {"g": cell})}
    except Exception:  # noqa: BLE001
        db.rollback()
    out: dict[str, Any] = {"collected": "greenbelt" in layers and "district_plan" in layers, "zoning_other_collected": "zoning_management" in layers,
                           "greenbelt": None, "district_plans": []}
    try:
        rows = db.execute(text(SPECIAL_SQL), params).mappings().all()
    except Exception:  # noqa: BLE001 - table missing (not collected yet)
        db.rollback()
        return out
    greenbelt = sum(float(r["area_m2"] or 0) for r in rows if r["kind"] == "GREENBELT")
    if greenbelt > 0:
        out["greenbelt"] = {"area_m2": round(greenbelt, 1), "share": round(min(greenbelt / site_area_m2, 1.0) * 100, 2)}
    for row in rows:
        if row["kind"] == "DISTRICT_PLAN" and float(row["area_m2"] or 0) / site_area_m2 >= 0.01:
            out["district_plans"].append({"name": row["name"], "area_m2": round(float(row["area_m2"]), 1),
                                          "share": round(min(float(row["area_m2"]) / site_area_m2, 1.0) * 100, 2)})
    return out


def site_zoning(db: Any, lon: float, lat: float, site_area_m2: float, rotation_deg: float = 0.0, housing: bool = True,
                region_code: str | None = None) -> dict[str, Any]:
    """용도지역 parts of the square site (side √area), the region's limits (조례 → 시행령 → 제79조) and special areas."""
    from sqlalchemy import text

    rules = region_rules(db, region_code)
    source, texts = rules["source"], rules["rules"]
    side = math.sqrt(max(site_area_m2, 1.0))
    try:
        rows = db.execute(text(site_square_sql()), {"lon": lon, "lat": lat, "h": side / 2, "rad": -math.radians(rotation_deg)}).mappings().all()
    except Exception as exc:  # noqa: BLE001 - table missing or PostGIS unavailable → honest "not collected"
        db.rollback()
        return {"status": "NOT_COLLECTED", "zones": [], "covered_share": 0.0, "bcr_limit": None, "far_limit": None, "mixed": False,
                "reason": f"용도지역 자료를 읽지 못했습니다 ({type(exc).__name__})", "site": {"lon": lon, "lat": lat, "side_m": side, "rotation_deg": rotation_deg},
                "rules": texts, "source": source, "basis": rules["kind"], "rules_kind": rules["kind"], "ordinance_status": rules["status"]}
    result = weighted_limits([dict(r) for r in rows], site_area_m2, housing=housing, rules=rules)
    special = special_areas(db, lon, lat, side, rotation_deg, site_area_m2)
    if any(z.get("gap") for z in result["zones"]) and not special["zoning_other_collected"]:
        for zone in result["zones"]:
            if zone.get("gap"):
                zone["note"] = GAP_NOTE + ". 이 곳은 관리·농림·자연환경보전지역 자료를 아직 받지 않았을 수 있습니다"
    result.update(site={"lon": lon, "lat": lat, "side_m": round(side, 2), "area_m2": site_area_m2, "rotation_deg": rotation_deg},
                  rules=texts, source=source, housing=housing, special=special, issuer=rules.get("issuer"))
    return result


def grid_center_lonlat(db: Any, grid_id: str) -> tuple[float, float] | None:
    from sqlalchemy import text

    try:
        row = db.execute(text("SELECT ST_X(c) AS lon, ST_Y(c) AS lat FROM (SELECT ST_Transform(ST_Centroid(geom), 4326) AS c FROM grid_500m WHERE id = :id) q"), {"id": grid_id}).mappings().first()
    except Exception:  # noqa: BLE001
        db.rollback()
        return None
    return (float(row["lon"]), float(row["lat"])) if row else None
