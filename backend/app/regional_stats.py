"""전국 공식 통계 두 가지: 지역 온실가스 인벤토리(시·군·구, 2010~2023)와 시·도별 도시가스 판매량.

* 온실가스종합정보센터(GIR) '2025년 지역 온실가스 인벤토리(2010-2023) 공표' 첨부 '2025 지역 온실가스 통계.zip'
  (data/raw/research/gir/regional_2025/*.xlsx, 광역 17개 파일 + '기타').
  - 시트 '<광역>_<기초>(vkt)'·'(연료)' 마다 7~49행: 왼쪽은 직접배출(06 KRF 분류), 오른쪽은 간접배출(전력·열·폐기물).
    6행이 배출연도(2010~2023), 단위는 Gg CO2eq(= 천 tCO2eq).
  - VKT 기준과 연료 공급량 기준은 수송만 다르다(건물 부문 값은 같다). 총배출량은 VKT 기준을 쓴다.
  - '<광역>_광역' = 그 광역의 기초 합 + '<광역>_기타'(기초에 나누지 않은 배출). '기타_기초'는 지역에 나누지 않은
    국가 배출이라 쓰지 않는다.
  - 건물 등 배출 = 직접 '에너지 > A. 연료연소 > 4. 기타'(가정·상업·공공·농림어업의 연료 연소)
    + 간접 '전력 > A. 연료연소 > 4. 기타' + '열 > A. 연료연소 > 4. 기타'. '4. 기타'에는 농림어업이 들어 있다.
  - 인벤토리는 2026년 행정구역 개편 전 이름이다: 인천 중구·동구·서구는 개편 전 자치구 그대로, 광주광역시와
    전라남도는 따로 있다(전국 지도의 전남광주통합특별시는 둘을 더한다).
* 한국가스공사 '월별 시도별 도시가스 판매현황'(공공데이터포털 15040819, 천㎥, 1989-01~2024-12, cp949 CSV,
  data/raw/gas/*.csv). 시·도 단위뿐이다(시·군·구 단위 공개 통계 없음).

* 한국전력공사 시군구별 전력판매량(한전 누리집 '전력판매량' 게시판 월별 엑셀, kWh, data/raw/kepco/*.xlsx).
  - 시트 '계약종별'(주택용·일반용·교육용·산업용·농사용·가로등·심야·합계)과 '용도업종별'. 3행이 머리줄
    (연도·시도·시군구·구분·1월~12월). 한 파일은 한 해의 1월부터 그 파일의 달까지(뒤 달은 0으로 채워져 있어 비운다).
  - 같은 해 파일이 여럿이면 더 많은 달이 든 파일이 이긴다(12월분 = 그해 전체).
  - 이름은 그해 행정구역: 2018년 인천 '남구'는 '미추홀구', 2023년 전 경북 '군위군'은 대구 '군위군'으로 잇는다.
    2026년 파일에는 개편 전후 이름(광주·전남과 광주전남통합특별시, 인천 옛 구와 새 구)이 함께 있어 연간 지표에는
    12개월이 모두 있는 해(2025년까지)만 쓴다.
  - 건물 전력 = 주택용 + 일반용 + 교육용(산업용·농사용·가로등·심야 제외).

세 자료 모두 전국 지도(``national_map``)의 시·도·시·군·구 지표로 쓴다. 값이 없는 곳은 0이 아니라 비운다.
"""
from __future__ import annotations

import csv
import io
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import JSON, Float, Integer, String, delete, func, insert, select, text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

GIR_URL = "https://www.gir.go.kr/home/board/read.do?menuId=36&boardMasterId=2&boardId=89"
GAS_URL = "https://www.data.go.kr/data/15040819/fileData.do"
GIR_SOURCE_TEXT = "온실가스종합정보센터 2025 지역 온실가스 인벤토리(2010~2023)"
GAS_SOURCE_TEXT = "한국가스공사 월별 시도별 도시가스 판매현황 (공공데이터포털 15040819)"
BASE_YEAR = 2018  # 국가 온실가스 감축목표(NDC)의 기준 연도

