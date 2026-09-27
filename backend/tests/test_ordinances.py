from pathlib import Path

from app.ordinances import ZONES, _parse_search, issuer_for, parse_limit_items, parse_ordinance, pick_search_hit
from app.zoning_limits import LIMITS

FIXTURES = Path(__file__).parent / "fixtures"


def test_jeonju_parsed_values_equal_the_verified_table():
    # 전주시 도시계획 조례 제45조("100분의 40" 형식)·제47조(단서의 주거복합·공동주택 상한): 원문 대조한 표와 같아야 한다
    parsed = parse_ordinance((FIXTURES / "ordinance-jeonju-45-47.xml").read_bytes())
    assert parsed["title"] == "전주시 도시계획 조례" and parsed["effective"] == "2026-04-13" and parsed["status"] == "PARSED"
    assert parsed["articles"] == {"bcr": "제45조(용도지역안에서의 건폐율)", "far": "제47조(용도지역안에서의 용적률)"}
    for zone, (bcr, far, far_housing, _note) in LIMITS.items():
        entry = parsed["limits"].get(zone, {})
        assert entry.get("bcr") == bcr and entry.get("far") == far, zone
        if far_housing is not None:
            assert entry["far_housing"] == far_housing, zone
    assert "자연환경보전지역" not in parsed["limits"]  # 조례에 규정 없음 → 시행령으로 넘어간다


def test_suwon_housing_provisos_and_missing_zones():
    parsed = parse_ordinance((FIXTURES / "ordinance-suwon-66-70.xml").read_bytes())
    limits = parsed["limits"]
    assert parsed["zones_bcr"] == 16 and parsed["zones_far"] == 16
    assert (limits["제3종일반주거지역"]["bcr"], limits["제3종일반주거지역"]["far"], limits["제3종일반주거지역"]["far_housing"]) == (40, 300, 230)
    # "각 목의 어느 하나에 해당하는 경우 500퍼센트" — 재건축 600퍼센트는 공동주택 일반 상한이 아니다
    assert limits["일반상업지역"]["far"] == 800 and limits["일반상업지역"]["far_housing"] == 500
    assert limits["중심상업지역"]["bcr_housing"] == 80 and limits["중심상업지역"]["far_housing"] == 500
    assert limits["일반공업지역"]["far_housing"] == 350  # 고시원 단서는 공동주택 상한이 아님
    assert not any(zone in limits for zone in ("보전관리지역", "계획관리지역", "농림지역", "자연환경보전지역"))


def test_busan_thousand_notation_and_site_area_rule():
    parsed = parse_ordinance((FIXTURES / "ordinance-busan-49-50.xml").read_bytes())
    limits = parsed["limits"]
    assert limits["중심상업지역"]["far"] == 1300 and limits["일반상업지역"]["far"] == 1000
    assert limits["제2종일반주거지역"]["far"] == 220
    assert limits["제2종일반주거지역"]["far_site_rules"] == [{"min_site_m2": 1000.0, "inclusive": False, "value": 200.0}]
    assert all(e.get("bcr", 0) <= 90 for e in limits.values())


def test_item_formats():
    lines = ["제9조(용도지역안에서의 용적률) 용적률은 다음과 같다. 1. 제1종 전용주거지역: 100분의 80 2. 보전녹지지역ㆍ생산녹지지역 및 자연녹지지역: 50퍼센트 이하",
             "② 제1항에도 불구하고 1. 일반주거지역: 500퍼센트 이하"]
    parsed = parse_limit_items(lines)
    assert parsed["제1종전용주거지역"]["value"] == 80
    assert all(parsed[z]["value"] == 50 for z in ("보전녹지지역", "생산녹지지역", "자연녹지지역"))
    assert len(parsed) == 4  # ② 이후(완화 규정)는 읽지 않는다


