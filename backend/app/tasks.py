import os,uuid
from celery import Celery
from sqlalchemy import select
from .db import Session
from .models import CollectionJob,CollectionJobConfig,DataSource,now
from .collectors import collect_energy,collect_weather
from .collection_preflight import ensure_collection_ready

celery_app=Celery('carbon',broker=os.getenv('REDIS_URL','redis://redis:6379/0'))
celery_app.conf.update(task_serializer='json',accept_content=['json'],result_serializer='json',task_ignore_result=True,broker_connection_retry_on_startup=True,worker_prefetch_multiplier=1,task_acks_late=True,task_reject_on_worker_lost=True,
    # A 'collect everything missing' run can wait until the next KST day for the provider quota (ETA up to ~24h).
    broker_transport_options={'visibility_timeout':26*3600})

ALL_MISSING='all_missing'

@celery_app.task(name='collect')
def run_collection(job_id):
    with Session() as db:
        job=db.get(CollectionJob,job_id)
        if not job or job.status not in ('QUEUED','RUNNING','WAITING'): return
        if job.datasets==[ALL_MISSING]:
            return run_all_missing(db,job)
        job.status='RUNNING';job.message='실제 공공 데이터 수집 중';db.commit()
        config=db.get(CollectionJobConfig,job.id)
        scope=config.scope if config else 'limited'
        errors=[];successes=0
        for i,dataset in enumerate(job.datasets):
            try:
                def progress(fraction,message):
                    job.progress=(i+fraction)/len(job.datasets)*100;job.message=message;db.commit()
                if dataset=='energy':
                    errors.extend(collect_energy(db,job.start_month,job.end_month,progress,scope))
                    from .kapt import merge_energy_coordinates
                    merge_energy_coordinates(db)
                elif dataset=='weather': collect_weather(db,job.start_month,job.end_month)
                elif dataset=='kapt_energy':
                    from .kapt_energy import collect_kapt_energy
                    stats=collect_kapt_energy(db,int(job.start_month[:4]),scope)
                    if stats.get('failed'):
                        errors.append({'dataset':dataset,'message':f"{stats['failed']}개 단지·월이 제공기관 일시 오류로 비어 있습니다. 다시 실행하면 그 월만 재요청합니다"})
                elif dataset=='kma_asos':
                    from .kma_asos import collect_asos
                    collect_asos(db,int(job.start_month[:4]),scope)
                elif dataset=='sgis':
                    from .sgis import collect_sgis_admin
                    collect_sgis_admin(db,int(os.getenv('SGIS_BASE_YEAR','2024')),scope)
                elif dataset=='building_register':
                    from .official import collect_register
                    stats=collect_register(db,scope,progress)
                    if stats.get('failed'):
                        errors.append({'dataset':dataset,'message':f"{stats['failed']}개 페이지가 제공기관 일시 오류로 비어 있습니다. 다시 실행하면 그 페이지만 재요청합니다"})
                elif dataset in ('vworld_zoning','vworld_cadastral','vworld_buildings'):
                    from .vworld import collect_vworld
                    collect_vworld(db,dataset.removeprefix('vworld_'),scope)
                else: raise ValueError('지원하지 않는 자동 수집 데이터셋')
                successes+=1
            except Exception as exc:
                db.rollback()
                # External errors are deliberately sanitized by the collectors. Never expose exception URLs.
                message=str(exc) if type(exc).__name__ in ('ExternalError','ValueError') else '데이터 처리 실패: '+type(exc).__name__
                errors.append({'dataset':dataset,'message':message})
                source_id={'kma_asos':'weather_kma','sgis':'sgis_admin','building_register':'building_official'}.get(dataset,dataset)
                source=db.get(DataSource,source_id)
                if source:
                    source.status='PARTIAL' if source.normalized_row_count else ('NEEDS_API_KEY' if '인증' in message else 'FAILED')
                    source.quality=message
                db.commit()
            job=db.get(CollectionJob,job_id);job.progress=(i+1)/len(job.datasets)*100;db.commit()
        job.status=('PARTIAL' if successes else 'FAILED') if errors else 'SUCCESS'
        job.errors=errors;job.finished_at=now();job.message='수집 완료' if not errors else '일부 자료 수집 불가 — 오류 내역 확인';db.commit()

