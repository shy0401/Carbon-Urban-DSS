import json

from app.history import classify_error, collect_history, history_status


class FakeDb:
    def rollback(self):
        pass


def test_back_fill_runs_every_year_then_the_once_layers_and_resumes(tmp_path):
    calls = []

    def runner(name):
        def run(year=None):
            calls.append((name, year))
            return {'status': 'DONE', 'rows': 1, 'scope': 'all_parcels'}
        return run

    runners = {name: runner(name) for name in ('sgis', 'kma_asos', 'kapt_energy', 'energy', 'vworld_buildings', 'vworld_cadastral')}
    result = collect_history(FakeDb(), 2023, 2024, data_dir=tmp_path, runners=runners, log=lambda m: None)
    assert calls[:3] == [('sgis', 2024), ('kma_asos', 2024), ('energy', 2024)]  # newest year first
    assert calls[3:6] == [('sgis', 2023), ('kma_asos', 2023), ('energy', 2023)]
    assert calls[6:8] == [('vworld_buildings', None), ('vworld_cadastral', None)]
    assert calls[-2:] == [('kapt_energy', 2024), ('kapt_energy', 2023)]  # the slow per-complex source goes last
    assert all(item['status'] == 'DONE' for item in result['items'].values())
    calls.clear()
    collect_history(FakeDb(), 2023, 2024, data_dir=tmp_path, runners=runners, log=lambda m: None)
    assert calls == []  # resumed: nothing left to do
    state = json.loads((tmp_path / 'ops' / 'history-progress.json').read_text(encoding='utf-8'))
    assert state['items']['kapt_energy:2024']['status'] == 'DONE'


def test_quota_stops_only_that_dataset_and_is_retried_next_run(tmp_path):
    from app.cache import ExternalError

    def quota(year=None):
        raise ExternalError('K-apt API 일일 호출 한도 초과(22): 성공한 월은 건너뛰므로 다음 날 다시 실행하세요')

    ok = lambda year=None: {'status': 'DONE'}  # noqa: E731
    runners = {'sgis': ok, 'kma_asos': ok, 'kapt_energy': quota, 'energy': ok}
    result = collect_history(FakeDb(), 2020, 2022, datasets=['sgis', 'kma_asos', 'kapt_energy', 'energy'], data_dir=tmp_path, runners=runners, log=lambda m: None)
    # newest year first: the first K-apt year hits the quota, the older ones wait for the next run
    assert result['items']['kapt_energy:2022']['status'] == 'FAILED'
    assert result['items']['kapt_energy:2022']['kind'] == 'QUOTA'
    assert result['items']['kapt_energy:2020']['status'] == 'BLOCKED'
    assert result['items']['energy:2022']['status'] == 'DONE'
    assert 'kapt_energy' in result['blocked']
    status = history_status(tmp_path)
    assert status['summary']['kapt_energy'] == {'FAILED': 1, 'BLOCKED': 2}


def test_error_classification():
    assert classify_error('KMA ASOS API 인증 실패: 서비스 활용 승인과 인증키를 확인하세요') == 'AUTH'
    assert classify_error('건축HUB 일일 호출 한도 초과(22)') == 'QUOTA'
    assert classify_error('외부 서비스 연결 실패') == 'ERROR'


def test_blocked_datasets_are_skipped_without_any_request(tmp_path):
    calls = []
    ok = lambda year=None: calls.append(year) or {'status': 'DONE'}  # noqa: E731
    result = collect_history(FakeDb(), 2024, 2024, datasets=['sgis', 'energy'], data_dir=tmp_path,
                             runners={'sgis': ok, 'energy': ok}, blockers={'energy': '환경변수 미설정: DATA_GO_KR_SERVICE_KEY'}, log=lambda m: None)
    assert calls == [2024]  # only sgis ran
    assert result['items']['energy:2024']['status'] == 'BLOCKED'
    assert '미설정' in result['items']['energy:2024']['reason']


