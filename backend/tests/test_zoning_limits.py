from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.zoning_limits import LIMITS, check_plan, limits_for, normalize_zone, site_zoning, weighted_limits


def test_ordinance_values_and_names():
    assert normalize_zone('제2종일반주거지역') == '제2종일반주거지역' and normalize_zone('제2종일반주거') == '제2종일반주거지역'
    assert normalize_zone('없는지역') is None and normalize_zone(None) is None
    second = limits_for('제2종일반주거지역')
    assert (second['bcr_limit'], second['far_limit'], second['far_limit_housing']) == (60, 250, 250)
    # 상업지역: 주거복합건축물·오피스텔은 낮은 상한, 준공업: 공동주택 200
    assert limits_for('일반상업지역')['far_limit'] == 900 and limits_for('일반상업지역')['far_limit_housing'] == 600
    assert limits_for('준공업지역')['far_limit_housing'] == 200
    # 조례에 없는 용도지역은 국토계획법 시행령 상한 (전국 공통 규칙)
    natural = limits_for('자연환경보전지역')
    assert (natural['bcr_limit'], natural['far_limit'], natural['basis']) == (20, 80, 'DECREE') and '시행령' in natural['note']
    assert limits_for('제2종일반주거지역')['basis'] == 'ORDINANCE'
    assert len(LIMITS) == 21


def test_single_zone_site_within_limits():
    limits = weighted_limits([{'zone_name': '제2종일반주거지역', 'area_m2': 10000}], 10000)
    assert limits['status'] == 'OK' and limits['bcr_limit'] == 60 and limits['far_limit'] == 250 and not limits['mixed']
    check = check_plan(limits, bcr=28.0, far=240.0, site_area_m2=10000, households=240)
    assert check['label'] == '조례 기본 상한 이내 (1차 확인)' and check['far'] == 'WITHIN'
    assert check['district_plan'] is True  # 1만㎡ 이상은 지구단위계획 수립 대상
    over = check_plan(limits, bcr=28.0, far=336.0, site_area_m2=9000, households=240)
    assert over['label'] == '조례 기본 상한 초과' and over['far'] == 'OVER' and over['district_plan'] is False


def test_mixed_zones_are_area_weighted_and_gaps_follow_article_79():
    mixed = weighted_limits([{'zone_name': '제2종일반주거지역', 'area_m2': 7500}, {'zone_name': '자연녹지지역', 'area_m2': 2500}], 10000)
    assert mixed['mixed'] and mixed['far_limit'] == 212.5 and mixed['bcr_limit'] == 50.0
    assert [z['zone'] for z in mixed['zones']] == ['제2종일반주거지역', '자연녹지지역'] and mixed['assumed_share'] == 0
    # 대지의 40%에 용도지역 자료가 없음 → 국토계획법 제79조 제1항(자연환경보전지역 20%·80%) 가정, 표시
    partial = weighted_limits([{'zone_name': '제2종일반주거지역', 'area_m2': 6000}], 10000)
    assert partial['status'] == 'OK' and partial['assumed_share'] == 40.0
    assert partial['far_limit'] == 0.6 * 250 + 0.4 * 80 and partial['bcr_limit'] == 0.6 * 60 + 0.4 * 20
    gap = partial['zones'][-1]
    assert gap['gap'] and gap['zone'] == '자연환경보전지역' and '제79조' in gap['note']
    check = check_plan(partial, bcr=20, far=100, site_area_m2=10000, households=10)
    assert check['label'] == '조례·시행령 기본 상한 이내 (1차 확인) · 일부 가정' and check['assumed']
    # 작은 틈(5% 미만)은 무시
    assert weighted_limits([{'zone_name': '제2종일반주거지역', 'area_m2': 9700}], 10000)['assumed_share'] == 0
    industrial = weighted_limits([{'zone_name': '일반공업지역', 'area_m2': 10000}], 10000)
    assert industrial['status'] == 'LIMIT_UNKNOWN'  # 공동주택 허용 여부 확인 필요
    assert weighted_limits([], 10000)['status'] == 'NO_ZONING'


def test_site_zoning_without_postgis_reports_not_collected():
    db = sessionmaker(create_engine('sqlite+pysqlite:///:memory:'))()
    result = site_zoning(db, 127.15, 35.82, 10000)
    assert result['status'] == 'NOT_COLLECTED' and result['far_limit'] is None and result['source']['url'].startswith('https://www.law.go.kr')


