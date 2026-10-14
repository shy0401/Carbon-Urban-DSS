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


def test_an_empty_provider_answer_is_retried_on_a_fresh_connection_not_failed(monkeypatch):
    """data.go.kr sometimes answers HTTP 200 with an empty body (10/10 night: 수원 2020·2021, 완주 2020·2022·2024 stopped on one
    page). That is never a real "no data" answer (no data is resultCode 03), so the page is asked again like 04 HTTP_ERROR."""
    import app.energy_parcels as ep
    monkeypatch.setattr(ep.time, 'sleep', lambda s: None)

    class Flaky(FakeClient):
        def __init__(self, answers, empty_times):
            super().__init__(answers)
            self.empty_times, self.forgotten, self.resets = empty_times, 0, 0

        def get(self, provider, operation, url, params):
            if operation == 'getBeElctyUsgInfo' and self.empty_times:
                self.empty_times -= 1
                self.calls.append((operation, params['useYm'], params['pageNo']))
                return {'body': b'', 'status': 200, 'id': 'x'}
            return super().get(provider, operation, url, params)

        def forget(self, result):
            self.forgotten += 1

        def reset_connection(self):
            self.resets += 1

    db = make_db()
    client = Flaky({('getBeElctyUsgInfo', '202401', 1): ([row('0011', '0011', 67)], 1)}, empty_times=2)
    stats = collect_energy_all(db, 2024, client=client, service_key='k', months=['202401'],
                               regions=[{'sigunguCd': '52113', 'bjdongCd': '11600'}])
    assert stats['inserted'] == 1 and client.forgotten == 2 and client.resets == 2
    assert db.scalars(select(EnergyMonthly)).one().usage_kwh == 67

    # still empty after every retry: the year stops with a provider error (the run moves on to the next year)
    from app.cache import ExternalError
    import pytest
    always = Flaky({}, empty_times=99)
    with pytest.raises(ExternalError, match='일시 오류'):
        collect_energy_all(make_db(), 2024, client=always, service_key='k', months=['202401'],
                           regions=[{'sigunguCd': '52113', 'bjdongCd': '11600'}])


def _hub_year(db, sg, bd, bun, ji, kwh_per_month, year=2025, energy_type='ELECTRICITY'):
    for m in range(1, 13):
        db.add(EnergyMonthly(source=HUB, sigungu_code=sg, bjdong_code=bd, lot_type='0', bun=bun, ji=ji, use_ym=f'{year}{m:02d}',
                             energy_type=energy_type, usage_kwh=kwh_per_month, raw_record={}))


def _parcel_db():
    from app.energy_parcels import ParcelGrid, _GRID_CACHE, _PARCEL_GRID
    _GRID_CACHE.clear(); _PARCEL_GRID.clear()
    db = make_db()
    ParcelGrid.__table__.create(db.get_bind())
    return db, ParcelGrid


def test_a_region_map_reads_only_its_cells_with_the_same_values_and_another_region_collecting_keeps_its_cache():
    """2026-10-14: the first 지도 분석 after a restart took 118 s because every region's 건축HUB year was summed
    (and again whenever any region was being collected). A region's cells now give the same numbers alone."""
    from app.energy_parcels import grid_building_energy
    db, ParcelGrid = _parcel_db()
    db.add_all([ParcelGrid(pnu='5211311600100110000', grid_id='g1'), ParcelGrid(pnu='5271025000100050000', grid_id='g1'),  # 완주 lot in a 전주 cell
                ParcelGrid(pnu='5271025000100060000', grid_id='g2')])
    _hub_year(db, '52113', '11600', '0011', '0000', 100.0)
    _hub_year(db, '52710', '25000', '0005', '0000', 10.0)
    _hub_year(db, '52710', '25000', '0006', '0000', 1.0)
    db.commit()
    national = grid_building_energy(db, 2025)
    scoped = grid_building_energy(db, 2025, {'g1'})
    assert set(scoped) == {'g1'} and scoped['g1']['electricity_kwh'] == national['g1']['electricity_kwh'] == 1320.0
    assert scoped['g1']['parcels'] == 2
    assert scoped['g1']['kwh_per_m2'] is None  # no 건축물대장 table yet: no area, no intensity (never 0)
    _hub_year(db, '41110', '10100', '0001', '0000', 5.0)  # another region is being collected
    db.commit()
    assert grid_building_energy(db, 2025, {'g1'}) is scoped  # still the cached answer


