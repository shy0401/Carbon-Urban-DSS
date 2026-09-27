"""용도지역별 건폐율·용적률 상한과 계획 대지의 1차 적합성 확인.

* 전주시(최초 연구 지역): 전주시 도시계획 조례 제45·47조 기본 상한.
* 그 밖의 지역: 해당 시·군 조례를 아직 등록하지 않았으므로 국토계획법 시행령 제84조(건폐율)·
  제85조(용적률 범위의 상한)를 씁니다. 조례는 시행령 범위 안에서 더 낮게 정하므로, 시행령 상한
  '초과'는 조례로도 초과이지만 '이내'는 조례 확인이 더 필요합니다.

값은 원문에서 확인한 수치만 둔다(확인 못 한 칸은 None). 완화 규정, 지구단위계획 지침, 경관지구
제한은 반영하지 않으므로 결과는 인허가 판단이 아니라 1차 확인이다.
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


def normalize_zone(name: str | None) -> str | None:
    """VWorld 이름("제2종일반주거지역")을 표의 키로 맞춘다. 모르는 이름은 None."""
    text = str(name or "").replace(" ", "")
    if not text:
        return None
    if not text.endswith("지역"):
        text += "지역"
    return text if text in LIMITS else None


def limits_for(zone_name: str | None, basis: str = "ORDINANCE") -> dict[str, Any]:
    """Limits of one 용도지역: ``ORDINANCE`` (전주시 조례) or ``DECREE`` (국토계획법 시행령 상한)."""
    key = normalize_zone(zone_name)
    if key is None:
        return {"zone": zone_name, "known": False, "bcr_limit": None, "far_limit": None, "far_limit_housing": None,
                "note": ("조례 표에 없는 용도지역 이름입니다" if basis == "ORDINANCE" else "시행령 표에 없는 용도지역 이름입니다") if zone_name else "용도지역 자료 없음"}
    if basis == "DECREE":
        bcr, far = DECREE_LIMITS[key]
        return {"zone": key, "known": True, "bcr_limit": bcr, "far_limit": far, "far_limit_housing": far,
                "note": "공동주택 허용 여부는 건축 제한을 따로 확인해야 합니다" if key in ("유통상업지역", "전용공업지역", "일반공업지역") else None}
    bcr, far, far_housing, note = LIMITS[key]
    return {"zone": key, "known": bcr is not None, "bcr_limit": bcr, "far_limit": far, "far_limit_housing": far_housing, "note": note}


def basis_for(region_code: str | None) -> str:
    """전주시(52110)만 조례 표가 등록되어 있습니다."""
    from .regions import DEFAULT_REGION
    return "ORDINANCE" if (region_code or DEFAULT_REGION) == DEFAULT_REGION else "DECREE"


def weighted_limits(zones: list[dict[str, Any]], site_area_m2: float, housing: bool = True, basis: str = "ORDINANCE") -> dict[str, Any]:
    """Area-weighted 상한 over the covered part of the site.

    ``zones``: [{"zone_name", "area_m2"}]. The uncovered part (no zoning polygon) makes the result partial:
    a limit is only returned when zoning covers at least 95 % of the site and every covered zone has a value.
    """
    rows = []
    covered = 0.0
    for item in zones:
        area = float(item.get("area_m2") or 0)
        if area <= 0:
            continue
        info = limits_for(item.get("zone_name"), basis)
        far = info["far_limit_housing"] if housing else info["far_limit"]
        rows.append(dict(info, zone_name=item.get("zone_name"), area_m2=round(area, 1),
                         share=round(area / site_area_m2 * 100, 2) if site_area_m2 else None, applied_far_limit=far))
        covered += area
    rows.sort(key=lambda r: -r["area_m2"])
    covered_share = covered / site_area_m2 if site_area_m2 else 0.0
    status = "OK"
    bcr = far = None
    if not rows:
        status = "NO_ZONING"
    elif covered_share < 0.95:
        status = "PARTIAL_COVERAGE"
    elif any(r["bcr_limit"] is None or r["applied_far_limit"] is None for r in rows):
        status = "LIMIT_UNKNOWN"
    else:
        bcr = sum(r["bcr_limit"] * r["area_m2"] for r in rows) / covered
        far = sum(r["applied_far_limit"] * r["area_m2"] for r in rows) / covered
    return {"status": status, "zones": rows, "covered_share": round(min(covered_share, 1.0) * 100, 2),
            "bcr_limit": round(bcr, 2) if bcr is not None else None, "far_limit": round(far, 2) if far is not None else None,
            "mixed": len(rows) > 1, "basis": basis}


def check_plan(limits: dict[str, Any], *, bcr: float | None, far: float | None, site_area_m2: float, households: int | None) -> dict[str, Any]:
    """Compare a plan's 건폐율·용적률 (%) with the limits; adds the district-plan (지구단위계획) flag."""
    def verdict(value: float | None, limit: float | None) -> str:
        if value is None or limit is None:
            return "UNKNOWN"
        return "OVER" if value > limit + 1e-9 else "WITHIN"

    bcr_state, far_state = verdict(bcr, limits.get("bcr_limit")), verdict(far, limits.get("far_limit"))
    decree = limits.get("basis") == "DECREE"
    district_plan = site_area_m2 >= SITE_AREA_DISTRICT_PLAN_M2 or (households or 0) >= HOUSEHOLDS_DISTRICT_PLAN
    if "OVER" in (bcr_state, far_state):
        label = "시행령 상한 초과" if decree else "조례 기본 상한 초과"
    elif bcr_state == far_state == "WITHIN":
        label = "시행령 상한 이내 (조례 확인 필요)" if decree else "조례 기본 상한 이내 (1차 확인)"
    else:
        label = "법적 상한 판단 보류"
    notes = []
    if decree:
        notes.append("이 지역 조례가 등록되지 않아 국토계획법 시행령 상한으로 확인했습니다. 조례 상한은 더 낮을 수 있습니다.")
    if district_plan:
        notes.append("지구단위계획 수립 대상 규모일 수 있습니다. 용적률은 지구단위계획 지침을 따르므로 이 확인과 다를 수 있습니다." if decree
                     else "지구단위계획 수립 대상 규모입니다. 용적률은 전주시 지구단위계획수립지침을 따르므로 이 확인과 다를 수 있습니다.")
    if limits.get("mixed"):
        notes.append("대지가 여러 용도지역에 걸쳐 있어 면적 가중 상한을 썼습니다.")
    if limits.get("status") == "PARTIAL_COVERAGE":
        notes.append("대지 일부에 용도지역 자료가 없어 판단을 보류합니다.")
    if limits.get("status") == "LIMIT_UNKNOWN":
        notes.append("조례에 수치가 없거나 공동주택 허용 여부 확인이 필요한 용도지역이 있습니다.")
    for zone in limits.get("zones", []):
        if zone.get("note"):
            notes.append(f"{zone['zone']}: {zone['note']}")
    return {"label": label, "bcr": bcr_state, "far": far_state, "bcr_value": bcr, "far_value": far,
            "bcr_limit": limits.get("bcr_limit"), "far_limit": limits.get("far_limit"),
            "district_plan": district_plan, "notes": notes, "basis": limits.get("basis", "ORDINANCE")}


