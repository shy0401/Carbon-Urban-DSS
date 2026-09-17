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


def add_complex(db, code='A1'):
    db.add(ApartmentComplex(
        kapt_code=code, snapshot_month='202512', name=code, bjd_code='5211311600',
        bun='0718', ji='0000', longitude=127.15, latitude=35.85,
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
    assert first == {'requested': 1, 'normalized': 1, 'skipped': 0, 'empty': 0, 'failed': 0}
    assert second == {'requested': 0, 'normalized': 0, 'skipped': 1, 'empty': 0, 'failed': 0}
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
