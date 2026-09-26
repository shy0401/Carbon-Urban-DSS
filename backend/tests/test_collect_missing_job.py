from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import history, tasks
from app.models import CollectionJob, CollectionJobConfig


def make_job():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    CollectionJob.__table__.create(engine)
    CollectionJobConfig.__table__.create(engine)
    db = sessionmaker(engine)()
    job = CollectionJob(id='j1', datasets=[tasks.ALL_MISSING], start_month='2015-01', end_month='2025-12', status='QUEUED', progress=0, message='대기', errors=[])
    db.add(job)
    db.commit()
    return db, job


def test_quota_makes_the_job_wait_and_schedules_its_own_resume(monkeypatch):
    db, job = make_job()
    scheduled = []
    monkeypatch.setattr(history, 'collect_missing', lambda db, a, b, **k: {
        'items': {'kapt_energy:2019': {'status': 'FAILED', 'reason': '한도 초과(22)'}, 'sgis:2019': {'status': 'DONE'}},
        'blocked': {'kapt_energy': '한도 초과(22)'}, 'quota': {'kapt_energy': '한도 초과(22)'}, 'resume_at': '2026-09-26T15:20:00+00:00'})
    monkeypatch.setattr(tasks.run_collection, 'apply_async', lambda args, eta: scheduled.append((args, eta)))
    tasks.run_all_missing(db, job)
    job = db.get(CollectionJob, 'j1')
    assert job.status == 'WAITING'
    assert job.resume_at is not None and '09월 27일 00:20' in job.message
    assert scheduled and scheduled[0][0] == ('j1',)
    assert job.errors[0]['dataset'] == 'kapt_energy'


def test_kapt_gateway_gaps_make_the_job_wait_and_ask_again(monkeypatch):
    db, job = make_job()
    scheduled = []
    monkeypatch.setattr(history, 'collect_missing', lambda db, a, b, **k: {
        'items': {'kapt_energy:2025': {'status': 'PARTIAL', 'kind': 'PROVIDER'}, 'sgis:2025': {'status': 'DONE'}},
        'blocked': {}, 'quota': {}, 'resume_at': None,
        'provider_retry': ['kapt_energy:2025'], 'provider_retry_at': '2026-09-26T13:00:00+00:00'})
    monkeypatch.setattr(tasks.run_collection, 'apply_async', lambda args, eta: scheduled.append((args, eta)))
    tasks.run_all_missing(db, job)
    job = db.get(CollectionJob, 'j1')
    assert job.status == 'WAITING' and '2025년' in job.message and '09월 26일 22:00' in job.message
    assert scheduled and scheduled[0][0] == ('j1',)


def test_finished_run_reports_what_is_left(monkeypatch):
    db, job = make_job()
    monkeypatch.setattr(history, 'collect_missing', lambda db, a, b, **k: {
        'items': {'building_register': {'status': 'BLOCKED', 'reason': '활용신청 필요'}, 'sgis:2019': {'status': 'DONE'}},
        'blocked': {'building_register': '활용신청 필요'}, 'quota': {}, 'resume_at': None})
    tasks.run_all_missing(db, job)
    job = db.get(CollectionJob, 'j1')
    assert job.status == 'PARTIAL' and job.progress == 100.0
    assert '남은 항목 1개' in job.message


def test_a_run_already_in_progress_fails_this_job_cleanly(monkeypatch):
    db, job = make_job()

    def locked(*a, **k):
        raise RuntimeError("다른 '빠진 자료 수집'이 이미 실행 중입니다")

    monkeypatch.setattr(history, 'collect_missing', locked)
    tasks.run_all_missing(db, job)
    job = db.get(CollectionJob, 'j1')
    assert job.status == 'FAILED' and '이미 실행 중' in job.message


def test_running_job_without_its_live_guard_is_restarted(monkeypatch):
    db, job = make_job()
    job.status = 'RUNNING'
    db.commit()
    sent = []
    monkeypatch.setattr(history, 'lock_held', lambda *a, **k: False)
    monkeypatch.setattr('time.sleep', lambda s: None)
    monkeypatch.setattr(tasks.run_collection, 'delay', lambda job_id: sent.append(job_id))
    restarted = tasks.resume_overdue(db)
    assert restarted is not None and restarted.status == 'QUEUED' and sent == ['j1']


def test_running_job_with_a_live_guard_is_left_alone(monkeypatch):
    db, job = make_job()
    job.status = 'RUNNING'
    db.commit()
    monkeypatch.setattr(history, 'lock_held', lambda *a, **k: True)
    assert tasks.stale_running(db) is None
    monkeypatch.setattr(history, 'lock_held', lambda *a, **k: None)  # no Redis: never guess
    assert tasks.stale_running(db) is None