# GIR 광역 이름 → 전국 지도 시·도(법정 2자리) 코드. 광주·전남은 2026 통합 시·도(12)로 더한다.
GIR_SIDO = {"서울": "11", "부산": "26", "대구": "27", "인천": "28", "광주": "12", "대전": "30", "울산": "31", "세종": "36",
            "경기": "41", "강원": "51", "충북": "43", "충남": "44", "전북": "52", "전남": "12", "경북": "47", "경남": "48", "제주": "50"}
# 가스공사 CSV 열 이름도 같은 짧은 이름이다.
GAS_SIDO = GIR_SIDO

KEY_TOTAL = "총배출량"
KEY_BUILDING_DIRECT = "에너지/A. 연료연소/4. 기타"
KEY_BUILDING_ELECTRICITY = "전력/A. 연료연소/4. 기타"
KEY_BUILDING_HEAT = "열/A. 연료연소/4. 기타"
KEY_ELECTRICITY = "전력"
MAP_KEYS = (KEY_TOTAL, KEY_BUILDING_DIRECT, KEY_BUILDING_ELECTRICITY, KEY_BUILDING_HEAT, KEY_ELECTRICITY)

LEFT_TOP = {"총배출량", "순배출량", "에너지", "산업공정 및 제품 생산", "농업", "LULUCF", "폐기물"}
RIGHT_TOP = {"간접배출량 합계", "간접(전력, 열) 합계", "전력", "열", "폐기물"}
SHEET_RE = re.compile(r"^(.+?)_(.+)\((vkt|연료)\)$")
LETTER_RE = re.compile(r"^[A-Z]\.\s*")
NUMBER_RE = re.compile(r"^\d+\.\s*")


class GirRegionalGhg(Base):
    __tablename__ = "gir_regional_ghg"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # "<basis>:<광역>:<기초>:<side>:<key>:<year>"
    sido: Mapped[str] = mapped_column(String, index=True)       # GIR 광역 이름 (서울, 경기, …, 기타)
    sgg: Mapped[str] = mapped_column(String, index=True)        # GIR 기초 이름, '광역'(광역 전체) 또는 '기타'
    basis: Mapped[str] = mapped_column(String)                  # 'vkt' | 'fuel' (수송 배출 산정 기준)
    side: Mapped[str] = mapped_column(String)                   # 'direct' | 'indirect'
    key: Mapped[str] = mapped_column(String, index=True)        # 분류 경로, 예: '에너지/A. 연료연소/4. 기타'
    year: Mapped[int] = mapped_column(Integer, index=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)  # Gg CO2eq (= 천 tCO2eq)
    source_file: Mapped[str] = mapped_column(String)


class CitygasSidoMonthly(Base):
    __tablename__ = "citygas_sido_monthly"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # "<시·도>:<YYYY-MM>"
    sido: Mapped[str] = mapped_column(String, index=True)      # 가스공사 열 이름 (서울, 인천, …)
    year_month: Mapped[str] = mapped_column(String, index=True)
    thousand_m3: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_file: Mapped[str] = mapped_column(String)


KEPCO_URL = "https://www.kepco.co.kr/home/customer/library/electricity-statistics/sales-volume/boardList.do"
KEPCO_SOURCE_TEXT = "한국전력공사 시군구별 전력판매량 (계약종별, kWh)"
KEPCO_SIDO = {"서울특별시": "11", "부산광역시": "26", "대구광역시": "27", "인천광역시": "28", "광주광역시": "12", "대전광역시": "30",
              "울산광역시": "31", "세종특별자치시": "36", "경기도": "41", "강원도": "51", "강원특별자치도": "51", "충청북도": "43",
              "충청남도": "44", "전라북도": "52", "전북특별자치도": "52", "전라남도": "12", "광주전남통합특별시": "12",
              "전남광주통합특별시": "12", "경상북도": "47", "경상남도": "48", "제주특별자치도": "50"}
