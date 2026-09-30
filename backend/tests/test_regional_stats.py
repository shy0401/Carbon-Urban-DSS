"""GIR 지역 온실가스 인벤토리·가스공사 시·도 도시가스 판매량: 읽기, 요약, 전국 지도 연결 (DB 없이)."""
from app import regional_stats as rs
from app.national_map import FIELDS, attach_ghg, summarize


def gir_sheet(scale: float = 1.0) -> list[list]:
    """GIR 시트 모양: 6행 연도(왼쪽 D~Q, 오른쪽 V~AI), 7행부터 분류. 연도 2018·2023만 둔 작은 표."""
    width = 40
    rows = [[None] * width for _ in range(6)]
    header = rows[5]
    header[0], header[1], header[2] = "구분", "광역", "기초"
    header[3], header[4] = 2018, 2023
    header[18] = "구분"
    header[21], header[22] = 2018, 2023
    left = [("총배출량", 1000), ("에너지", 700), ("A. 연료연소", 690), ("1.  에너지산업", 100), ("4.  기타", 200), ("B. 탈루", 10),
            ("폐기물", 50), ("A. 폐기물매립", 50)]
    right = [("간접배출량 합계", 520), ("전력", 500), ("A. 연료연소", 500), ("4.  기타", 300), ("열", 20), ("A. 연료연소", 20), ("4.  기타", 10),
             ("폐기물", 5)]
    for i in range(max(len(left), len(right))):
        row = [None] * width
        if i < len(left):
            row[0] = left[i][0]
            row[3], row[4] = left[i][1] * scale, left[i][1] * scale * 0.9
        if i < len(right):
            row[18] = right[i][0]
            row[21], row[22] = right[i][1] * scale, right[i][1] * scale * 0.8
        rows.append(row)
    return rows


def values_of(rows) -> dict:
    return {(key, year): value for _, key, year, value in rs.parse_sheet(rows)}


def test_sheet_keys_follow_the_category_tree_on_both_sides():
    parsed = rs.parse_sheet(gir_sheet())
    keys = {(side, key) for side, key, _, _ in parsed}
    assert ("direct", "에너지/A. 연료연소/4. 기타") in keys and ("direct", "폐기물/A. 폐기물매립") in keys
    assert ("indirect", "전력/A. 연료연소/4. 기타") in keys and ("indirect", "열/A. 연료연소/4. 기타") in keys
    # each side reads only its own run of year columns (the left side must not pick up 2018·2023 of the right side)
    assert sorted({year for _, _, year, _ in parsed}) == [2018, 2023]
    assert len(parsed) == (8 + 8) * 2
    v = values_of(gir_sheet())
    assert v[(rs.KEY_TOTAL, 2023)] == 900 and v[(rs.KEY_BUILDING_ELECTRICITY, 2023)] == 240
    assert rs.sheet_identity("경기_수원시(vkt)") == ("경기", "수원시", "vkt")
    assert rs.sheet_identity("세종_세종시(연료)") == ("세종", "세종시", "fuel") and rs.sheet_identity("바로가기") is None


def test_building_emissions_add_direct_electricity_and_heat():
    m = rs.ghg_metrics(values_of(gir_sheet()), 2023)
    # 2023: 직접 180 + 전력 240 + 열 8 = 428; 2018: 200 + 300 + 10 = 510
    assert m == {"ghg_total": 900.0, "ghg_building": 428.0, "ghg_building_change_pct": -16.1}
    both = rs.add_values([values_of(gir_sheet()), values_of(gir_sheet(2.0))])
    assert rs.ghg_metrics(both, 2023)["ghg_total"] == 2700.0
    # a part without a key leaves the sum empty (not a partial sum)
    assert rs.add_values([{("a", 1): 1.0}, {}])[("a", 1)] is None
    assert rs.change_pct(0, 5) is None and rs.change_pct(None, 5) is None


def test_citygas_csv_and_full_year_totals():
    text = "연월,서울,광주,전남\n2018-01,10,1,2\n" + "".join(f"2024-{m:02d},{m},1,\n" for m in range(1, 13))
    rows = rs.parse_citygas(text)
    assert ("서울", "2018-01", 10.0) in rows and ("전남", "2024-03", None) in rows
    seoul = {ym: v for s, ym, v in rows if s == "서울"}
    assert rs.gas_summary(seoul, 2024) == {"year": 2024, "thousand_m3": 78.0, "base_year": 2018, "base_thousand_m3": None, "change_pct": None}
    jeonnam = {ym: v for s, ym, v in rows if s == "전남"}
    assert rs.gas_summary(jeonnam, 2024) is None  # empty months: no yearly total
    assert rs.decode("연월,서울\n".encode("cp949")).startswith("연월")