def test_metered_parcels_missing_from_the_cadastral_snapshot_are_placed_by_their_main_lot():
    """전주 2025: 488 metered parcels (80 GWh) had a PNU the 연속지적도 does not hold (split or renumbered later)."""
    from app.energy_parcels import MAIN_LOT_METHOD, grid_building_energy, place_missing_parcels
    db, ParcelGrid = _parcel_db()
    db.add_all([ParcelGrid(pnu='5211311600101660001', grid_id='g1'), ParcelGrid(pnu='5211311600101660002', grid_id='g1'),
                ParcelGrid(pnu='5211311600101660003', grid_id='g2')])
    _hub_year(db, '52113', '11600', '0166', '0011', 50.0)   # 166-11: not in the snapshot, siblings 166-1/2 in g1, 166-3 in g2
    _hub_year(db, '52113', '11600', '0999', '0000', 7.0)    # no lot 999 at all: stays unplaced
    db.commit()
    stats = place_missing_parcels(db, ['52113'])
    assert stats == {'missing': 2, 'placed': 1, 'no_sibling': 1}
    placed = db.get(ParcelGrid, '5211311600101660011')
    assert placed.grid_id == 'g1' and placed.method == MAIN_LOT_METHOD
    assert grid_building_energy(db, 2025, {'g1'})['g1']['electricity_kwh'] == 600.0
    assert place_missing_parcels(db, ['52113'])['placed'] == 0  # a second run adds nothing


def test_a_region_scoped_map_still_finds_the_register_floor_area_of_its_parcels():
    """10/14 deploy: the region filter on the 건축물대장 matched nothing on the PC (locale collation) and every
    grid lost its 건물 전체 전력 원단위; the floor area must come with the scoped totals."""
    from app.energy_parcels import grid_building_energy
    from app.official import BuildingRegister
    db, ParcelGrid = _parcel_db()
    BuildingRegister.__table__.create(db.get_bind())
    db.add(ParcelGrid(pnu='5211311600100110000', grid_id='g1'))
    db.add(BuildingRegister(id='b1', parcel_code='5211311600100110000', source='t', reference_period='2025', attributes={'gross_floor_area_m2': 1200.0},
                            raw_record={}))
    db.add(BuildingRegister(id='b2', parcel_code='4111110100100010000', source='t', reference_period='2025', attributes={'gross_floor_area_m2': 9.0},
                            raw_record={}))
    _hub_year(db, '52113', '11600', '0011', '0000', 10000.0)
    db.commit()
    cell = grid_building_energy(db, 2025, {'g1'})['g1']
    assert cell['area_m2'] == 1200.0 and cell['kwh_per_m2'] == 100.0


def test_address_lookup_cleans_the_provider_address_and_never_asks_without_a_key(monkeypatch):
    from app.energy_parcels import _clean_address, place_by_address
    assert _clean_address('전라북도 전주시 완산구 쑥고개로 356-1 (효자동2가)') == '전북특별자치도 전주시 완산구 쑥고개로 356-1'
    assert _clean_address('전라북도 전주시 덕진구   (팔복동1가 24-4)') is None  # no road name and number: nothing to look up
    assert _clean_address(None) is None
    monkeypatch.delenv('VWORLD_API_KEY', raising=False)
    db, _ = _parcel_db()
    assert place_by_address(db, ['52113']) == {'missing': 0, 'placed': 0, 'not_found': 0, 'requests': 0}