# 그해 이름 → 지금 시·도·이름 (행정구역이 바뀐 곳)
KEPCO_ALIASES = {("28", "남구"): ("28", "미추홀구"), ("47", "군위군"): ("27", "군위군")}
BUILDING_USES = ("주택용", "일반용", "교육용")


class KepcoSigunguMonthly(Base):
    __tablename__ = "kepco_sigungu_monthly"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # "<year>:<kind>:<시도>:<시군구>:<구분>"
    year: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String)                  # 'contract'(계약종별) | 'industry'(용도업종별)
    sido: Mapped[str] = mapped_column(String)                  # 그해 한전 표기 (전라북도, 전북특별자치도 …)
    sgg: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String, index=True)  # 공백 없앤 구분 (합계, 주택용 …)
    months: Mapped[list] = mapped_column(JSON)                 # 1~12월 kWh, 파일에 아직 없는 달은 null
    last_month: Mapped[int] = mapped_column(Integer)
    source_file: Mapped[str] = mapped_column(String)


# --------------------------------------------------------------------------- parsing (pure, tested without files)
def _clean(label: Any) -> str | None:
    if not isinstance(label, str):
        return None
    label = re.sub(r"\s+", " ", label).strip()
    return label or None


def sheet_identity(name: str) -> tuple[str, str, str] | None:
    """'경기_수원시(vkt)' → ('경기', '수원시', 'vkt'); '(연료)' → 'fuel'. Other sheets (바로가기) → None."""
    m = SHEET_RE.match(name.strip())
    if not m:
        return None
    sido, sgg, basis = m.groups()
    return sido, sgg, "vkt" if basis == "vkt" else "fuel"


def _paths(labels: Iterable[Any], top: set[str]) -> list[str | None]:
    """Hierarchical keys for one label column: top level, 'A.' level, '1.' level."""
    stack: list[str] = []
    out: list[str | None] = []
    for raw in labels:
        label = _clean(raw)
        if label is None:
            out.append(None)
            continue
        if label in top:
            stack = [label]
        elif LETTER_RE.match(label):
            stack = stack[:1] + [label]
        elif NUMBER_RE.match(label):
            stack = stack[:2] + [label]
        else:
            stack = stack[:1] + [label]
        out.append("/".join(stack))
    return out


def parse_sheet(rows: list[list[Any]]) -> list[tuple[str, str, int, float | None]]:
    """(side, key, year, Gg CO2eq) of one GIR sheet (rows as read from row 1, 0-based list).

    Row 6 holds the years (direct: columns D..Q, indirect: columns V..AI); rows 7.. the categories."""
    if len(rows) < 7:
        return []
    header = list(rows[5]) + [None] * 80
    out: list[tuple[str, str, int, float | None]] = []
    for side, label_col, first, top in (("direct", 0, 3, LEFT_TOP), ("indirect", 18, 21, RIGHT_TOP)):
        years = []
        for i in range(first, first + 40):  # the contiguous run of year columns (the other side starts after a gap)
            if not (isinstance(header[i], (int, float)) and 1990 <= int(header[i]) <= 2100):
                break
            years.append((i, int(header[i])))
        body = rows[6:]
        labels = [(list(r) + [None] * 40)[label_col] for r in body]
        for row, key in zip(body, _paths(labels, top)):
            if key is None:
                continue
            cells = list(row) + [None] * 40
            for i, year in years:
                v = cells[i]
                out.append((side, key, year, float(v) if isinstance(v, (int, float)) else None))
    return out


def parse_citygas(content: str) -> list[tuple[str, str, float | None]]:
    """(시·도, 'YYYY-MM', 천㎥) from the 가스공사 CSV (already decoded). Empty cells stay None (not 0)."""
    reader = csv.reader(io.StringIO(content))
    header = [h.strip().lstrip("﻿") for h in next(reader, [])]
    if not header or header[0] != "연월":
        raise ValueError("가스공사 CSV 머리줄이 '연월'로 시작하지 않습니다")
    out = []
    for row in reader:
        if not row or not re.match(r"^\d{4}-\d{2}$", row[0].strip()):
            continue
        for name, cell in zip(header[1:], row[1:]):
            cell = cell.strip().replace(",", "")
            out.append((name, row[0].strip(), float(cell) if cell not in ("", "-") else None))
    return out