def region(code: str, short: str, sido: str, linked: bool = True) -> dict:
    metrics, notes = summarize([{"population": 10, "households": 1, "area_km2": 1}], 0)
    return {"code": code, "short_name": short, "sido": sido, "linked": linked, "metrics": metrics, "notes": notes}


def test_map_rows_get_gir_values_by_name_inside_the_province():
    gir = {("전북", "전주시"): values_of(gir_sheet()), ("세종", "세종시"): values_of(gir_sheet()), ("인천", "중구"): values_of(gir_sheet()),
           ("광주", "광역"): values_of(gir_sheet()), ("전남", "광역"): values_of(gir_sheet(2.0)), ("전북", "광역"): values_of(gir_sheet())}
    regions = [region("52110", "전주시", "52"), region("36110", "세종특별자치시", "36"), region("28125", "제물포구", "28"),
               region("sgis:23010", "중구", "28", linked=False), region("52710", "완주군", "52")]
    provinces = [dict(region("12", "전남광주통합특별시", "12"), code="12"), dict(region("52", "전북특별자치도", "52"), code="52"),
                 dict(region("11", "서울특별시", "11"), code="11")]
    attach_ghg(regions, provinces, gir, 2023)
    by = {r["code"]: r for r in regions}
    assert by["52110"]["metrics"]["ghg_building"] == 428.0 and set(by["52110"]["metrics"]) == set(FIELDS)
    assert by["36110"]["metrics"]["ghg_total"] == 900.0  # 세종: 시·도에 하나뿐이라 이름이 달라도 잇는다
    assert by["28125"]["metrics"]["ghg_total"] is None and "2026년 개편" in by["28125"]["notes"]["ghg_total"]
    assert by["sgis:23010"]["metrics"]["ghg_total"] == 900.0 and "개편 전" in by["sgis:23010"]["notes"]["ghg_total"]
    assert by["52710"]["metrics"]["ghg_total"] is None and "없음" in by["52710"]["notes"]["ghg_total"]
    p = {x["code"]: x for x in provinces}
    assert p["12"]["metrics"]["ghg_total"] == 2700.0 and "광주·전남" in p["12"]["notes"]["ghg_total"]
    assert p["11"]["metrics"]["ghg_total"] is None
    # nothing loaded: every row says why (never 0)
    empty = [region("52110", "전주시", "52")]
    attach_ghg(empty, [], {}, None)
    assert empty[0]["metrics"]["ghg_total"] is None and "가져오지 않음" in empty[0]["notes"]["ghg_building"]


def test_manual_list_drops_collected_files_and_keeps_the_factor_decision(tmp_path):
    from app.history import MANUAL_SOURCES, manual_sources
    raw = tmp_path / "raw"
    (raw / "research" / "gir" / "regional_2025").mkdir(parents=True)
    (raw / "research" / "gir" / "regional_2025" / "x.xlsx").write_bytes(b"")
    (raw / "gas").mkdir()
    (raw / "gas" / "kogas.csv").write_text("연월,서울\n", encoding="utf-8")
    for board in (44, 56, 86):
        (raw / "research" / "gir" / f"b{board}_1_승인.pdf").write_bytes(b"")
    items = manual_sources(tmp_path)
    ids = [i["id"] for i in items]
    assert "gir_regional" not in ids and "gas_sido" not in ids and len(items) == len(MANUAL_SOURCES) - 2
    factor = next(i for i in items if i["id"] == "factors_yearly")
    assert "2025 승인" in factor["label"] and "0.4781" in factor["why"]


def test_historic_electricity_factors_need_matching_evidence(tmp_path, monkeypatch):
    from app import emissions
    folder = tmp_path / "research" / "gir"
    folder.mkdir(parents=True)
    (folder / "b56_2_2021.pdf").write_bytes(b"%PDF")
    (folder / "b56_2_2021.txt").write_text("간접배출량 소비단 CO2eq. 배출계수 0.4781 t CO2eq/MWh", encoding="utf-8")
    monkeypatch.setattr(emissions, "RAW", tmp_path)

    class FakeDb:
        def __init__(self):
            self.rows = []
        def merge(self, row):
            self.rows.append(row)
        def commit(self):
            pass

    db = FakeDb()
    assert emissions.collect_historic_factors(db) == ["gir-2021-approved-consumption"]
    assert db.rows[0].factor == 0.4781 and db.rows[0].effective_from == "2022-01-10"
    (folder / "b56_2_2021.txt").write_text("다른 문서", encoding="utf-8")
    try:
        emissions.collect_historic_factors(FakeDb())
    except ValueError as exc:
        assert "증빙 불일치" in str(exc)
    else:
        raise AssertionError("evidence without the published value must be refused")
