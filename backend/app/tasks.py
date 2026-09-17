import os,uuid
from celery import Celery
from sqlalchemy import select
from .db import Session
from .models import CollectionJob,CollectionJobConfig,DataSource,now
from .collectors import collect_energy,collect_weather

celery_app=Celery('carbon',broker=os.getenv('REDIS_URL','redis://redis:6379/0'))
celery_app.conf.update(task_serializer='json',accept_content=['json'],result_serializer='json',task_ignore_result=True,broker_connection_retry_on_startup=True,worker_prefetch_multiplier=1,task_acks_late=True,task_reject_on_worker_lost=True)

@celery_app.task(name='collect')
def run_collection(job_id):
    with Session() as db:
        job=db.get(CollectionJob,job_id)
        if not job or job.status not in ('QUEUED','RUNNING'): return
        job.status='RUNNING';job.message='실제 공공 데이터 수집 중';db.commit()
        config=db.get(CollectionJobConfig,job.id)
        scope=config.scope if config else 'limited'
        errors=[];successes=0
        for i,dataset in enumerate(job.datasets):
            try:
                def progress(fraction,message):
                    job.progress=(i+fraction)/len(job.datasets)*100;job.message=message;db.commit()
                if dataset=='energy':
                    errors.extend(collect_energy(db,job.start_month,job.end_month,progress))
                    from .kapt import merge_energy_coordinates
                    merge_energy_coordinates(db)
                elif dataset=='weather': collect_weather(db,job.start_month,job.end_month)
                elif dataset=='kapt_energy':
                    from .kapt_energy import collect_kapt_energy
                    collect_kapt_energy(db,int(job.start_month[:4]),scope)
                elif dataset=='kma_asos':
                    from .kma_asos import collect_asos
                    collect_asos(db,int(job.start_month[:4]),scope)
                elif dataset=='sgis':
                    from .sgis import collect_sgis_admin
                    collect_sgis_admin(db,int(os.getenv('SGIS_BASE_YEAR','2020')),scope)
                elif dataset in ('vworld_zoning','vworld_cadastral'):
                    from .vworld import collect_vworld
                    collect_vworld(db,dataset.removeprefix('vworld_'),scope)
                else: raise ValueError('지원하지 않는 자동 수집 데이터셋')
                successes+=1
            except Exception as exc:
                db.rollback()
                # External errors are deliberately sanitized by the collectors. Never expose exception URLs.
                message=str(exc) if type(exc).__name__ in ('ExternalError','ValueError') else '데이터 처리 실패: '+type(exc).__name__
                errors.append({'dataset':dataset,'message':message})
                source_id={'kma_asos':'weather_kma','sgis':'sgis_admin'}.get(dataset,dataset)
                source=db.get(DataSource,source_id)
                if source:
                    source.status='PARTIAL' if source.normalized_row_count else ('NEEDS_API_KEY' if '인증' in message else 'FAILED')
                    source.quality=message
                db.commit()
            job=db.get(CollectionJob,job_id);job.progress=(i+1)/len(job.datasets)*100;db.commit()
        job.status=('PARTIAL' if successes else 'FAILED') if errors else 'SUCCESS'
        job.errors=errors;job.finished_at=now();job.message='수집 완료' if not errors else '일부 자료 수집 불가 — 오류 내역 확인';db.commit()

def queue_collection(db,datasets,start,end,scope='limited'):
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
