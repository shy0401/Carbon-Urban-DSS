from datetime import datetime,timezone
from sqlalchemy import String,Float,Integer,DateTime,JSON,Text,UniqueConstraint,ForeignKey
from sqlalchemy.orm import Mapped,mapped_column
from geoalchemy2 import Geometry
from .db import Base

def now(): return datetime.now(timezone.utc)

class DataSource(Base):
    __tablename__='data_sources'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    category:Mapped[str]=mapped_column(String)
    name:Mapped[str]=mapped_column(String)
    organization:Mapped[str]=mapped_column(String)
    source_url:Mapped[str]=mapped_column(Text)
    source_type:Mapped[str]=mapped_column(String,default='OFFICIAL')
    status:Mapped[str]=mapped_column(String,default='NOT_COLLECTED')
    collected_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    reference_period:Mapped[str]=mapped_column(String,default='2025-01 ~ 2025-12')
    geographic_coverage:Mapped[str]=mapped_column(String,default='전북특별자치도 전주시')
    raw_row_count:Mapped[int]=mapped_column(Integer,default=0)
    normalized_row_count:Mapped[int]=mapped_column(Integer,default=0)
    missing_count:Mapped[int|None]=mapped_column(Integer,nullable=True)
    quality:Mapped[str]=mapped_column(String,default='자료 없음')
    limitation:Mapped[str]=mapped_column(Text,default='')

class CollectionJob(Base):
    __tablename__='collection_jobs'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    datasets:Mapped[list]=mapped_column(JSON)
    start_month:Mapped[str]=mapped_column(String)
    end_month:Mapped[str]=mapped_column(String)
    status:Mapped[str]=mapped_column(String,default='QUEUED')
    progress:Mapped[float]=mapped_column(Float,default=0)
    message:Mapped[str]=mapped_column(Text,default='대기 중')
    errors:Mapped[list]=mapped_column(JSON,default=list)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    finished_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)

class RawDataAsset(Base):
    __tablename__='raw_data_assets'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    source_id:Mapped[str]=mapped_column(ForeignKey('data_sources.id'))
    provider:Mapped[str]=mapped_column(String)
    source_url:Mapped[str]=mapped_column(Text)
    collected_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    reference_period:Mapped[str]=mapped_column(String)
    row_count:Mapped[int]=mapped_column(Integer,default=0)
    collection_status:Mapped[str]=mapped_column(String)
    storage_location:Mapped[str]=mapped_column(Text)
    request_parameters:Mapped[dict]=mapped_column(JSON,default=dict)
    error:Mapped[str|None]=mapped_column(Text,nullable=True)

class Region(Base):
    __tablename__='regions'
    code:Mapped[str]=mapped_column(String,primary_key=True)
    sigungu_code:Mapped[str]=mapped_column(String)
    bjdong_code:Mapped[str]=mapped_column(String)
    name:Mapped[str]=mapped_column(String)
    source:Mapped[str]=mapped_column(String)
    version:Mapped[str]=mapped_column(String)
    raw_record:Mapped[dict]=mapped_column(JSON)

class Grid(Base):
    __tablename__='grid_500m'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    geom:Mapped[object]=mapped_column(Geometry('POLYGON',srid=5179))
    area_m2:Mapped[float]=mapped_column(Float,default=250000)
    properties:Mapped[dict]=mapped_column(JSON)
    geojson:Mapped[dict]=mapped_column(JSON)