def parse_kepco_sheet(rows: list[list[Any]]) -> tuple[list[tuple[int, str, str, str, list[float | None]]], int]:
    """(연도, 시도, 시군구, 구분, 1~12월 kWh) of one 한전 sheet and the last month the file reports.

    Months after that month are 0 in the file (not reported yet) and become None."""
    start = next((i + 1 for i, r in enumerate(rows[:10]) if r and r[0] == "연도"), None)
    if start is None:
        raise ValueError("한전 시트에 '연도' 머리줄이 없습니다")
    body = []
    for r in rows[start:]:
        r = (list(r) + [None] * 16)[:16]
        if not isinstance(r[0], (int, float)) or not r[1] or not r[2] or not r[3]:
            continue
        months = [float(v) if isinstance(v, (int, float)) else None for v in r[4:16]]
        body.append((int(r[0]), str(r[1]).strip(), str(r[2]).strip(), re.sub(r"\s+", "", str(r[3])), months))
    last = max((m + 1 for _, _, _, _, months in body for m, v in enumerate(months) if v), default=0)
    return [(y, sido, sgg, cat, [v if i < last else None for i, v in enumerate(months)]) for y, sido, sgg, cat, months in body], last


def kepco_key(sido: str, sgg: str) -> tuple[str, str] | None:
    """(지금 시·도 코드, 이름) of a 한전 row; None for places outside the map (개성시 등)."""
    code = KEPCO_SIDO.get(sido)
    if not code:
        return None
    return KEPCO_ALIASES.get((code, sgg), (code, sgg))


def annual(months: list[float | None] | None) -> float | None:
    """Yearly kWh only when all 12 months are reported."""
    if not months or len(months) < 12 or any(v is None for v in months[:12]):
        return None
    return float(sum(months[:12]))


def kepco_metrics(values: dict[tuple[str, int], float | None], year: int, base: int = BASE_YEAR, households: float | None = None,
                  household_year: int | None = None) -> dict[str, float | None]:
    """Map metrics of one area from {(구분, 연도): kWh}: 전력 합계·건물 전력(GWh), 2018 대비 건물 전력 증감률, 가구당 주택용."""
    def building(y: int) -> float | None:
        parts = [values.get((c, y)) for c in BUILDING_USES]
        return None if any(p is None for p in parts) else float(sum(parts))
    total = values.get(("합계", year))
    now = building(year)
    home = values.get(("주택용", household_year)) if household_year else None
    return {"elec_total": round(total / 1e6, 1) if total is not None else None,
            "elec_building": round(now / 1e6, 1) if now is not None else None,
            "elec_building_change_pct": change_pct(building(base), now),
            "elec_home_per_household": round(home / households) if home is not None and households else None}


def decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp949", errors="replace")


# --------------------------------------------------------------------------- summaries (pure)
def change_pct(before: float | None, after: float | None) -> float | None:
    if before is None or after is None or before <= 0:
        return None
    return round((after - before) / before * 100, 1)


def ghg_metrics(values: dict[tuple[str, int], float | None], year: int, base: int = BASE_YEAR) -> dict[str, float | None]:
    """Map metrics of one area from {(key, year): Gg}: 총배출량, 건물 등(직접+전력+열), 2018 대비 건물 등 증감률."""
    def building(y: int) -> float | None:
        parts = [values.get((k, y)) for k in (KEY_BUILDING_DIRECT, KEY_BUILDING_ELECTRICITY, KEY_BUILDING_HEAT)]
        return None if any(p is None for p in parts) else float(sum(parts))
    total = values.get((KEY_TOTAL, year))
    now, then = building(year), building(base)
    return {"ghg_total": round(total, 1) if total is not None else None,
            "ghg_building": round(now, 1) if now is not None else None,
            "ghg_building_change_pct": change_pct(then, now)}