def test_decree_basis_outside_the_original_region():
    from app.zoning_limits import basis_for, check_plan, limits_for, weighted_limits
    assert basis_for(None) == "ORDINANCE" and basis_for("52110") == "ORDINANCE"
    assert basis_for("41110") == "DECREE"
    decree = limits_for("제2종일반주거지역", "DECREE")
    assert decree["bcr_limit"] == 60 and decree["far_limit"] == 250  # 시행령 제84조·제85조 상한
    assert limits_for("준주거지역", "DECREE")["bcr_limit"] == 70  # 조례(전주 60)보다 높음
    assert limits_for("자연환경보전지역", "DECREE")["known"] is True
    assert limits_for("일반공업지역", "DECREE")["far_limit_housing"] is None  # 공동주택 건축 제한 확인
    limits = weighted_limits([{"zone_name": "제2종일반주거지역", "area_m2": 10000}], 10000, basis="DECREE")
    assert limits["status"] == "OK" and limits["basis"] == "DECREE"
    over = check_plan(limits, bcr=40, far=260, site_area_m2=10000, households=200)
    assert over["label"] == "시행령 상한 초과" and over["basis"] == "DECREE"
    within = check_plan(limits, bcr=40, far=240, site_area_m2=5000, households=100)
    assert within["label"] == "시행령 상한 이내 (조례 확인 필요)"
    assert any("조례 상한은 더 낮을 수 있습니다" in note for note in within["notes"])


def test_undivided_and_unknown_zones_follow_article_79():
    from app.zoning_limits import limits_for
    urban = limits_for("도시지역", "DECREE")
    assert urban["zone"] == "보전녹지지역" and (urban["bcr_limit"], urban["far_limit"]) == (20, 80) and "시행령 제86조" in urban["assumed"]
    assert limits_for("관리지역", "DECREE")["zone"] == "보전관리지역"
    assert limits_for("상업지역", "DECREE")["zone"] == "근린상업지역"  # 상업지역 중 가장 낮은 상한 (가정)
    assert limits_for("주거지역")["zone"] == "제1종전용주거지역"
    unknown = limits_for("알수없는지역", "DECREE")
    assert unknown["zone"] == "자연환경보전지역" and "제79조 제1항" in unknown["assumed"]


def test_parsed_ordinance_rules_per_zone(monkeypatch):
    from app import ordinances
    from app.zoning_limits import check_plan, region_rules, weighted_limits
    row = {"status": "PARSED", "title": "수원시 도시계획 조례", "agency": "경기도 수원시", "promulgation_no": "4816", "effective": "2025-12-31",
           "articles": {"bcr": "제66조(용도지역 안에서의 건폐율)", "far": "제70조(용도지역안에서의 용적률)"}, "checked": "2026-09-27", "url": "https://www.law.go.kr/x",
           "limits": {"제3종일반주거지역": {"bcr": 40, "bcr_housing": 40, "far": 300, "far_housing": 230},
                      "제2종일반주거지역": {"bcr": 60, "bcr_housing": 60, "far": 220, "far_housing": 220,
                                     "far_site_rules": [{"min_site_m2": 1000, "inclusive": False, "value": 200}]},
                      "준주거지역": {"bcr": 80, "far": 400, "far_housing": 400, "bcr_over_decree": True}}}
    issuer = {"code": "41110", "name": "경기도 수원시", "names": ["경기도 수원시"], "rule": "시·군 도시·군계획 조례"}
    monkeypatch.setattr(ordinances, "ordinance_for_region", lambda db, code: {"issuer": issuer, "status": "PARSED", "row": row})
    rules = region_rules(None, "41110")
    assert rules["kind"] == "ORDINANCE" and rules["source"]["name"] == "수원시 도시계획 조례" and "제66조" in rules["source"]["articles"]
    third = weighted_limits([{"zone_name": "제3종일반주거지역", "area_m2": 10000}], 10000, rules=rules)
    assert (third["bcr_limit"], third["far_limit"], third["basis"]) == (40, 230, "ORDINANCE")  # 공동주택 단서
    assert weighted_limits([{"zone_name": "제3종일반주거지역", "area_m2": 10000}], 10000, housing=False, rules=rules)["far_limit"] == 300
    # 대지면적 1천㎡ 초과 단서
    assert weighted_limits([{"zone_name": "제2종일반주거지역", "area_m2": 800}], 800, rules=rules)["far_limit"] == 220
    big = weighted_limits([{"zone_name": "제2종일반주거지역", "area_m2": 5000}], 5000, rules=rules)
    assert big["far_limit"] == 200 and "대지면적 1,000㎡ 초과" in big["zones"][0]["applied_notes"][0]
    # 조례 값이 시행령 상한을 넘으면 시행령 (준주거 건폐율 70%), 조례에 없는 용도지역은 시행령
    semi = weighted_limits([{"zone_name": "준주거지역", "area_m2": 1000}], 1000, rules=rules)
    assert semi["bcr_limit"] == 70 and semi["far_limit"] == 400 and semi["basis"] == "MIXED"
    green = weighted_limits([{"zone_name": "계획관리지역", "area_m2": 1000}], 1000, rules=rules)
    assert (green["bcr_limit"], green["far_limit"], green["basis"]) == (40, 100, "DECREE")
    check = check_plan(third, bcr=30, far=250, site_area_m2=10000, households=200)
    assert check["label"] == "조례 기본 상한 초과" and check["far"] == "OVER"
    within = check_plan(green, bcr=30, far=90, site_area_m2=1000, households=10)
    assert within["label"] == "시행령 기본 상한 이내 (1차 확인)"  # 조례를 받은 지역에서 조례에 없는 용도지역
    assert any("조례에 값이 없는 용도지역" in n for n in within["notes"])