class EnergyMonthly(Base):
    __tablename__='energy_monthly'
    __table_args__=(UniqueConstraint('sigungu_code','bjdong_code','lot_type','bun','ji','use_ym','energy_type'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    source:Mapped[str]=mapped_column(String)
    sigungu_code:Mapped[str]=mapped_column(String)
    bjdong_code:Mapped[str]=mapped_column(String)
    lot_type:Mapped[str]=mapped_column(String,default='0')
    bun:Mapped[str]=mapped_column(String)
    ji:Mapped[str]=mapped_column(String)
    use_ym:Mapped[str]=mapped_column(String)
    energy_type:Mapped[str]=mapped_column(String)
    usage_kwh:Mapped[float|None]=mapped_column(Float,nullable=True)
    grid_id:Mapped[str|None]=mapped_column(String,nullable=True)
    match_method:Mapped[str|None]=mapped_column(String,nullable=True)
    raw_record:Mapped[dict]=mapped_column(JSON)
    collected_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class WeatherMonthly(Base):
    __tablename__='weather_monthly'
    use_ym:Mapped[str]=mapped_column(String,primary_key=True)
    provider:Mapped[str]=mapped_column(String)
    source_type:Mapped[str]=mapped_column(String)
    latitude:Mapped[float]=mapped_column(Float)
    longitude:Mapped[float]=mapped_column(Float)
    mean_temperature:Mapped[float|None]=mapped_column(Float,nullable=True)
    min_temperature:Mapped[float|None]=mapped_column(Float,nullable=True)
    max_temperature:Mapped[float|None]=mapped_column(Float,nullable=True)
    precipitation:Mapped[float|None]=mapped_column(Float,nullable=True)
    hdd:Mapped[float|None]=mapped_column(Float,nullable=True)
    cdd:Mapped[float|None]=mapped_column(Float,nullable=True)
    days_observed:Mapped[int]=mapped_column(Integer)
    expected_days:Mapped[int]=mapped_column(Integer)
    collected_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class EmissionFactor(Base):
    __tablename__='emission_factors'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    energy_type:Mapped[str]=mapped_column(String)
    factor:Mapped[float]=mapped_column(Float)
    factor_unit:Mapped[str]=mapped_column(String)
    reference_year:Mapped[int]=mapped_column(Integer)
    source:Mapped[str]=mapped_column(String)
    source_url:Mapped[str]=mapped_column(Text)
    effective_from:Mapped[str]=mapped_column(String)
    notes:Mapped[str]=mapped_column(Text,default='')

class Building(Base):
    __tablename__='buildings'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    grid_id:Mapped[str|None]=mapped_column(String,nullable=True)
    name:Mapped[str]=mapped_column(String)
    source:Mapped[str]=mapped_column(String)
    source_type:Mapped[str]=mapped_column(String)
    footprint_m2:Mapped[float|None]=mapped_column(Float,nullable=True)
    floor_area_m2:Mapped[float|None]=mapped_column(Float,nullable=True)
    properties:Mapped[dict]=mapped_column(JSON)
    geojson:Mapped[dict]=mapped_column(JSON)

class ZoningArea(Base):
    __tablename__='zoning_areas'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    source:Mapped[str]=mapped_column(String)
    properties:Mapped[dict]=mapped_column(JSON)
    geojson:Mapped[dict]=mapped_column(JSON)

class PopulationGrid(Base):
    __tablename__='population_grid'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    grid_id:Mapped[str]=mapped_column(String)
    population:Mapped[float]=mapped_column(Float)
    reference_period:Mapped[str]=mapped_column(String)
    source:Mapped[str]=mapped_column(String)

class TestbedSector(Base):
    __tablename__='testbed_sectors'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    grid_id:Mapped[str]=mapped_column(String)
    name:Mapped[str]=mapped_column(String)
    area_m2:Mapped[float]=mapped_column(Float,default=250000)
    reason:Mapped[str]=mapped_column(Text)
    candidates:Mapped[list]=mapped_column(JSON)
    metadata_json:Mapped[dict]=mapped_column(JSON,default=dict)

class Scenario(Base):
    __tablename__='scenarios'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    inputs:Mapped[dict]=mapped_column(JSON)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class ScenarioResult(Base):
    __tablename__='scenario_results'
    id:Mapped[str]=mapped_column(ForeignKey('scenarios.id'),primary_key=True)
    result:Mapped[dict]=mapped_column(JSON)

class ModelRun(Base):
    __tablename__='model_runs'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    year:Mapped[int]=mapped_column(Integer)
    result:Mapped[dict]=mapped_column(JSON)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
