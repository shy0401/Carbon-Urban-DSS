from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import DataSource, EnergyMonthly, WeatherMonthly
from app.quality import calculate_quality, dataset_quality


def test_calculate_quality_averages_only_known_dimensions_with_evidence() -> None:
    result = calculate_quality(
        coverage={"score": 0.8, "evidence": "8 of 10 rows normalized"},
        completeness=None,
        temporal={"score": 0.6, "evidence": "6 of 10 periods"},
        spatial_match=None,
    )

    assert result["overall"] == 0.7
    assert result["known_dimensions"] == 2
    assert result["dimensions"]["coverage"] == {
        "score": 0.8,
        "evidence": "8 of 10 rows normalized",
    }
    assert result["dimensions"]["completeness"]["score"] is None
    assert "2/4" in result["explanation"]


def test_calculate_quality_returns_unknown_when_every_dimension_is_null() -> None:
    result = calculate_quality(None, None, None, None)

    assert result["overall"] is None
    assert result["known_dimensions"] == 0
    assert "available evidence 없음" in result["explanation"]


def test_dataset_quality_uses_actual_energy_rows_for_temporal_and_spatial_scores() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    DataSource.__table__.create(engine)
    EnergyMonthly.__table__.create(engine)
    TestSession = sessionmaker(engine)
    with TestSession() as db:
        db.add(
            DataSource(
                id="energy",
                category="건물 에너지",
                name="test",
                organization="test",
                source_url="https://example.test",
                raw_row_count=4,
                normalized_row_count=3,
                missing_count=1,
            )
        )
        for index, (month, grid_id) in enumerate(
            [("202501", "cell_1"), ("202502", "cell_1"), ("202502", None)], start=1
        ):
            db.add(
                EnergyMonthly(
                    id=index,
                    source="국토교통부 건축HUB",
                    sigungu_code="52110",
                    bjdong_code="10100",
                    bun=str(index),
                    ji="0",
                    use_ym=month,
                    energy_type="ELECTRICITY",
                    usage_kwh=100.0,
                    grid_id=grid_id,
                    raw_record={},
                )
            )
        db.commit()

        result = dataset_quality(db, "energy", year=2025)

    assert result["dimensions"]["coverage"]["score"] == 0.75
    assert result["dimensions"]["completeness"]["score"] == 2 / 3
    assert result["dimensions"]["temporal"]["score"] == 2 / 24
    assert result["dimensions"]["spatial_match"]["score"] == 2 / 3
    assert "2 observed energy-type months" in result["dimensions"]["temporal"]["evidence"]


def test_weather_quality_uses_expected_months_and_observed_days_after_aggregation() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    DataSource.__table__.create(engine)
    WeatherMonthly.__table__.create(engine)
    TestSession = sessionmaker(engine)
    with TestSession() as db:
        db.add(
            DataSource(
                id="weather",
                category="기상",
                name="weather",
                organization="provider",
                source_url="https://example.test",
                raw_row_count=365,
                normalized_row_count=12,
                missing_count=5,
            )
        )
        for month in range(1, 13):
            expected = 31
            observed = 30
            db.add(
                WeatherMonthly(
                    use_ym=f"2025{month:02d}",
                    provider="provider",
                    source_type="UNVERIFIED",
                    latitude=35.8,
                    longitude=127.1,
                    days_observed=observed,
                    expected_days=expected,
                )
            )
        db.commit()

        result = dataset_quality(db, "weather", year=2025)

    assert result["dimensions"]["coverage"]["score"] == 1.0
    assert result["dimensions"]["completeness"]["score"] == 360 / 372
    assert result["dimensions"]["temporal"]["score"] == 1.0
    assert "12 normalized months / 12 expected" in result["dimensions"]["coverage"]["evidence"]
