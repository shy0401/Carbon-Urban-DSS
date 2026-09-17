import calendar
import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.kma_asos import (
    WeatherDailyObservation, WeatherMonthlyObservation, aggregate_asos_months,
    backfill_weather_observations, collect_asos, parse_asos_response,
)
from app.models import DataSource, RawDataAsset, WeatherMonthly


def test_asos_parser_preserves_zero_and_maps_missing_markers_to_none():
    body = json.dumps({'response': {'header': {'resultCode': '00'}, 'body': {
        'totalCount': 1, 'items': {'item': [{
            'stnId': '146', 'tm': '2025-01-01', 'avgTa': '', 'minTa': '0',
            'maxTa': '-', 'sumRn': '0.0', 'avgRhm': '71.2', 'sumSsHr': None,
            'sumGsr': '8.5', 'avgWs': '1.6',
        }]}
    }}}).encode()
    parsed = parse_asos_response(body)
    row = parsed['rows'][0]
    assert parsed['total_count'] == 1
    assert row['station_id'] == '146'
    assert row['observed_date'] == '2025-01-01'
    assert row['avg_temperature_c'] is None
    assert row['min_temperature_c'] == 0.0
    assert row['max_temperature_c'] is None
    assert row['precipitation_mm'] == 0.0
    assert row['avg_humidity_pct'] == 71.2
    assert row['sunshine_hours'] is None


def test_monthly_aggregation_marks_only_complete_months_as_official():
    rows = []
    for day in range(1, calendar.monthrange(2025, 1)[1] + 1):
        rows.append({
            'station_id': '146', 'observed_date': f'2025-01-{day:02d}',
            'avg_temperature_c': 2.0, 'min_temperature_c': -1.0,
            'max_temperature_c': 5.0, 'precipitation_mm': 0.0,
            'avg_humidity_pct': 60.0, 'sunshine_hours': 4.0,
            'solar_radiation_mj_m2': 8.0, 'avg_wind_speed_m_s': 1.5,
        })
    rows.append({**rows[0], 'observed_date': '2025-02-01'})
    monthly = {row['use_ym']: row for row in aggregate_asos_months(rows)}
    january = monthly['202501']
    february = monthly['202502']
    assert january['valid_day_count'] == january['expected_day_count'] == 31
    assert january['completeness_ratio'] == 1.0
    assert january['official_asos_complete'] is True
    assert january['precipitation_sum_mm'] == 0.0
    assert january['sunshine_sum_hours'] == 124.0
    assert february['valid_day_count'] == 1
    assert february['expected_day_count'] == 28
    assert february['official_asos_complete'] is False


class StubClient:
    def __init__(self, body):
        self.body = body
        self.calls = 0

    def get(self, provider, operation, url, params):
        self.calls += 1
        return {'body': self.body, 'status': 200, 'url': url}


def test_collection_preserves_fallback_and_promotes_complete_asos_month(tmp_path):
    engine = create_engine('sqlite+pysqlite:///:memory:')
    for table in [DataSource.__table__, RawDataAsset.__table__, WeatherMonthly.__table__, WeatherDailyObservation.__table__, WeatherMonthlyObservation.__table__]:
        table.create(engine)
    db = sessionmaker(engine)()
    db.add(WeatherMonthly(
        use_ym='202501', provider='Open-Meteo / ERA5-Land', source_type='FALLBACK',
        latitude=35.82, longitude=127.14, mean_temperature=1.0, min_temperature=-2.0,
        max_temperature=4.0, precipitation=10.0, hdd=527.0, cdd=0.0,
        days_observed=31, expected_days=31,
    ))
    db.commit()
    assert backfill_weather_observations(db) == 1
    items = [{
        'stnId': '146', 'tm': f'2025-01-{day:02d}', 'avgTa': '2', 'minTa': '-1',
        'maxTa': '5', 'sumRn': '0', 'avgRhm': '60', 'sumSsHr': '4',
        'sumGsr': '8', 'avgWs': '1.5',
    } for day in range(1, 32)]
    body = json.dumps({'response': {'header': {'resultCode': '00'}, 'body': {'totalCount': 31, 'items': {'item': items}}}}).encode()
    result = collect_asos(db, 2025, 'smoke', client=StubClient(body), service_key='valid-test-key', data_dir=tmp_path)
    effective = db.get(WeatherMonthly, '202501')
    observations = list(db.scalars(select(WeatherMonthlyObservation).where(WeatherMonthlyObservation.use_ym == '202501')))
    assert result == {'daily_rows': 31, 'monthly_rows': 1, 'complete_months': 1}
    assert effective.provider == 'KMA ASOS station146'
    assert {row.source_type for row in observations} == {'FALLBACK', 'OFFICIAL'}