def site_square_sql() -> str:
    """Zoning parts of a square site (EPSG:5179 metres) centred on a lon/lat point, rotated clockwise."""
    return (
        "WITH c AS (SELECT ST_Transform(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 5179) AS p), "
        "s AS (SELECT ST_Rotate(ST_MakeEnvelope(ST_X(p) - :h, ST_Y(p) - :h, ST_X(p) + :h, ST_Y(p) + :h, 5179), :rad, p) AS g FROM c) "
        "SELECT z.zone_name, sum(ST_Area(ST_Intersection(ST_MakeValid(z.geom), s.g))) AS area_m2 "
        "FROM vworld_zoning_areas z, s WHERE ST_Intersects(z.geom, s.g) GROUP BY z.zone_name ORDER BY area_m2 DESC"
    )


def site_zoning(db: Any, lon: float, lat: float, site_area_m2: float, rotation_deg: float = 0.0, housing: bool = True,
                region_code: str | None = None) -> dict[str, Any]:
    """용도지역 parts of the square site (side √area) and the weighted limits (조례, or 시행령 outside Jeonju)."""
    from sqlalchemy import text

    basis = basis_for(region_code)
    rules, source = (RULES, ORDINANCE) if basis == "ORDINANCE" else (DECREE_RULES, DECREE)

    side = math.sqrt(max(site_area_m2, 1.0))
    try:
        rows = db.execute(text(site_square_sql()), {"lon": lon, "lat": lat, "h": side / 2, "rad": -math.radians(rotation_deg)}).mappings().all()
    except Exception as exc:  # noqa: BLE001 - table missing or PostGIS unavailable → honest "not collected"
        db.rollback()
        return {"status": "NOT_COLLECTED", "zones": [], "covered_share": 0.0, "bcr_limit": None, "far_limit": None, "mixed": False,
                "reason": f"용도지역 자료를 읽지 못했습니다 ({type(exc).__name__})", "site": {"lon": lon, "lat": lat, "side_m": side, "rotation_deg": rotation_deg},
                "rules": rules, "source": source, "basis": basis}
    result = weighted_limits([dict(r) for r in rows], site_area_m2, housing=housing, basis=basis)
    result.update(site={"lon": lon, "lat": lat, "side_m": round(side, 2), "area_m2": site_area_m2, "rotation_deg": rotation_deg},
                  rules=rules, source=source, housing=housing)
    return result


def grid_center_lonlat(db: Any, grid_id: str) -> tuple[float, float] | None:
    from sqlalchemy import text

    try:
        row = db.execute(text("SELECT ST_X(c) AS lon, ST_Y(c) AS lat FROM (SELECT ST_Transform(ST_Centroid(geom), 4326) AS c FROM grid_500m WHERE id = :id) q"), {"id": grid_id}).mappings().first()
    except Exception:  # noqa: BLE001
        db.rollback()
        return None
    return (float(row["lon"]), float(row["lat"])) if row else None
