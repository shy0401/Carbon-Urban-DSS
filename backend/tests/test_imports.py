from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pyproj import Transformer
from shapely.geometry import Polygon, mapping
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.imports as imports_module
from app.imports import (
    ImportedRecord,
    UploadBatch,
    UnsafeUpload,
    _db_session,
    allocate_population_geometry,
    inspect_upload,
    normalise_import_records,
    router,
)
from app.models import DataSource, EnergyMonthly, RawDataAsset


def test_cp949_csv_preview_reports_encoding_columns_and_mapping() -> None:
    content = (
        "시군구코드,법정동코드,번,지,사용년월,에너지원,사용량\n"
        "52110,10100,12,3,202501,ELECTRICITY,123.5\n"
    ).encode("cp949")

    parsed = inspect_upload("energy.csv", content, "energy")
    preview = parsed.preview()

    assert preview["encoding"] == "cp949"
    assert preview["columns"] == [
        "시군구코드",
        "법정동코드",
        "번",
        "지",
        "사용년월",
        "에너지원",
        "사용량",
    ]
    assert preview["rows"][0]["사용량"] == "123.5"
    assert preview["required_fields"] == [
        "sigungu_code",
        "bjdong_code",
        "bun",
        "ji",
        "use_ym",
        "energy_type",
        "usage_kwh",
    ]
    assert preview["suggested_mapping"]["use_ym"] == "사용년월"


def test_zip_preview_rejects_path_traversal_before_extraction() -> None:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../outside.shp", b"not-a-shapefile")

    with pytest.raises(UnsafeUpload, match="unsafe ZIP path"):
        inspect_upload("parcel.zip", archive.getvalue(), "zoning", source_crs="EPSG:5179")


def test_invalid_geojson_geometry_is_rejected_without_silent_repair() -> None:
    bow_tie = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"id": "bad"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]],
                },
            }
        ],
    }
    parsed = inspect_upload(
        "bad.geojson", json.dumps(bow_tie).encode(), "buildings", source_crs="EPSG:5179"
    )

    with pytest.raises(ValueError, match="row 1.*invalid geometry"):
        normalise_import_records(
            parsed,
            "buildings",
            {"id": "id", "geometry": "geometry"},
            target_crs="EPSG:5179",
        )


def test_official_grid_validation_preserves_off_origin_geometry_and_old_id() -> None:
    metric_square = Polygon(
        [
            (965_100, 1_755_100),
            (965_600, 1_755_100),
            (965_600, 1_755_600),
            (965_100, 1_755_600),
            (965_100, 1_755_100),
        ]
    )
    geojson = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:5179"}},
        "features": [
            {
                "type": "Feature",
                "properties": {"official_id": "다사1234"},
                "geometry": mapping(metric_square),
            }
        ],
    }
    parsed = inspect_upload("grid.geojson", json.dumps(geojson).encode(), "grid")

    records = normalise_import_records(
        parsed,
        "grid",
        {"id": "official_id", "geometry": "geometry"},
        target_crs="EPSG:5179",
    )

    assert records[0]["old_grid_id"] == "다사1234"
    assert records[0]["new_grid_id"] is None
    assert records[0]["normalized_geometry"].area == pytest.approx(250_000, abs=0.01)
    assert records[0]["geometry_valid"] is True
    assert "geometry" not in records[0]["values"]


def test_csv_spatial_import_accepts_confirmed_wkt_geometry_mapping() -> None:
    content = (
        'building_id,wkt\n'
        'b-1,"POLYGON ((965000 1755000, 965010 1755000, 965010 1755010, '
        '965000 1755010, 965000 1755000))"\n'
    ).encode()
    parsed = inspect_upload("buildings.csv", content, "buildings", source_crs="EPSG:5179")
    assert parsed.preview()["detected_crs"] == "EPSG:5179"

    records = normalise_import_records(
        parsed,
        "buildings",
        {"id": "building_id", "geometry": "wkt"},
        target_crs="EPSG:5179",
    )

    assert records[0]["normalized_geometry"].area == 100
    assert records[0]["original_properties"]["wkt"].startswith("POLYGON")


def test_grid_import_rejects_non_500_metre_polygon() -> None:
    geojson = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:5179"}},
        "features": [
            {
                "type": "Feature",
                "properties": {"id": "wrong-size"},
                "geometry": mapping(Polygon([(0, 0), (400, 0), (400, 500), (0, 500), (0, 0)])),
            }
        ],
    }
    parsed = inspect_upload("grid.geojson", json.dumps(geojson).encode(), "grid")

    with pytest.raises(ValueError, match="exact 500m x 500m"):
        normalise_import_records(
            parsed,
            "grid",
            {"id": "id", "geometry": "geometry"},
            target_crs="EPSG:5179",
        )


