import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

class Base(DeclarativeBase): pass

def _int_env(name: str, default: int) -> int:
    try: return max(1, int(os.getenv(name, default)))
    except ValueError: return default

# 연결 묶음: 기본값(5 + 넘침 10, 30초 대기)으로는 화면을 빠르게 넘길 때(지역 시뮬레이션·검증처럼 오래 걸리는 요청이 겹칠 때)
# 연결을 기다리다 500이 났다(2026-11-14 촬영: QueuePool limit of size 5 overflow 10 reached). api와 worker를 합쳐도
# PostgreSQL 기본 max_connections(100) 안에 들도록 10 + 20으로 둔다. 바꿀 때는 .env의 DB_POOL_SIZE·DB_MAX_OVERFLOW·DB_POOL_TIMEOUT.
engine=create_engine(os.getenv('DATABASE_URL','postgresql+psycopg://carbon:carbon_local@localhost:5432/carbon'),pool_pre_ping=True,
                     pool_size=_int_env('DB_POOL_SIZE',10),max_overflow=_int_env('DB_MAX_OVERFLOW',20),pool_timeout=_int_env('DB_POOL_TIMEOUT',60))
Session=sessionmaker(engine,expire_on_commit=False)
