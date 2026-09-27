import io
import zipfile

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import regions
from app.regions import AdminUnit, Scope, legal_leaves, match_sgis, parse_legal_dong, region_catalog, short_name, sido_keys


def legal_zip(lines):
    text = "법정동코드\t법정동명\t폐지여부\n" + "\n".join(lines) + "\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("법정동코드 전체자료.txt", text.encode("cp949"))
    return buffer.getvalue()


SAMPLE = [
    "4100000000\t경기도\t존재",
    "4111000000\t경기도 수원시\t존재",
    "4111100000\t경기도 수원시 장안구\t존재",
    "4111110100\t경기도 수원시 장안구 파장동\t존재",
    "4111300000\t경기도 수원시 권선구\t존재",
    "4182000000\t경기도 가평군\t존재",
    "4182025000\t경기도 가평군 가평읍\t존재",
    "4182025021\t경기도 가평군 가평읍 읍내리\t존재",
    "4182025022\t경기도 가평군 가평읍 대곡리\t존재",
    "1100000000\t서울특별시\t존재",
    "1111000000\t서울특별시 종로구\t존재",
    "1111010100\t서울특별시 종로구 청운동\t존재",
    "3611000000\t세종특별자치시\t존재",
    "4211000000\t강원도 춘천시\t폐지",
]


def test_parse_keeps_only_existing_codes_with_levels():
    rows = parse_legal_dong(legal_zip(SAMPLE))
    by_code = {row["code"]: row for row in rows}
    assert "4211000000" not in by_code  # 폐지
    assert by_code["4100000000"]["level"] == "SIDO"
    assert by_code["4111100000"]["level"] == "SIGUNGU" and by_code["4111100000"]["parent_code"] == "4100000000"
    assert by_code["4111110100"]["level"] == "EMD" and by_code["4111110100"]["parent_code"] == "4111100000"
    assert by_code["4182025021"]["level"] == "RI" and by_code["4182025021"]["parent_code"] == "4182025000"


def test_catalog_groups_general_districts_under_their_city():
    rows = region_catalog(parse_legal_dong(legal_zip(SAMPLE)))
    by_code = {row["code"]: row for row in rows}
    assert by_code["41110"]["legal_codes"] == ["41110", "41111", "41113"]
    assert [d["name"] for d in by_code["41110"]["districts"]] == ["장안구", "권선구"]
    assert "41111" not in by_code  # an 일반구 is not a region of its own
    assert by_code["11110"]["legal_codes"] == ["11110"]  # 서울 자치구 stays a region
    assert by_code["41820"]["sido_name"] == "경기도"
    assert by_code["36110"]["name"] == "세종특별자치시"


def test_sido_keys_follow_renamed_provinces():
    assert sido_keys("전라북도") == sido_keys("전북특별자치도") == ("전북",)
    assert sido_keys("강원특별자치도") == ("강원",)
    assert set(sido_keys("전남광주통합특별시")) == {"전남", "광주"}


def test_sgis_codes_match_by_name_never_by_guess():
    sgis = [
        {"adm_code": "35011", "adm_name": "전라북도 전주시 완산구"}, {"adm_code": "35012", "adm_name": "전라북도 전주시 덕진구"},
        {"adm_code": "35020", "adm_name": "전라북도 군산시"}, {"adm_code": "31011", "adm_name": "경기도 수원시 장안구"},
        {"adm_code": "31012", "adm_name": "경기도 수원시 권선구"}, {"adm_code": "31010", "adm_name": "경기도 수원시장안"},
        {"adm_code": "29010", "adm_name": "세종특별자치시 세종시"},
    ]
    assert match_sgis("전북특별자치도 전주시", sgis) == ["35011", "35012"]
    assert match_sgis("경기도 수원시", sgis) == ["31011", "31012"]
    assert match_sgis("세종특별자치시", sgis) == ["29010"]
    assert match_sgis("경기도 용인시", sgis) == []


def test_legal_leaves_use_ri_inside_eup_myeon():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    AdminUnit.__table__.create(engine)
    db = sessionmaker(engine)()
    for row in parse_legal_dong(legal_zip(SAMPLE)):
        db.add(AdminUnit(**row))
    db.commit()
    leaves = legal_leaves(db, ["41820", "41110", "41111", "41113"])
    codes = [(r["sigunguCd"], r["bjdongCd"]) for r in leaves]
    assert ("41820", "25021") in codes and ("41820", "25022") in codes
    assert ("41820", "25000") not in codes  # the 읍 itself has 리 below it
    assert ("41111", "10100") in codes


def test_scope_keeps_legacy_rows_for_the_original_region_only():
    jeonju = Scope("52110", "전북특별자치도 전주시", "전주시", frozenset({"cell_1_1"}), ("52111", "52113"), ("35011",), None, None, None, "READY", True,
                   foreign_legal=("41111", "41113"), foreign_sgis=("31011",))
    suwon = Scope("41110", "경기도 수원시", "수원시", frozenset({"cell_9_9"}), ("41110", "41111", "41113"), ("31011",), None, None, None, "PARTIAL", False)
    assert jeonju.owns_legal("5211110100") and jeonju.owns_legal("4511110100")  # unclaimed legacy code
    assert not jeonju.owns_legal("4111110100")  # claimed by 수원시
    assert suwon.owns_legal("4111110100") and not suwon.owns_legal("5211110100")
    assert suwon.owns_complex(None, "cell_9_9") and not suwon.owns_complex(None, "cell_1_1")
    assert suwon.owns_sgis("3101151000") and not suwon.owns_sgis("3501151000")
    assert jeonju.owns_sgis("3501151000") and not jeonju.owns_sgis("3101151000")


def test_short_name():
    assert short_name("전북특별자치도 전주시") == "전주시"
    assert short_name("경기도 수원시") == "수원시"
    assert short_name("세종특별자치시") == "세종특별자치시"


def test_grid_cell_geometry():
    assert regions.grid_cell_geometry("cell_968500_1762000") == (968500.0, 1762000.0, 969000.0, 1762500.0)
    assert regions.grid_cell_geometry("bad") is None


def test_list_codes_use_districts_instead_of_the_city():
    assert regions.list_codes(["41110", "41111", "41113"]) == ["41111", "41113"]
    assert regions.list_codes(["52111", "52113"]) == ["52111", "52113"]
    assert regions.list_codes(["11110"]) == ["11110"]
    assert regions.list_codes(["36110"]) == ["36110"]


def test_sgis_district_names_get_their_province():
    from app.national import full_name
    assert full_name("경기도", "수원시 장안구") == "경기도 수원시 장안구"
    assert full_name("세종특별자치시", "세종특별자치시") == "세종특별자치시"
    assert full_name("전북특별자치도", "전북특별자치도 전주시 완산구") == "전북특별자치도 전주시 완산구"
    assert full_name(None, "종로구") == "종로구"
    rows = [{"adm_code": "31011", "adm_name": full_name("경기도", "수원시 장안구")}, {"adm_code": "31012", "adm_name": full_name("경기도", "수원시 권선구")}]
    assert match_sgis("경기도 수원시", rows) == ["31011", "31012"]


def test_kapt_csrf_token_in_any_attribute_order():
    from app.kapt import csrf_token
    assert csrf_token('<meta id="_csrf" name="_csrf" content="abc-123" />') == "abc-123"
    assert csrf_token('<meta name="_csrf" content="x1">') == "x1"
    assert csrf_token('<meta content="y2" name="_csrf">') == "y2"
    assert csrf_token('<meta name="_csrf_header" content="X-CSRF-TOKEN" />') is None
