import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.kapt import ApartmentComplex
from app.models import DataSource, EnergyMonthly, RawDataAsset
from app.kapt_energy import (
    ApartmentEnergyMonthly,
    ComplexGridMapping,
    collect_kapt_energy,
    parse_kapt_energy_response,
)
from app.main import CollectionInput


def response(item):
    return json.dumps({
        'response': {
            'header': {'resultCode': '00', 'resultMsg': 'NORMAL SERVICE'},
            'body': {'item': item},
        }
    }).encode()


def test_parser_supports_direct_item_and_keeps_zero_distinct_from_missing():
    parsed = parse_kapt_energy_response(response({
        'kaptCode': 'A1', 'reqDate': '202501',
        'helect': 0, 'elect': '12000', 'hgas': '', 'gas': None,
        'hheat': '3.5', 'heat': '900', 'hwaterHot': '-',
        'waterHot': '0', 'hwaterCool': '12.25', 'waterCool': '2500',
    }))
    row = parsed['rows'][0]
    assert parsed['provider_code'] == '00'
    assert row['electricity_quantity'] == 0.0
    assert row['electricity_amount_krw'] == 12000.0
    assert row['gas_quantity'] is None
    assert row['heating_quantity'] == 3.5
    assert row['hot_water_quantity'] is None
    assert row['hot_water_amount_krw'] == 0.0
    assert row['water_quantity'] == 12.25
    assert row['units'] == {
        'electricity_quantity': 'kWh', 'gas_quantity': 'm3',
        'heating_quantity': 'Mcal', 'hot_water_quantity': 'tonne',
        'water_quantity': 'm3', 'amounts': 'KRW',
    }


class StubClient:
    def __init__(self, body):
        self.body = body
        self.calls = []

    def get(self, provider, operation, url, params):
        self.calls.append(dict(params))
        return {'body': self.body, 'url': url, 'status': 200, 'id': 'upstream-cache-id', 'timestamp': 1}


def make_db():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    for table in [DataSource.__table__, RawDataAsset.__table__, EnergyMonthly.__table__, ApartmentComplex.__table__, ApartmentEnergyMonthly.__table__, ComplexGridMapping.__table__]:
        table.create(engine)
    return sessionmaker(engine)()


def add_complex(db, code='A1', households=None):
    db.add(ApartmentComplex(
        kapt_code=code, snapshot_month='202512', name=code, bjd_code='5211311600',
        bun='0718', ji='0000', longitude=127.15, latitude=35.85, households=households,
        grid_id='cell_1_1', detail_collected=True, summary_json={}, detail_json={},
    ))
    db.commit()


def test_smoke_collection_upserts_once_and_resumes_without_duplicate_call(tmp_path):
    db = make_db()
    add_complex(db)
    client = StubClient(response({'kaptCode': 'A1', 'reqDate': '202501', 'helect': '10'}))
    first = collect_kapt_energy(db, 2025, 'smoke', client=client, service_key='valid-test-key', data_dir=tmp_path)
    second = collect_kapt_energy(db, 2025, 'smoke', client=client, service_key='valid-test-key', data_dir=tmp_path)
    row = db.scalar(select(ApartmentEnergyMonthly))
    analysis_row = db.scalar(select(EnergyMonthly))
    mapping = db.get(ComplexGridMapping, 'A1')
    assert {k: first[k] for k in ('requested', 'normalized', 'skipped', 'empty', 'failed')} == {'requested': 1, 'normalized': 1, 'skipped': 0, 'empty': 0, 'failed': 0}
    assert {k: second[k] for k in ('requested', 'normalized', 'skipped', 'empty', 'failed')} == {'requested': 0, 'normalized': 0, 'skipped': 1, 'empty': 0, 'failed': 0}
    assert len(client.calls) == 1
    assert row.electricity_quantity == 10.0
    assert row.electricity_carbon_kg == pytest.approx(4.541)
    assert row.gas_quantity is None
    assert analysis_row.source == 'K-apt'
    assert analysis_row.energy_type == 'ELECTRICITY'
    assert analysis_row.usage_kwh == 10.0
    assert analysis_row.raw_record['quantity_unit'] == 'kWh'
    assert mapping.grid_id == 'cell_1_1'
    assert mapping.method == 'KAPT_POINT_PROJECT_GRID'
    assert db.scalar(select(func.count()).select_from(RawDataAsset)) == 1
    assert Path(db.scalar(select(RawDataAsset)).storage_location).is_file()