def test_issuer_rules():
    assert issuer_for("11680", "서울특별시 강남구", "서울특별시")["code"] == "11000"
    assert issuer_for("27710", "대구광역시 달성군", "대구광역시")["name"] == "대구광역시"  # 광역시 관할 군
    assert issuer_for("50130", "제주특별자치도 서귀포시", "제주특별자치도")["name"] == "제주특별자치도"
    assert issuer_for("36110", "세종특별자치시", "세종특별자치시")["code"] == "36000"
    assert issuer_for("41110", "경기도 수원시", "경기도") == {"code": "41110", "name": "경기도 수원시", "names": ["경기도 수원시"], "rule": "시·군 도시·군계획 조례"}
    gu = issuer_for("12140", "전남광주통합특별시 광산구", "전남광주통합특별시")
    assert gu["code"] == "12000" and gu["names"] == ["전남광주통합특별시", "광주광역시"]
    assert issuer_for("12810", "전남광주통합특별시 강진군", "전남광주통합특별시")["code"] == "12810"


def test_search_hit_selection():
    body = ("<OrdinSearch>"
            "<law><자치법규일련번호>1</자치법규일련번호><자치법규명>고성군 군계획 조례</자치법규명><지자체기관명>강원특별자치도 고성군</지자체기관명><자치법규종류>조례</자치법규종류><시행일자>20260629</시행일자></law>"
            "<law><자치법규일련번호>2</자치법규일련번호><자치법규명>고성군계획 조례</자치법규명><지자체기관명>경상남도 고성군</지자체기관명><자치법규종류>조례</자치법규종류><시행일자>20251222</시행일자></law>"
            "<law><자치법규일련번호>3</자치법규일련번호><자치법규명>고성군 군계획 조례 시행규칙</자치법규명><지자체기관명>경상남도 고성군</지자체기관명><자치법규종류>규칙</자치법규종류><시행일자>20260101</시행일자></law>"
            "<law><자치법규일련번호>4</자치법규일련번호><자치법규명>강진군 군계획 조례</자치법규명><지자체기관명>전남광주통합특별시 강진군</지자체기관명><자치법규종류>조례</자치법규종류><시행일자>20260810</시행일자></law>"
            "</OrdinSearch>").encode()
    hits = _parse_search(body)
    assert pick_search_hit(hits, "경상남도 고성군", today="20260927")["mst"] == "2"
    assert pick_search_hit(hits, "강원특별자치도 고성군", today="20260927")["mst"] == "1"
    assert pick_search_hit(hits, "전라남도 강진군", today="20260927")["mst"] == "4"  # 시도 이름이 바뀌어도 같은 군
    assert pick_search_hit(hits, "경상북도 고령군", today="20260927") is None
    assert len(ZONES) == 21


def test_hwp_table_attachment():
    # 창원시 도시계획 조례 별표 27은 law.go.kr XML에 본문이 없고 .hwp 첨부로만 있다
    from app.hwp import hwp_text
    from app.ordinances import _parse_table_text, _combined_scan
    text = hwp_text((FIXTURES / "ordinance-changwon-table27.hwp").read_bytes())
    assert "용도지역에서의 건폐율" in text and "1. 제1종 전용주거지역 : 50퍼센트" in text
    parsed = _parse_table_text(text, "건폐율", combined=False)
    assert len(parsed) == 21 and parsed["준주거지역"]["value"] == 70 and parsed["계획관리지역"]["value"] == 40
    combined = _combined_scan("제1종전용주거지역 50퍼센트 이하 100퍼센트 이하\n중심상업지역 80퍼센트 이하 1,300퍼센트 이하")
    assert combined["bcr"]["중심상업지역"]["value"] == 80 and combined["far"]["중심상업지역"]["value"] == 1300


def test_title_and_agency_variants():
    from app.ordinances import _same_agency, _title_ok
    assert _title_ok("청도군 군계획 조례 [제명개정 2020. 10. 5.]", "청도군")
    assert _title_ok("장흥군 관리계획 조례", "장흥군") and _title_ok("거창군 계획조례", "거창군")
    assert not _title_ok("장흥군 지방재정계획심의위원회 조례", "장흥군")
    assert _same_agency("(구)광주광역시", "광주광역시")  # 통합 전 광역시 조례
