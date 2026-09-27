from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.domain import carbon_kg
from app.emissions import GAS_FACTOR, GAS_FACTOR_ID, GAS_NCV_FACTOR, ensure_gas_factor
from app.models import EmissionFactor


def test_city_gas_rule_values():
    # IPCC 2006 천연가스 CO2 56,100 + CH4 5×28 + N2O 0.1×265 = 56,266.5 kgCO2eq/TJ; 1 kWh = 3.6e-6 TJ
    assert GAS_NCV_FACTOR == 0.20256
    # 총발열량 기준 kWh 가정: × 38.5/42.7 (에너지법 시행규칙 도시가스 순/총발열량)
    assert GAS_FACTOR == 0.1826
    assert round(GAS_NCV_FACTOR / GAS_FACTOR - 1, 3) == 0.109


def test_gas_rule_is_registered_as_an_assumption():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[EmissionFactor.__table__])
    db = sessionmaker(engine)()
    ensure_gas_factor(db)
    ensure_gas_factor(db)  # idempotent
    rows = db.query(EmissionFactor).all()
    assert len(rows) == 1 and rows[0].id == GAS_FACTOR_ID and rows[0].id.startswith("rule-") and "가정" in rows[0].notes
    factor = {"factor": rows[0].factor, "factor_unit": rows[0].factor_unit}
    assert round(carbon_kg(1000.0, factor), 1) == 182.6
