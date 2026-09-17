import json
import shutil
from pathlib import Path

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.cache import CachedClient
from app.kapt import (
    ApartmentComplex,
    _coordinates,
    candidate_energy_parcels,
    collect_kapt,
    fetch_monthly_energy,
    merge_energy_coordinates,
)
from app.models import EnergyMonthly, TestbedSector as Sector


def test_kapt_projection_matches_published_sample():
    lon, lat = _coordinates({"x": 212523.3695, "y": 258284.408})
    assert lon == 127.1393924972
    assert abs(lat - 35.8245953543) < 3e-10


class StubCache:
    def __init__(self, body):
        self.body = body
        self.params = None

    def get(self, provider, operation, url, params):
        self.params = params
        return {"body": self.body}


def test_monthly_energy_parses_json_and_omits_cost_fields():
    body = json.dumps({"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": {"kaptCode": "A1", "reqDate": "202501", "helect": "10", "hgas": "2", "hheat": "3", "hwaterHot": "4", "electCost": "99999"}}}}}).encode()
    cache = StubCache(body)
    rows = fetch_monthly_energy("A1", "202501", "registered-test-key", cache)
    assert rows[0]["helect"] == "10"
    assert rows[0]["helect_unit"] == "kWh"
    assert "electCost" not in rows[0]
    assert cache.params["serviceKey"] == "registered-test-key"


def test_monthly_energy_xml_fallback():
    body = b"<response><header><resultCode>00</resultCode></header><body><items><item><kaptCode>A1</kaptCode><reqDate>202501</reqDate><helect>10</helect></item></items></body></response>"
    rows = fetch_monthly_energy("A1", "202501", "registered-test-key", StubCache(body))
    assert rows[0]["helect"] == "10"
    assert rows[0]["hgas"] is None


def test_monthly_energy_accepts_official_direct_item_and_preserves_key_encoding():
    body = json.dumps({"response": {"header": {"resultCode": "00"}, "body": {"item": {"kaptCode": "A1", "reqDate": "202501", "helect": "10"}}}}).encode()
    cache = StubCache(body)
    rows = fetch_monthly_energy("A1", "202501", "abc%2Bdef", cache)
    assert rows[0]["helect"] == "10"
    assert cache.params["serviceKey"] == "abc%2Bdef"


def test_collect_kapt_uses_cached_raw_files_in_offline_mode(tmp_path, monkeypatch):
    source = Path(__file__).parents[2] / "data" / "raw" / "research"
    for path in list(source.glob("kapt_jeonju_*_202512.json")) + list(source.glob("kapt_detail_*.json")):
        shutil.copy2(path, tmp_path / path.name)
    calls = []

    def handler(request):
        calls.append(request)
        raise AssertionError("offline cached collection attempted network access")

    monkeypatch.setenv("DEMO_OFFLINE_MODE", "true")
    monkeypatch.setattr("app.kapt._client", lambda target: CachedClient(tmp_path / "cache", httpx.Client(transport=httpx.MockTransport(handler)), min_interval=0))
    result = collect_kapt(raw_dir=tmp_path)
    assert result["summary_rows"] == 364
    assert result["detail_rows"] == len(list(tmp_path.glob("kapt_detail_*.json")))
    retained = collect_kapt(raw_dir=tmp_path, detail_codes=result['detail_codes'][:1])
    assert retained['detail_rows'] == result['detail_rows']
    assert calls == []


def test_exact_parcel_candidates_and_energy_coordinate_match():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    ApartmentComplex.__table__.create(engine)
    EnergyMonthly.__table__.create(engine)
    Sector.__table__.create(engine)
    Session = sessionmaker(engine)
    with Session() as db:
        complex_row = ApartmentComplex(
            kapt_code="A56121109", snapshot_month="202512", name="호성동 엘지동아",
            bjd_code="5211311600", bun="0718", ji="0000", parcel_address="호성동1가 718",
            longitude=127.1521907584, latitude=35.8552530425, grid_id="cell_966000_1753000",
            gross_floor_area_m2=94993.33, detail_collected=True, summary_json={}, detail_json={},
        )
        db.add(complex_row)
        db.add(Sector(id="prototype", grid_id="cell_966000_1753000", name="LG동아", reason="test", candidates=[], metadata_json={}))
        db.add(EnergyMonthly(
            id=1, source="MOLIT", sigungu_code="52113", bjdong_code="11600", bun="0718", ji="0000",
            use_ym="202501", energy_type="ELECTRICITY", usage_kwh=100.0, raw_record={},
        ))
        db.add(EnergyMonthly(
            id=2, source="MOLIT", sigungu_code="52113", bjdong_code="11600", lot_type="1", bun="0718", ji="0000",
            use_ym="202501", energy_type="ELECTRICITY", usage_kwh=10.0, grid_id="stale-grid", raw_record={},
        ))
        db.commit()
        candidates = candidate_energy_parcels(db, 3)
        assert candidates[0]["sigunguCd"] == "52113"
        assert candidates[0]["bjdongCd"] == "11600"
        assert candidates[0]["parcel_match_status"] == "EXACT_SINGLE_COMPLEX"
        result = merge_energy_coordinates(db)
        energy = db.get(EnergyMonthly, 1)
        mountain = db.get(EnergyMonthly, 2)
        sector = db.get(Sector, "prototype")
        assert result["matched"] == 1
        assert energy.match_method == "KAPT_COMPLEX_CENTROID"
        assert energy.raw_record["matched_gross_floor_area_m2"] == 94993.33
        assert mountain.grid_id is None
        assert mountain.match_method == "UNMATCHED_KAPT_MOUNTAIN_PARCEL"
        assert sector.metadata_json["baseline_floor_area_m2"] == 94993.33
