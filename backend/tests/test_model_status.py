from app import model_service


def test_eligible_untrained_data_is_ready_not_insufficient(monkeypatch):
    rows = [dict(grid_id=f'grid_{i}', spatial_block=str(i // 4),
                 use_ym=f'2025{m:02d}') for i in range(10) for m in range(1, 13)]
    monkeypatch.setattr(model_service, 'model_rows', lambda *args: rows)

    class Database:
        def scalar(self, query):
            return None

    report = model_service.model_status(Database(), 2025)
    assert report['status'] == 'READY_FOR_SPATIAL_VALIDATION'
    assert all(not model['validated'] for model in report['models'])
    assert all(model['metrics'] is None for model in report['models'])
