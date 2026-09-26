import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import official
from app.cache import ExternalError
from app.kapt import ApartmentComplex
from app.models import DataSource, RawDataAsset, Region
from app.official import BuildingRegister, approval_year_of, collect_register, normalize_register, register_pnu


def make_db():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    for table in [DataSource.__table__, RawDataAsset.__table__, Region.__table__, BuildingRegister.__table__, ApartmentComplex.__table__]:
        table.create(engine)
    db = sessionmaker(engine)()
    db.add(DataSource(id='building_official', category='x', name='건축물대장', organization='국토교통부', source_url='u', source_type='OFFICIAL',
                      status='NEEDS_API_KEY', reference_period='-', geographic_coverage='전주시', raw_row_count=0, normalized_row_count=0,
                      quality='-', limitation='-'))
    for code in ('5211310300', '5211310400'):
        db.add(Region(code=code, sigungu_code=code[:5], bjdong_code=code[5:], name=f'전주시 {code}', source='t', version='1', raw_record={}))
    db.commit()
    return db


def test_register_fields_keep_blank_as_missing_and_read_energy_grades():
    r = normalize_register({'totArea': '12,000', 'grndFlrCnt': '15', 'ugrndFlrCnt': '', 'strctCdNm': '철근콘크리트구조',
                            'useAprDay': '20190315', 'engrGrade': '1+', 'gnBldGrade': ' ', 'mainPurpsCdNm': '공동주택'})
    assert r['gross_floor_area_m2'] == 12000 and r['floors'] == 15
    assert r['underground_floors'] is None  # blank is missing, never 0
    assert r['structure'] == '철근콘크리트구조' and r['energy_grade'] == '1+'
    assert r['green_grade'] is None
    assert r['legal_far_limit'] is None
    assert approval_year_of(r['approval_date']) == 2019
    assert approval_year_of('') is None and approval_year_of('00000000') is None


def test_pnu_uses_cadastral_land_type_codes():
    assert register_pnu({'sigunguCd': '52113', 'bjdongCd': '10300', 'platGbCd': '0', 'bun': '718', 'ji': '0'}) == '5211310300107180000'
    assert register_pnu({'sigunguCd': '52113', 'bjdongCd': '10300', 'platGbCd': '1', 'bun': '12', 'ji': '3'}) == '5211310300200120003'


def test_full_collection_pages_every_dong_and_links_apartment_parcels(monkeypatch, tmp_path):
    db = make_db()
    db.add(ApartmentComplex(kapt_code='A1', snapshot_month='202512', name='단지', bjd_code='5211310300', bun='0718', ji='0000',
                            longitude=127.1, latitude=35.8, households=500, grid_id='cell_9', detail_collected=True, summary_json={}, detail_json={}))
    db.commit()
    monkeypatch.setattr(official, 'official_spec', lambda *a: {'host': 'apis.data.go.kr', 'basePath': '/1613000/BldRgstHubService', 'paths': {'/getBrTitleInfo': {}}})
    monkeypatch.setenv('DATA_GO_KR_SERVICE_KEY', 'valid-test-key')
    body = tmp_path / 'b.json'
    body.write_text('{}')
    calls = []

    def fake_request(url, params):
        calls.append((params['bjdongCd'], params['pageNo'], params['numOfRows']))
        if params['bjdongCd'] == '10300':
            rows = [{'mgmBldrgstPk': f'P{params["pageNo"]}-{i}', 'sigunguCd': '52113', 'bjdongCd': '10300', 'platGbCd': '0', 'bun': '0718', 'ji': '0000',
                     'totArea': '1000', 'useAprDay': '20200101', 'mainPurpsCdNm': '공동주택'} for i in range(100 if params['pageNo'] == 1 else 20)]
            return {'id': f'r{len(calls)}', 'path': str(body), 'url': url}, (rows, 120)
        return {'id': f'r{len(calls)}', 'path': str(body), 'url': url}, ([], 0)

    monkeypatch.setattr(official, '_register_request', fake_request)
    result = collect_register(db, 'full')
    assert calls == [('10300', 1, 100), ('10300', 2, 100), ('10400', 1, 100)]
    assert result['rows'] == 120 and result['total'] == 120
    assert result['linked'] == 120  # the K-apt complex on the same parcel gives the grid (no PostGIS needed)
    item = db.scalar(select(BuildingRegister).limit(1))
    assert item.grid_id == 'cell_9' and item.approval_year == 2020 and item.parcel_code == '5211310300107180000'
    source = db.get(DataSource, 'building_official')
    assert source.status == 'COLLECTED' and source.normalized_row_count == 120


def test_unapproved_service_stops_with_an_auth_message(monkeypatch, tmp_path):
    db = make_db()
    monkeypatch.setattr(official, 'official_spec', lambda *a: {'host': 'apis.data.go.kr', 'basePath': '', 'paths': {'/getBrTitleInfo': {}}})
    monkeypatch.setenv('DATA_GO_KR_SERVICE_KEY', 'valid-test-key')

    def denied(url, params):
        raise ExternalError('API 인증 실패: 건축HUB 건축물대장(15134735) 활용신청 승인과 DATA_GO_KR_SERVICE_KEY를 확인하세요')

    monkeypatch.setattr(official, '_register_request', denied)
    with pytest.raises(ExternalError):
        collect_register(db, 'smoke')
    assert db.get(DataSource, 'building_official').status == 'NEEDS_API_APPROVAL'


def test_grid_register_summary_uses_known_values_only():
    from app.register_grid import map_properties, summarize
    rows = [
        {"grid_id": "g", "use": "공동주택", "gfa": 30000.0, "far_gfa": 24000.0, "approval_year": 1995, "energy_grade": None},
        {"grid_id": "g", "use": "제2종근린생활시설", "gfa": 10000.0, "far_gfa": 9000.0, "approval_year": 2015, "energy_grade": "1+"},
        {"grid_id": "g", "use": None, "gfa": None, "far_gfa": None, "approval_year": None, "energy_grade": None},
        {"grid_id": None, "use": "공동주택", "gfa": 99999.0, "far_gfa": 1.0, "approval_year": 2000, "energy_grade": None},
    ]
    g = summarize(rows)["g"]
    assert g["buildings"] == 3 and g["gfa_m2"] == 40000.0 and g["far_gfa_m2"] == 33000.0
    assert g["far_pct"] == 13.2  # 33,000 / 250,000
    assert g["residential_gfa_pct"] == 75.0 and g["dominant_use"] == "주거"
    assert g["old_gfa_pct"] == 75.0  # 1995 building: 30,000 of 40,000 dated m²
    assert map_properties(None)["reg_far_pct"] is None  # no register: missing, not 0