def add_values(parts: list[dict[tuple[str, int], float | None]]) -> dict[tuple[str, int], float | None]:
    """Sum several areas (광주 + 전남); a key missing in any part stays missing."""
    keys = set().union(*parts) if parts else set()
    out: dict[tuple[str, int], float | None] = {}
    for k in keys:
        vals = [p.get(k) for p in parts]
        out[k] = None if any(v is None for v in vals) else float(sum(vals))
    return out


def gas_summary(rows: dict[str, float | None], year: int, base: int = BASE_YEAR) -> dict[str, Any] | None:
    """{'YYYY-MM': 천㎥} of one 시·도 → yearly sales (only full years of 12 months) and change since ``base``."""
    def total(y: int) -> float | None:
        months = [rows.get(f"{y}-{m:02d}") for m in range(1, 13)]
        return None if any(v is None for v in months) else float(sum(months))
    now = total(year)
    if now is None:
        return None
    then = total(base)
    return {"year": year, "thousand_m3": round(now, 1), "base_year": base, "base_thousand_m3": round(then, 1) if then is not None else None,
            "change_pct": change_pct(then, now)}


# --------------------------------------------------------------------------- files → database
def data_root() -> Path:
    return Path(os.getenv("DATA_DIR", "data")) / "raw"


def gir_files(root: Path | None = None) -> list[Path]:
    root = root or data_root()
    return sorted(p for p in (root / "research" / "gir").glob("regional_*/*.xlsx") if not p.name.startswith("~$"))


def gas_files(root: Path | None = None) -> list[Path]:
    root = root or data_root()
    return sorted((root / "gas").glob("*.csv"))


def _loaded(db: Any, model: Any, name: str) -> bool:
    return bool(db.scalar(select(func.count()).select_from(model).where(model.source_file == name)))


def import_gir(db: Any, root: Path | None = None, force: bool = False) -> int:
    """Read every GIR regional xlsx not loaded yet (one file = one 광역). Returns rows written."""
    from openpyxl import load_workbook
    written = 0
    for path in gir_files(root):
        name = path.name
        if not force and _loaded(db, GirRegionalGhg, name):
            continue
        rows_out: list[dict[str, Any]] = []
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            for sheet in wb.sheetnames:
                ident = sheet_identity(sheet)
                if not ident:
                    continue
                sido, sgg, basis = ident
                rows = [list(r) for r in wb[sheet].iter_rows(min_row=1, max_row=60, values_only=True)]
                for side, key, year, value in parse_sheet(rows):
                    rows_out.append({"id": f"{basis}:{sido}:{sgg}:{side}:{key}:{year}", "sido": sido, "sgg": sgg, "basis": basis, "side": side,
                                     "key": key, "year": year, "value": value, "source_file": name})
        finally:
            wb.close()
        # one file holds one 광역 (ids carry 광역·기초), so replacing that file's rows is enough
        db.execute(delete(GirRegionalGhg).where(GirRegionalGhg.source_file == name))
        for start in range(0, len(rows_out), 5000):
            db.execute(insert(GirRegionalGhg), rows_out[start:start + 5000])
        db.commit()
        written += len(rows_out)
    return written


def import_gas(db: Any, root: Path | None = None, force: bool = False) -> int:
    written = 0
    for path in gas_files(root):
        name = path.name
        if not force and _loaded(db, CitygasSidoMonthly, name):
            continue
        rows = parse_citygas(decode(path.read_bytes()))
        db.execute(delete(CitygasSidoMonthly).where(CitygasSidoMonthly.source_file == name))
        payload = [{"id": f"{s}:{ym}", "sido": s, "year_month": ym, "thousand_m3": v, "source_file": name} for s, ym, v in rows]
        db.execute(delete(CitygasSidoMonthly).where(CitygasSidoMonthly.id.in_([p["id"] for p in payload])))
        for start in range(0, len(payload), 5000):
            db.execute(insert(CitygasSidoMonthly), payload[start:start + 5000])
        db.commit()
        written += len(payload)
    return written


LOCK_KEY = 5_000_600  # pg advisory lock: the API start-up import and a CLI run never load the same file at once


