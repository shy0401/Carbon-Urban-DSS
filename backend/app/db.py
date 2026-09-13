import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

class Base(DeclarativeBase): pass

engine=create_engine(os.getenv('DATABASE_URL','postgresql+psycopg://carbon:carbon_local@localhost:5432/carbon'),pool_pre_ping=True)
Session=sessionmaker(engine,expire_on_commit=False)
