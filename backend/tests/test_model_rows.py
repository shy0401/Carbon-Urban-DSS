from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.kapt import ApartmentComplex
from app.model_service import model_rows
from app.models import EnergyMonthly, WeatherMonthly


def make_db():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    for table in (EnergyMonthly.__table__, WeatherMonthly.__table__, ApartmentComplex.__table__):
        table.create(engine)
    return sessionmaker(engine)()


def complex_(code, area, households, approval='2005-03-01'):
    return ApartmentComplex(kapt_code=code, snapshot_month='202509', name=code, gross_floor_area_m2=area, households=households,
                            approval_date=approval, summary_json={}, detail_collected=False)


def energy(grid, code, month, kwh, typ='ELECTRICITY', bun='0001'):
    return EnergyMonthly(source='국토교통부 건축HUB', sigungu_code='52113', bjdong_code='10100', lot_type='0', bun=bun, ji='0000',
                         use_ym=f'2025{month:02d}', energy_type=typ, usage_kwh=kwh, grid_id=grid,
                         raw_record={'kapt_code': code, 'matched_gross_floor_area_m2': 152757779.62 if code == 'BAD' else None})


def test_model_rows_use_the_same_plausible_parcels_for_energy_and_floor_area():
    db = make_db()
    db.add_all([
        complex_('A', 30000.0, 300, '2005-03-01'),   # 100 m²/세대, 25,000 kWh/월 → 1,000 kWh/세대·년
        complex_('B', 10000.0, 100, '1995-06-01'),
        complex_('BAD', 152757779.62, 500),          # published floor area typing error
        complex_('PART', 20000.0, 200),              # only 11 months observed
        complex_('LOW', 20000.0, 400),               # 100 kWh/월 for 400 세대: common-area meter only
    ])
    for month in range(1, 13):
        db.add(WeatherMonthly(use_ym=f'2025{month:02d}', hdd=100.0 - month, cdd=float(month), provider='test', source_type='OBSERVED', latitude=35.8, longitude=127.1, days_observed=30, expected_days=30))
        db.add(energy('g1', 'A', month, 25000.0, bun='0001'))
        db.add(energy('g1', 'B', month, 10000.0, bun='0002'))
        db.add(energy('g1', 'LOW', month, 100.0, bun='0003'))
        db.add(energy('g2', 'BAD', month, 50000.0, bun='0004'))
        if month < 12:
            db.add(energy('g3', 'PART', month, 20000.0, bun='0005'))
    db.commit()
    rows = model_rows(db, 2025, 'ELECTRICITY')
    assert {r['grid_id'] for r in rows} == {'g1'} and len(rows) == 12
    first = rows[0]
    assert first['usage_kwh'] == 35000.0 and first['floor_area_m2'] == 40000.0 and first['parcels'] == 2
    assert first['area_per_household'] == 100.0
    assert first['age'] == round(2025 - (30000 * 2005 + 10000 * 1995) / 40000, 1)
    assert first['hdd'] == 99.0 and first['cdd'] == 1.0


def test_validation_reports_intensity_r2_next_to_total_r2():
    from app.modeling import fit_candidates
    rows = []
    for g in range(12):
        area = 10000.0 * (g + 1)
        intensity = 3.0 + (g % 3) * 0.2
        for month in range(1, 13):
            rows.append(dict(grid_id=f'g{g}', spatial_block=str(g // 3), use_ym=f'2025{month:02d}', usage_kwh=area * intensity * (1 + month / 24),
                             floor_area_m2=area, month_sin=0.0, month_cos=float(month), hdd=None, cdd=None, area_per_household=90.0 + g, age=10.0))
    result = fit_candidates(rows)
    assert result['validated']
    baseline = result['models'][0]['metrics']
    assert baseline['r2'] > baseline['intensity_r2']  # the total R² is flattered by floor area alone