@contextmanager
def _import_lock(db: Any):
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        yield
        return
    with bind.connect() as connection:
        connection.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK_KEY})
        try:
            yield
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            connection.commit()


def kepco_files(root: Path | None = None) -> list[Path]:
    root = root or data_root()
    return sorted(p for p in (root / "kepco").glob("*.xlsx") if not p.name.startswith("~$"))


def import_kepco(db: Any, root: Path | None = None, force: bool = False) -> int:
    """한전 시군구별 전력판매량: each file holds one year; a year is replaced only by a file with more months."""
    from openpyxl import load_workbook
    written = 0
    for path in kepco_files(root):
        name = path.name
        if not force and _loaded(db, KepcoSigunguMonthly, name):
            continue
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            sheets = {("contract" if "계약" in ws.title else "industry"): parse_kepco_sheet([list(r) for r in ws.iter_rows(values_only=True)])
                      for ws in wb.worksheets if "계약" in ws.title or "업종" in ws.title}
        finally:
            wb.close()
        for kind, (rows, last) in sheets.items():
            years = sorted({r[0] for r in rows})
            for year in years:
                have = db.scalar(select(func.max(KepcoSigunguMonthly.last_month)).where(
                    KepcoSigunguMonthly.year == year, KepcoSigunguMonthly.kind == kind, KepcoSigunguMonthly.source_file != name))
                if have and have >= last and not force:
                    continue  # another file already holds this year with at least as many months
                db.execute(delete(KepcoSigunguMonthly).where(KepcoSigunguMonthly.year == year, KepcoSigunguMonthly.kind == kind))
                payload = {}
                for y, sido, sgg, cat, months in rows:
                    if y == year:
                        rid = f"{y}:{kind}:{sido}:{sgg}:{cat}"
                        payload[rid] = {"id": rid, "year": y, "kind": kind, "sido": sido, "sgg": sgg, "category": cat, "months": months,
                                        "last_month": last, "source_file": name}
                items = list(payload.values())
                for start in range(0, len(items), 5000):
                    db.execute(insert(KepcoSigunguMonthly), items[start:start + 5000])
                written += len(items)
        db.commit()
    return written


def import_all(db: Any, root: Path | None = None, force: bool = False) -> dict[str, int]:
    """Every source; files already loaded are skipped (checked again after waiting for another importer)."""
    with _import_lock(db):
        return {"gir": import_gir(db, root, force), "gas": import_gas(db, root, force), "kepco": import_kepco(db, root, force)}


def row_counts(db: Any) -> tuple[int, int, int]:
    try:
        return (int(db.scalar(select(func.count()).select_from(GirRegionalGhg)) or 0),
                int(db.scalar(select(func.count()).select_from(CitygasSidoMonthly)) or 0),
                int(db.scalar(select(func.count()).select_from(KepcoSigunguMonthly)) or 0))
    except Exception:  # noqa: BLE001 - tables missing
        db.rollback()
        return 0, 0, 0


# --------------------------------------------------------------------------- readers for the national map
def gir_latest_year(db: Any) -> int | None:
    try:
        return db.scalar(select(func.max(GirRegionalGhg.year)).where(GirRegionalGhg.basis == "vkt", GirRegionalGhg.value.is_not(None)))
    except Exception:  # noqa: BLE001
        db.rollback()
        return None


def gir_values(db: Any, years: Iterable[int]) -> dict[tuple[str, str], dict[tuple[str, int], float | None]]:
    """{(광역, 기초): {(key, year): Gg}} for the map keys (VKT 기준)."""
    out: dict[tuple[str, str], dict[tuple[str, int], float | None]] = {}
    try:
        rows = db.execute(select(GirRegionalGhg.sido, GirRegionalGhg.sgg, GirRegionalGhg.key, GirRegionalGhg.year, GirRegionalGhg.value)
                          .where(GirRegionalGhg.basis == "vkt", GirRegionalGhg.key.in_(MAP_KEYS), GirRegionalGhg.year.in_(list(years))))
        for sido, sgg, key, year, value in rows:
            out.setdefault((sido, sgg), {})[(key, int(year))] = value
    except Exception:  # noqa: BLE001 - table missing
        db.rollback()
    return out


