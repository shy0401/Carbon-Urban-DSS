import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.energy_parcels import HUB, collect_energy_all, parcel_pnu, summarize_parcels
from app.models import EnergyMonthly


def make_db():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    EnergyMonthly.__table__.create(engine)
    return sessionmaker(engine)()


def page(rows, total):
    return json.dumps({'response': {'header': {'resultCode': '00', 'resultMsg': 'NORMAL SERVICE.'},
                                    'body': {'items': {'item': rows}, 'totalCount': total, 'numOfRows': 100, 'pageNo': 1}}}).encode()


class FakeClient:
    """Answers per (operation, useYm, pageNo); records every request."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def get(self, provider, operation, url, params):
        assert params['bun'] == '' and params['ji'] == ''  # the whole 법정동 at once
        self.calls.append((operation, params['useYm'], params['pageNo']))
        rows, total = self.answers.get((operation, params['useYm'], params['pageNo']), ([], 0))
        return {'body': page(rows, total), 'status': 200}


def row(bun, ji, qty, ym='202401', lot='0'):
    return {'useYm': ym, 'sigunguCd': '52113', 'bjdongCd': '11600', 'platGbCd': lot, 'bun': bun, 'ji': ji, 'useQty': qty, 'platPlc': f'호성동1가 {bun}-{ji}'}


def test_pnu_follows_the_cadastral_land_type():
    assert parcel_pnu('52113', '11600', '0', '11', '1') == '5211311600100110001'
    assert parcel_pnu('52113', '11600', '1', '0718', '0000') == '5211311600207180000'  # 산 → 2


def test_city_wide_collection_pages_through_every_parcel_and_keeps_missing_months_missing():
    db = make_db()
    # an earlier K-apt value for one parcel is replaced by the building meter and kept for comparison
    db.add(EnergyMonthly(source='K-apt', sigungu_code='52113', bjdong_code='11600', lot_type='0', bun='0016', ji='0000',
                         use_ym='202401', energy_type='ELECTRICITY', usage_kwh=999.0, raw_record={}))
    db.commit()
    elec_page1 = [row('0011', '0011', 67)] + [row(f'{i:04d}', '0000', 100 + i) for i in range(100, 199)]
    elec_page2 = [row('0016', '0000', 12404), row('0016', '0000', 6)]  # the same 지번 twice → one parcel, summed
    client = FakeClient({
        ('getBeElctyUsgInfo', '202401', 1): (elec_page1, 102),
        ('getBeElctyUsgInfo', '202401', 2): (elec_page2, 102),
        ('getBeGasUsgInfo', '202401', 1): ([row('0011', '0011', 0)], 1),
    })
    stats = collect_energy_all(db, 2024, client=client, service_key='k', months=['202401', '202402'],
                               regions=[{'sigunguCd': '52113', 'bjdongCd': '11600', 'name': '호성동1가'}])
    assert ('getBeElctyUsgInfo', '202401', 2) in client.calls and stats['requests'] == 5  # 2+1 pages for Jan, 1+1 for Feb
    electricity = {(r.bun, r.ji): r for r in db.scalars(select(EnergyMonthly).where(EnergyMonthly.energy_type == 'ELECTRICITY'))}
    assert len(electricity) == 101
    replaced = electricity[('0016', '0000')]
    assert replaced.usage_kwh == 12410 and replaced.source == HUB
    assert replaced.raw_record['replaced_source'] == 'K-apt' and replaced.raw_record['merged_rows'] == 2
    gas = db.scalars(select(EnergyMonthly).where(EnergyMonthly.energy_type == 'GAS')).all()
    assert len(gas) == 1 and gas[0].usage_kwh == 0  # a metered 0 stays 0
    assert not db.scalars(select(EnergyMonthly).where(EnergyMonthly.use_ym == '202402')).all()  # empty month: no rows, not 0
    again = collect_energy_all(db, 2024, client=client, service_key='k', months=['202401'],
                               regions=[{'sigunguCd': '52113', 'bjdongCd': '11600'}])
    assert again['inserted'] == 0 and again['updated'] == 0


def test_grid_totals_use_complete_parcels_and_register_area_for_intensity():
    parcels = [
        {'pnu': 'A', 'energy_type': 'ELECTRICITY', 'months': 12, 'kwh': 120000.0},
        {'pnu': 'B', 'energy_type': 'ELECTRICITY', 'months': 12, 'kwh': 600000.0},   # 600 kWh/m² on 1,000 m²: kept (a shop)
        {'pnu': 'C', 'energy_type': 'ELECTRICITY', 'months': 7, 'kwh': 5000.0},      # partial year: not in totals
        {'pnu': 'D', 'energy_type': 'ELECTRICITY', 'months': 12, 'kwh': 10.0},       # 0.01 kWh/m²: partial meter
        {'pnu': 'A', 'energy_type': 'GAS', 'months': 12, 'kwh': 80000.0},
        {'pnu': 'Z', 'energy_type': 'ELECTRICITY', 'months': 12, 'kwh': 1.0},        # no grid: ignored
    ]
    grid = summarize_parcels(parcels, {'A': 'g', 'B': 'g', 'C': 'g', 'D': 'g'}, {'A': 3000.0, 'B': 1000.0, 'D': 1000.0})['g']
    assert grid['parcels'] == 4 and grid['electricity_complete'] == 3
    assert grid['electricity_kwh'] == 720010.0 and grid['gas_kwh'] == 80000.0
    assert grid['area_parcels'] == 2 and grid['kwh_per_m2'] == 180.0 and grid['suspect'] == 1


def test_jeonbuk_months_before_the_rename_use_the_old_sigungu_code():
    from app.energy_parcels import request_sigungu
    assert request_sigungu('52111', '202310') == '45111' and request_sigungu('52113', '202001') == '45113'
    assert request_sigungu('52111', '202311') == '52111' and request_sigungu('41111', '202101') == '41111'


def test_map_properties_add_building_gas_carbon_with_the_assumed_factor_and_keep_missing_as_none():
    from app.emissions import GAS_FACTOR
    from app.energy_parcels import map_properties
    item = {"parcels": 5, "electricity_kwh": 100_000.0, "gas_kwh": 50_000.0, "electricity_complete": 4, "gas_complete": 3,
            "area_m2": 1000.0, "area_parcels": 2, "kwh_per_m2": 50.0, "suspect": 0}
    props = map_properties(item, 0.4781)
    assert props["bldg_carbon_t"] == round(100_000 * 0.4781 / 1000, 1)
    assert props["bldg_gas_carbon_t"] == round(50_000 * GAS_FACTOR / 1000, 1)
    assert map_properties(dict(item, gas_kwh=None), 0.4781)["bldg_gas_carbon_t"] is None   # no gas observed: missing, not 0
    assert map_properties(None, 0.4781)["bldg_gas_carbon_t"] is None