def test_population_100m_geometry_is_allocated_by_containment_and_overlap() -> None:
    app_grids = [
        ("left", Polygon([(0, 0), (500, 0), (500, 500), (0, 500), (0, 0)])),
        ("right", Polygon([(500, 0), (1000, 0), (1000, 500), (500, 500), (500, 0)])),
    ]
    contained = Polygon([(100, 100), (200, 100), (200, 200), (100, 200), (100, 100)])
    crossing = Polygon([(450, 100), (550, 100), (550, 200), (450, 200), (450, 100)])

    assert allocate_population_geometry(contained, 80, app_grids) == [
        {
            "grid_id": "left",
            "population": 80.0,
            "weight": 1.0,
            "method": "CONTAINED_100M",
        }
    ]
    assert allocate_population_geometry(crossing, 80, app_grids) == [
        {
            "grid_id": "left",
            "population": 40.0,
            "weight": 0.5,
            "method": "AREA_WEIGHTED_ESTIMATE",
        },
        {
            "grid_id": "right",
            "population": 40.0,
            "weight": 0.5,
            "method": "AREA_WEIGHTED_ESTIMATE",
        },
    ]


def test_energy_values_are_canonicalized_and_strictly_validated() -> None:
    content = (
        "sigungu,bjdong,bun,ji,month,type,kwh\n"
        "52110,10100,12,3,2025-01,ELECTRICITY,0\n"
    ).encode()
    parsed = inspect_upload("energy.csv", content, "energy")
    mapping_json = {
        "sigungu_code": "sigungu",
        "bjdong_code": "bjdong",
        "bun": "bun",
        "ji": "ji",
        "use_ym": "month",
        "energy_type": "type",
        "usage_kwh": "kwh",
    }

    record = normalise_import_records(parsed, "energy", mapping_json)[0]

    assert record["values"]["bun"] == "0012"
    assert record["values"]["ji"] == "0003"
    assert record["values"]["use_ym"] == "202501"
    assert record["values"]["usage_kwh"] == 0.0

    invalid = inspect_upload(
        "energy.csv",
        content.replace(b"ELECTRICITY,0", b"HEAT,-1"),
        "energy",
    )
    with pytest.raises(ValueError, match="energy_type.*ELECTRICITY or GAS"):
        normalise_import_records(invalid, "energy", mapping_json)


def test_population_accepts_source_grid_id_and_year_without_arbitrary_app_grid_id() -> None:
    content = "source_id,pop,year\nsg-100-1,25,2025\n".encode()
    parsed = inspect_upload("population.csv", content, "population")

    records = normalise_import_records(
        parsed,
        "population",
        {"source_grid_id": "source_id", "population": "pop", "year": "year"},
    )

    assert records[0]["values"] == {
        "source_grid_id": "sg-100-1",
        "population": 25.0,
        "year": "2025",
    }


def test_normalization_requires_epsg5179_target() -> None:
    content = "source_id,pop,year\nsg-1,25,2025\n".encode()
    parsed = inspect_upload("population.csv", content, "population")

    with pytest.raises(ValueError, match="target_crs must be EPSG:5179"):
        normalise_import_records(
            parsed,
            "population",
            {"source_grid_id": "source_id", "population": "pop", "year": "year"},
            target_crs="EPSG:4326",
        )


def test_upload_api_requires_nonblank_provenance_and_imports_atomically(
    tmp_path, monkeypatch
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        DataSource.__table__,
        UploadBatch.__table__,
        RawDataAsset.__table__,
        ImportedRecord.__table__,
        EnergyMonthly.__table__,
    ):
        table.create(engine)
    TestSession = sessionmaker(engine, expire_on_commit=False)

    def test_db():
        with TestSession() as db:
            yield db

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[_db_session] = test_db
    monkeypatch.setattr(imports_module, "UPLOAD_ROOT", tmp_path)
    client = TestClient(app)
    content = (
        "시군구코드,법정동코드,번,지,사용년월,에너지원,사용량\n"
        "52110,10100,12,3,202501,ELECTRICITY,123.5\n"
    ).encode("cp949")

    preview = client.post(
        "/api/uploads/preview",
        files={"file": ("energy.csv", content, "text/csv")},
        data={"dataset_type": "energy"},
    )
    assert preview.status_code == 200
    payload = preview.json()
    assert payload["encoding"] == "cp949"
    assert payload["id"]

    mapping_json = payload["suggested_mapping"]
    blank_provider = client.post(
        f"/api/uploads/{payload['id']}/import",
        json={
            "mapping": mapping_json,
            "source_url": "https://data.example.test/energy.csv",
            "provider": "   ",
            "reference_period": "2025-01",
        },
    )
    assert blank_provider.status_code == 422

    imported = client.post(
        f"/api/uploads/{payload['id']}/import",
        json={
            "mapping": mapping_json,
            "source_url": "https://data.example.test/energy.csv",
            "provider": "전주시 제공자",
            "reference_period": "2025-01",
        },
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["source_type"] == "UNVERIFIED"
    with TestSession() as db:
        assert db.scalar(select(func.count()).select_from(EnergyMonthly)) == 1
        assert db.scalar(select(func.count()).select_from(ImportedRecord)) == 1
        source = db.get(DataSource, imported.json()["source_id"])
        assert source.organization == "전주시 제공자"
        assert source.normalized_row_count == 1