def gas_by_province(db: Any, year: int | None = None) -> dict[str, dict[str, Any]]:
    """전국 지도 시·도 코드 → 연간 도시가스 판매량(천㎥) and change since 2018 (광주+전남 = 12)."""
    try:
        rows = list(db.execute(select(CitygasSidoMonthly.sido, CitygasSidoMonthly.year_month, CitygasSidoMonthly.thousand_m3)))
    except Exception:  # noqa: BLE001
        db.rollback()
        return {}
    if not rows:
        return {}
    by_code: dict[str, dict[str, dict[str, float | None]]] = {}
    for sido, ym, value in rows:
        code = GAS_SIDO.get(sido)
        if code:
            by_code.setdefault(code, {}).setdefault(sido, {})[ym] = value
    last = year or max(int(ym[:4]) for _, ym, _ in rows if ym)
    out: dict[str, dict[str, Any]] = {}
    for code, parts in by_code.items():
        merged: dict[str, float | None] = {}
        for ym in set().union(*parts.values()):
            vals = [p.get(ym) for p in parts.values()]
            merged[ym] = None if any(v is None for v in vals) else float(sum(vals))
        summary = gas_summary(merged, last)
        if summary:
            summary["parts"] = sorted(parts)
            out[code] = summary
    return out


def kepco_values(db: Any) -> tuple[dict[tuple[str, str], dict[tuple[str, int], float | None]], int | None]:
    """{(시·도 코드, 이름): {(구분, 연도): 연간 kWh}} (계약종별, 12개월이 모두 있는 해) and the latest such year."""
    out: dict[tuple[str, str], dict[tuple[str, int], float | None]] = {}
    try:
        rows = list(db.execute(select(KepcoSigunguMonthly.year, KepcoSigunguMonthly.sido, KepcoSigunguMonthly.sgg, KepcoSigunguMonthly.category,
                                      KepcoSigunguMonthly.months).where(KepcoSigunguMonthly.kind == "contract", KepcoSigunguMonthly.last_month == 12)))
    except Exception:  # noqa: BLE001 - table missing
        db.rollback()
        return {}, None
    for year, sido, sgg, category, months in rows:
        key = kepco_key(sido, sgg)
        if key:
            out.setdefault(key, {})[(category, int(year))] = annual(months)
    latest = max((int(r[0]) for r in rows), default=None)
    return out, latest


def region_index(values: dict[tuple[str, str], Any]) -> dict[tuple[str, str], tuple[str, str]]:
    """(시·도 코드, 기초 이름) → (광역, 기초) for every GIR 기초 (not '광역'/'기타')."""
    out: dict[tuple[str, str], tuple[str, str]] = {}
    for sido, sgg in values:
        if sgg in ("광역", "기타") or sido not in GIR_SIDO:
            continue
        out[(GIR_SIDO[sido], sgg)] = (sido, sgg)
    return out


def match_region(index: dict[tuple[str, str], tuple[str, str]], sido_code: str | None, short: str, only_one: bool) -> tuple[str, str] | None:
    """GIR 기초 of a 전국 지도 시·군·구 by name inside its 시·도. 세종처럼 시·도에 하나뿐이면 이름이 달라도 잇는다."""
    if not sido_code:
        return None
    hit = index.get((sido_code, short))
    if hit:
        return hit
    if only_one:
        inside = [v for (code, _), v in index.items() if code == sido_code]
        # 세종: '세종시' ↔ '세종특별자치시' (시·도에 하나뿐이고 이름 앞부분이 같을 때만)
        if len(inside) == 1 and short.startswith(inside[0][1].removesuffix("시")):
            return inside[0]
    return None


REORGANIZED_NOTE = "2026년 개편으로 생긴 구: GIR 2023 통계는 개편 전 자치구(중구·동구·서구) 기준이라 이 구에 나눌 수 없음"
