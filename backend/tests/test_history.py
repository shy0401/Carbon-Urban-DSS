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
            return {'status': 'DONE', 'rows': 1}
        return run

    runners = {name: runner(name) for name in ('sgis', 'kma_asos', 'kapt_energy', 'energy', 'vworld_buildings', 'vworld_cadastral')}
    result = collect_history(FakeDb(), 2023, 2024, data_dir=tmp_path, runners=runners, log=lambda m: None)
    assert calls[:4] == [('sgis', 2023), ('kma_asos', 2023), ('kapt_energy', 2023), ('energy', 2023)]
    assert calls[-2:] == [('vworld_buildings', None), ('vworld_cadastral', None)]
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
    assert result['items']['kapt_energy:2020']['status'] == 'FAILED'
    assert result['items']['kapt_energy:2020']['kind'] == 'QUOTA'
    assert result['items']['kapt_energy:2021']['status'] == 'BLOCKED'
    assert result['items']['energy:2022']['status'] == 'DONE'
    assert 'kapt_energy' in result['blocked']
    status = history_status(tmp_path)
    assert status['summary']['kapt_energy'] == {'FAILED': 1, 'BLOCKED': 2}


def test_error_classification():
    assert classify_error('KMA ASOS API 인증 실패: 서비스 활용 승인과 인증키를 확인하세요') == 'AUTH'
    assert classify_error('건축HUB 일일 호출 한도 초과(22)') == 'QUOTA'
    assert classify_error('외부 서비스 연결 실패') == 'ERROR'