def run_all_missing(db,job):
    """Background 'collect everything missing' run. On a daily quota it waits and resumes by itself."""
    from datetime import datetime
    from .history import collect_missing
    job.status='RUNNING';job.resume_at=None;job.message='빠진 자료 수집 시작';db.commit()
    def progress(fraction,message):
        job.progress=round(max(0.0,min(1.0,fraction))*100,1);job.message=message;db.commit()
    try:
        result=collect_missing(db,int(job.start_month[:4]),int(job.end_month[:4]),progress=progress,log=lambda m:None)
    except Exception as exc:  # noqa: BLE001 - lock held by another run, or an unexpected local failure
        db.rollback();job=db.get(CollectionJob,job.id)
        job.status='FAILED';job.finished_at=now()
        job.message=str(exc)[:200] if type(exc).__name__ in ('RuntimeError','ValueError') else '데이터 처리 실패: '+type(exc).__name__
        job.errors=[{'dataset':ALL_MISSING,'message':job.message}];db.commit();return
    job=db.get(CollectionJob,job.id)
    failed=[{'dataset':key.split(':')[0],'message':f"{key}: {item.get('reason','')}"[:240]} for key,item in result['items'].items() if item.get('status') in ('FAILED','BLOCKED')]
    job.errors=failed[:60]
    if result.get('quota'):
        resume=datetime.fromisoformat(result['resume_at'])
        job.status='WAITING';job.resume_at=resume;job.progress=100.0
        from datetime import timedelta,timezone
        kst=resume.astimezone(timezone(timedelta(hours=9))).strftime('%m월 %d일 %H:%M')
        job.message=f"일일 호출 한도에 걸린 자료({', '.join(sorted(result['quota']))})는 {kst}(한국 시간)에 자동으로 이어서 수집합니다. 그때 PC와 Docker가 켜져 있어야 합니다."
        db.commit()
        try: run_collection.apply_async((job.id,),eta=resume)
        except Exception: pass  # the status endpoint re-queues an overdue waiting job
        return
    job.status='PARTIAL' if failed else 'SUCCESS';job.finished_at=now();job.progress=100.0
    job.message='빠진 자료 수집을 마쳤습니다' if not failed else f'수집을 마쳤습니다. 키·승인 또는 제공기관 오류로 남은 항목 {len(failed)}개'
    db.commit()

def queue_all_missing(db,from_year,to_year):
    """One background job that collects every missing year and layer (no dataset preflight: the run skips blocked ones)."""
    import redis
    connection=redis.Redis.from_url(os.getenv('REDIS_URL','redis://redis:6379/0'))
    with connection.lock('carbon:collection-enqueue',timeout=15,blocking_timeout=5):
        existing=db.scalar(select(CollectionJob).where(CollectionJob.status.in_(['QUEUED','RUNNING','WAITING'])))
        if existing and existing.status=='WAITING' and existing.datasets==[ALL_MISSING]:
            # The user asked again: try now instead of waiting for the scheduled resume.
            existing.status='QUEUED';existing.resume_at=None;existing.message='다시 시작 요청';db.commit()
            try: run_collection.delay(existing.id)
            except Exception: pass
            return existing
        if existing: return existing
        job=CollectionJob(id=str(uuid.uuid4()),datasets=[ALL_MISSING],start_month=f'{from_year}-01',end_month=f'{to_year}-12',message='대기 중')
        db.add(job);db.flush();db.add(CollectionJobConfig(job_id=job.id,scope='full'));db.commit()
        try: run_collection.delay(job.id)
        except Exception:
            job.status='FAILED';job.message='수집 작업 큐 연결 실패';job.errors=[{'message':job.message}];db.commit()
        return job

def resume_overdue(db):
    """Re-queue a waiting run whose resume time has passed (e.g. the worker restarted and lost its timer)."""
    from datetime import timedelta
    job=db.scalar(select(CollectionJob).where(CollectionJob.status=='WAITING'))
    if job and job.resume_at and job.resume_at+timedelta(minutes=10)<now():
        job.resume_at=now()+timedelta(hours=1);db.commit()  # avoid re-queuing on every poll
        try: run_collection.delay(job.id)
        except Exception: pass
    return job

def queue_collection(db,datasets,start,end,scope='limited'):
    ensure_collection_ready(datasets)
    # Serialize collection requests across API processes. Historical disk cache remains reusable.
    import redis
    connection=redis.Redis.from_url(os.getenv('REDIS_URL','redis://redis:6379/0'))
    with connection.lock('carbon:collection-enqueue',timeout=15,blocking_timeout=5):
        existing=db.scalar(select(CollectionJob).where(CollectionJob.status.in_(['QUEUED','RUNNING'])))
        if existing: return existing
        job=CollectionJob(id=str(uuid.uuid4()),datasets=datasets,start_month=start,end_month=end)
        db.add(job);db.flush();db.add(CollectionJobConfig(job_id=job.id,scope=scope));db.commit()
        try: run_collection.delay(job.id)
        except Exception:
            job.status='FAILED';job.message='수집 작업 큐 연결 실패';job.errors=[{'message':job.message}];db.commit()
        return job