def test_items_already_in_the_db_are_marked_done_without_a_call(tmp_path, monkeypatch):
    from app import history
    calls = []
    monkeypatch.setattr(history, 'db_satisfied', lambda db, dataset, year: '2024년 ASOS 완전월 12개 보유' if dataset == 'kma_asos' else None)
    runner = lambda year=None: calls.append(year) or {'status': 'DONE'}  # noqa: E731
    result = collect_history(FakeDb(), 2024, 2024, datasets=['kma_asos'], data_dir=tmp_path, runners={'kma_asos': runner}, check_db=True, log=lambda m: None)
    assert calls == []
    assert result['items']['kma_asos:2024'] == {**result['items']['kma_asos:2024'], 'status': 'DONE', 'requests': 0}


def test_quota_gives_a_resume_time_after_the_next_kst_midnight(tmp_path):
    from datetime import datetime, timezone
    from app.cache import ExternalError
    from app.history import next_quota_reset

    def quota(year=None):
        raise ExternalError('건축물대장 일일 호출 한도 초과(22)')

    result = collect_history(FakeDb(), 2024, 2024, datasets=['energy'], data_dir=tmp_path, runners={'energy': quota}, log=lambda m: None)
    assert result['quota'] and result['resume_at']
    # 2026-09-25 23:50 KST (14:50 UTC) → 2026-09-26 00:20 KST = 2026-09-25 15:20 UTC
    assert next_quota_reset(datetime(2026, 9, 25, 14, 50, tzinfo=timezone.utc)) == datetime(2026, 9, 25, 15, 20, tzinfo=timezone.utc)
    # 00:10 KST (15:10 UTC previous day) → the same day's 00:20 has passed? no: next day 00:20 KST
    assert next_quota_reset(datetime(2026, 9, 25, 15, 10, tzinfo=timezone.utc)) == datetime(2026, 9, 26, 15, 20, tzinfo=timezone.utc)


def test_plan_lists_done_todo_blocked_and_manual_without_requests(tmp_path):
    from app.history import MANUAL_SOURCES, Progress, plan_missing
    progress = Progress(tmp_path / 'ops' / 'history-progress.json')
    progress.set('sgis', 2024, 'DONE')
    progress.set('kapt_energy', 2024, 'FAILED', kind='ERROR', reason='일시 오류')
    plan = plan_missing(FakeDb(), 2024, 2025, data_dir=tmp_path, blockers={'building_register': '키 거절'}, check_db=False)
    rows = {r['dataset']: r for r in plan['rows']}
    assert [c['state'] for c in rows['sgis']['cells']] == ['DONE', 'TODO']
    assert rows['kapt_energy']['cells'][0]['state'] == 'RETRY'
    assert rows['building_register']['cells'] == [{'year': None, 'state': 'BLOCKED', 'reason': '키 거절', 'at': None}]
    assert plan['summary']['manual'] == len(MANUAL_SOURCES) and plan['summary']['blocked'] == 1
    assert plan['summary']['todo'] == plan['summary']['states'].get('TODO', 0) + 1


def test_energy_collected_per_apartment_parcel_is_redone_city_wide_once(tmp_path):
    calls = []
    ok = lambda year=None: calls.append(year) or {'status': 'DONE'}  # noqa: E731 - old per-parcel run: no scope
    collect_history(FakeDb(), 2025, 2025, datasets=['energy'], data_dir=tmp_path, runners={'energy': ok}, log=lambda m: None)
    collect_history(FakeDb(), 2025, 2025, datasets=['energy'], data_dir=tmp_path, runners={'energy': ok}, log=lambda m: None)
    assert calls == [2025, 2025]
    city = lambda year=None: calls.append(year) or {'status': 'DONE', 'scope': 'all_parcels'}  # noqa: E731
    collect_history(FakeDb(), 2025, 2025, datasets=['energy'], data_dir=tmp_path, runners={'energy': city}, log=lambda m: None)
    collect_history(FakeDb(), 2025, 2025, datasets=['energy'], data_dir=tmp_path, runners={'energy': city}, log=lambda m: None)
    assert calls == [2025, 2025, 2025]  # done city-wide: not requested again