def test_unparsed_region_uses_decree_and_says_why(monkeypatch):
    from app import ordinances
    from app.zoning_limits import region_rules
    issuer = {"code": "11000", "name": "서울특별시", "names": ["서울특별시"], "rule": "특별시·광역시의 구·군은 시 조례를 따릅니다"}
    monkeypatch.setattr(ordinances, "ordinance_for_region", lambda db, code: {"issuer": issuer, "status": "NOT_FOUND", "row": {"status": "NOT_FOUND"}})
    rules = region_rules(None, "11680")
    assert rules["kind"] == "DECREE" and rules["status"] == "NOT_FOUND"
    assert "찾지 못해" in rules["rules"][0] and "서울특별시 도시·군계획 조례" in rules["rules"][1]


def test_greenbelt_and_district_plan_flags():
    from app.zoning_limits import check_plan, weighted_limits
    limits = weighted_limits([{"zone_name": "자연녹지지역", "area_m2": 10000}], 10000)
    limits["special"] = {"greenbelt": {"area_m2": 4000, "share": 40.0}, "district_plans": []}
    check = check_plan(limits, bcr=10, far=50, site_area_m2=10000, households=10)
    assert check["label"] == "개발제한구역 — 건축 원칙적 제한" and check["greenbelt"] and "제12조" in check["notes"][0]
    limits["special"] = {"greenbelt": None, "district_plans": [{"name": "영통 지구단위계획구역", "area_m2": 10000, "share": 100.0}]}
    plan = check_plan(limits, bcr=10, far=50, site_area_m2=10000, households=10)
    assert plan["label"].endswith("지구단위계획 우선") and plan["district_plan"] and "영통" in plan["notes"][0]


def test_overlapping_unnamed_urban_outline_only_fills_the_rest():
    from app.zoning_limits import weighted_limits
    # VWorld has a large 도시지역 polygon without a 세부 name under the named 자연녹지지역 polygon
    both = weighted_limits([{"zone_name": "자연녹지지역", "area_m2": 10000}, {"zone_name": "", "area_m2": 10000}], 10000, basis="DECREE")
    assert [z["zone"] for z in both["zones"]] == ["자연녹지지역"] and both["far_limit"] == 100 and both["assumed_share"] == 0
    part = weighted_limits([{"zone_name": "자연녹지지역", "area_m2": 7000}, {"zone_name": "도시지역", "area_m2": 10000}], 10000, basis="DECREE")
    assert [(z["zone"], z["share"]) for z in part["zones"]] == [("자연녹지지역", 70.0), ("보전녹지지역", 30.0)]
    assert part["far_limit"] == 0.7 * 100 + 0.3 * 80 and part["assumed_share"] == 30.0