def test_full_scope_requires_a_recorded_smoke_success(tmp_path):
    db = make_db()
    add_complex(db)
    with pytest.raises(ValueError, match='smoke'):
        collect_kapt_energy(db, 2025, 'full', client=StubClient(response({})), service_key='valid-test-key', data_dir=tmp_path)


def test_collection_api_accepts_kapt_energy_with_explicit_scope():
    request = CollectionInput(
        datasets=['kapt_energy'], start_month='2025-01', end_month='2025-12',
        region='전주시', scope='smoke',
    )
    assert request.datasets == ['kapt_energy']
    assert request.scope == 'smoke'


def test_provider_success_000_and_nodata_03_are_not_errors():
    ok = json.dumps({'response': {'header': {'resultCode': '000', 'resultMsg': 'OK'}, 'body': {'item': {'kaptCode': 'A1', 'reqDate': '202501', 'helect': '100'}}}}).encode()
    assert parse_kapt_energy_response(ok)['rows'][0]['electricity_quantity'] == 100.0
    nodata = json.dumps({'response': {'header': {'resultCode': '03', 'resultMsg': 'NODATA_ERROR'}, 'body': {}}}).encode()
    assert parse_kapt_energy_response(nodata)['rows'] == []


def test_rate_limit_and_auth_codes_have_distinct_messages():
    from app.cache import ExternalError
    limit = json.dumps({'response': {'header': {'resultCode': '22'}, 'body': {}}}).encode()
    with pytest.raises(ExternalError, match='호출 한도'):
        parse_kapt_energy_response(limit)
    auth = json.dumps({'response': {'header': {'resultCode': '30'}, 'body': {}}}).encode()
    with pytest.raises(ExternalError, match='인증 실패'):
        parse_kapt_energy_response(auth)


GATEWAY_04 = json.dumps({'OpenAPI_ServiceResponse': {'cmmMsgHeader': {'errMsg': 'HTTP_ERROR', 'returnAuthMsg': 'HTTP 에러', 'returnReasonCode': '04'}}}).encode()


def test_gateway_error_envelope_is_classified_not_parsed_as_empty():
    from app.kapt_energy import TransientProviderError
    from app.cache import ExternalError
    with pytest.raises(TransientProviderError, match='provider_code=04'):
        parse_kapt_energy_response(GATEWAY_04)
    xml = b'<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</errMsg><returnReasonCode>30</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>'
    with pytest.raises(ExternalError, match='인증 실패'):
        parse_kapt_energy_response(xml)


def test_all_zero_month_is_not_reported_and_never_becomes_zero_usage(tmp_path):
    db = make_db()
    add_complex(db, households=300)
    zero = {'kaptCode': 'A1', 'reqDate': '202501', 'helect': 0, 'elect': 0, 'hgas': 0, 'gas': 0, 'hheat': 0, 'heat': 0, 'hwaterHot': 0, 'waterHot': 0, 'hwaterCool': 0, 'waterCool': 0}
    stats = collect_kapt_energy(db, 2025, 'smoke', client=StubClient(response(zero)), service_key='valid-test-key', data_dir=tmp_path)
    row = db.scalar(select(ApartmentEnergyMonthly))
    assert stats['not_reported'] == 1 and stats['normalized'] == 0
    assert row.quality_status == 'NOT_REPORTED'
    assert row.electricity_quantity is None and row.electricity_amount_krw is None and row.electricity_carbon_kg is None
    assert db.scalar(select(func.count()).select_from(EnergyMonthly)) == 0


def test_implausibly_small_electricity_is_suspect_and_excluded(tmp_path):
    db = make_db()
    add_complex(db, households=160)
    item = {'kaptCode': 'A1', 'reqDate': '202501', 'helect': '15', 'hgas': '1', 'hheat': '1'}
    stats = collect_kapt_energy(db, 2025, 'smoke', client=StubClient(response(item)), service_key='valid-test-key', data_dir=tmp_path)
    row = db.scalar(select(ApartmentEnergyMonthly))
    assert stats['suspect'] == 1
    assert row.quality_status == 'SUSPECT' and '비현실적' in row.raw_record['quality_reason']
    assert row.electricity_quantity == 15.0 and row.electricity_carbon_kg is None
    assert db.scalar(select(func.count()).select_from(EnergyMonthly)) == 0


class SequenceClient(StubClient):
    """Returns the given bodies in order and records forgotten (retried) cache entries."""
    def __init__(self, bodies):
        super().__init__(bodies[0])
        self.bodies = list(bodies)
        self.forgotten = 0

    def get(self, provider, operation, url, params):
        self.calls.append(dict(params))
        body = self.bodies.pop(0) if len(self.bodies) > 1 else self.bodies[0]
        return {'body': body, 'url': url, 'status': 200, 'id': f'id-{len(self.calls)}', 'timestamp': 1}

    def forget(self, result):
        self.forgotten += 1


def test_temporary_gateway_error_is_retried_then_stored(tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(time, 'sleep', lambda seconds: None)
    db = make_db()
    add_complex(db, households=300)
    client = SequenceClient([GATEWAY_04, response({'kaptCode': 'A1', 'reqDate': '202501', 'helect': '60000'})])
    stats = collect_kapt_energy(db, 2025, 'smoke', client=client, service_key='valid-test-key', data_dir=tmp_path)
    assert stats['normalized'] == 1 and stats['failed'] == 0
    assert client.forgotten == 1 and len(client.calls) == 2
    assert db.scalar(select(EnergyMonthly)).usage_kwh == 60000.0


def test_persistent_gateway_error_marks_month_failed_and_continues(tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(time, 'sleep', lambda seconds: None)
    db = make_db()
    add_complex(db, households=300)
    stats = collect_kapt_energy(db, 2025, 'smoke', client=SequenceClient([GATEWAY_04]), service_key='valid-test-key', data_dir=tmp_path)
    row = db.scalar(select(ApartmentEnergyMonthly))
    assert stats['failed'] == 1
    assert row.quality_status == 'FAILED' and 'provider_code=04' in row.provider_code
    # A FAILED month is requested again on the next run.
    retry = collect_kapt_energy(db, 2025, 'smoke', client=StubClient(response({'kaptCode': 'A1', 'reqDate': '202501', 'helect': '60000'})), service_key='valid-test-key', data_dir=tmp_path)
    assert retry['requested'] == 1 and retry['normalized'] == 1


def test_rows_stored_by_older_versions_are_reclassified(tmp_path):
    from app.kapt_energy import reclassify_existing
    db = make_db()
    add_complex(db, households=300)
    db.add(ApartmentEnergyMonthly(id='A1:202501:K-apt', complex_code='A1', year_month='202501', source='K-apt',
                                  electricity_quantity=0.0, quality_status='SUCCESS', units={},
                                  raw_record={'kaptCode': 'A1', 'helect': 0, 'hgas': 0}))
    db.add(EnergyMonthly(source='K-apt', sigungu_code='52113', bjdong_code='11600', lot_type='0', bun='0718', ji='0000',
                         use_ym='202501', energy_type='ELECTRICITY', usage_kwh=0.0, grid_id='cell_1_1', raw_record={}))
    db.commit()
    assert reclassify_existing(db) == {'NOT_REPORTED': 1}
    assert db.get(ApartmentEnergyMonthly, 'A1:202501:K-apt').quality_status == 'NOT_REPORTED'
    assert db.scalar(select(func.count()).select_from(EnergyMonthly)) == 0
