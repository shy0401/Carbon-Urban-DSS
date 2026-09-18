"""Safe operational readiness view for collection, normalization and data use."""
from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from .models import DataSource, EnergyMonthly, Grid, RawDataAsset
from .settings import offline_mode


REGISTRY: dict[str, dict[str, Any]] = {
    "kapt_energy": dict(label="K-apt 월별 에너지", acquisition="API_KEY", collection_dataset="kapt_energy", credentials=["DATA_GO_KR_SERVICE_KEY"], scopes={"smoke": "1단지 × 1개월", "limited": "3단지 × 12개월", "full": "전체 단지 × 12개월"}, products=["단지·월 에너지", "전기 탄소"], uses=["월별 에너지 관측", "운영탄소", "실데이터 모델 학습"]),
    "energy": dict(label="건축HUB 건물에너지", acquisition="API_KEY", collection_dataset="energy", credentials=["DATA_GO_KR_SERVICE_KEY"], scopes={"smoke": "후보 지번 제한", "limited": "최대 12개월", "full": "전주시 전수화 추가 개발"}, products=["지번별 전력·가스"], uses=["격자별 에너지", "운영탄소", "모델 검증"]),
    "building_official": dict(label="건축HUB 건축물대장", acquisition="API_KEY", collection_dataset=None, credentials=["DATA_GO_KR_SERVICE_KEY"], scopes={}, products=["공식 연면적", "층수", "현재 FAR/BCR"], uses=["건물 속성 보정", "용적률 분석", "에너지 원단위"]),
    "weather_kma": dict(label="KMA ASOS 전주 146", acquisition="API_KEY", collection_dataset="kma_asos", credentials=["DATA_GO_KR_SERVICE_KEY"], scopes={"smoke": "2025년 1월", "limited": "선택연도 12개월", "full": "선택연도 12개월"}, products=["일별 기상", "완전월 기상"], uses=["기상 보정", "HDD/CDD", "에너지 모델 설명변수"]),
    "sgis_admin": dict(label="SGIS 행정구역 인구·가구", acquisition="API_KEY", collection_dataset="sgis", credentials=["SGIS_CONSUMER_KEY", "SGIS_CONSUMER_SECRET"], scopes={"smoke": "전주시 인구", "limited": "전주시 인구·가구", "full": "전주시 인구·가구"}, products=["행정구역 인구", "가구", "비공개 상태"], uses=["도시 현황 비교", "수요 지표", "보고서 근거"]),
    "sgis_grid": dict(label="SGIS 공식 500m 격자", acquisition="MANUAL_DOWNLOAD", collection_dataset=None, credentials=[], scopes={}, products=["공식 격자 ID", "500m 인구", "비밀보호 표식"], uses=["인구밀도 지도", "자체 격자 교차검증", "수용량 분석"]),
    "vworld_zoning": dict(label="VWorld 용도지역", acquisition="API_KEY", collection_dataset="vworld_zoning", credentials=["VWORLD_API_KEY", "VWORLD_DOMAIN"], scopes={"smoke": "분석격자 1개 bbox", "limited": "분석격자 25개 bbox", "full": "분석격자 전체 bbox"}, products=["용도지역 도형", "격자별 교차비율"], uses=["토지이용 지도", "시나리오 제약 근거", "보고서 출처"]),
    "vworld_cadastral": dict(label="VWorld 연속지적", acquisition="API_KEY", collection_dataset="vworld_cadastral", credentials=["VWORLD_API_KEY", "VWORLD_DOMAIN"], scopes={"smoke": "분석격자 1개 bbox", "limited": "분석격자 25개 bbox", "full": "분석격자 전체 bbox"}, products=["PNU", "필지 경계", "법정동·지번"], uses=["에너지 지번 매칭", "건축물 연결", "공간 품질검증"]),
    "factors": dict(label="공식 에너지 배출계수", acquisition="MANUAL_DOWNLOAD", collection_dataset=None, credentials=[], scopes={}, products=["에너지원별 계수", "적용연도·단위"], uses=["전기 운영탄소", "가스 계수 검증", "보고서 산식"]),
    "kapt": dict(label="K-apt 공동주택 기본정보", acquisition="OPEN_WEB", collection_dataset=None, credentials=[], scopes={}, products=["단지 위치", "주소", "연면적"], uses=["에너지 단지 매칭", "격자 연결", "대상지 설명"]),
    "jeonju_apartments": dict(label="전주시 공동주택 공개자료", acquisition="OPEN_FILE", collection_dataset=None, credentials=[], scopes={}, products=["준공·공사중 공동주택"], uses=["공동주택 모집단 비교", "K-apt 누락 검토"]),
    "weather": dict(label="ERA5-Land 대체 기상", acquisition="OPEN_API", collection_dataset="weather", credentials=[], scopes={"smoke": "저장 원본 재사용", "limited": "최대 12개월", "full": "최대 12개월"}, products=["월평균 기온", "강수", "HDD/CDD"], uses=["KMA 결측 대체", "기상 차트", "에너지 모델 설명변수"]),
    "buildings": dict(label="OSM 건물", acquisition="OPEN_API", collection_dataset=None, credentials=[], scopes={}, products=["건물 윤곽", "일부 층수"], uses=["지도 시각화", "공간 범위", "공식 건물과 비교"]),
    "boundary": dict(label="OSM 전주시 경계", acquisition="OPEN_API", collection_dataset=None, credentials=[], scopes={}, products=["분석 경계"], uses=["지도 클리핑", "격자 생성 범위"]),
    "regions": dict(label="법정동 코드", acquisition="OPEN_FILE", collection_dataset=None, credentials=[], scopes={}, products=["법정동 코드·명칭"], uses=["공공 API 요청", "주소 정규화"]),
    "grid": dict(label="프로젝트 500m 분석격자", acquisition="DERIVED", collection_dataset=None, credentials=[], scopes={}, products=["EPSG:5179 500m 격자"], uses=["지도 집계", "공간 교차", "대상지 선택"]),
}


def _credential_rows(names: list[str]) -> list[dict[str, Any]]:
    return [{"name": name, "configured": bool(os.getenv(name, "").strip())} for name in names]


def _state(source: DataSource | None, meta: dict[str, Any], credentials: list[dict[str, Any]]) -> str:
    status = (source.status if source else "NOT_COLLECTED").upper()
    rows = source.normalized_row_count if source else 0
    if status == "REPLACED":
        return "REPLACED"
    if rows and status in {"COLLECTED", "SUCCESS", "COMPLETED"}:
        return "COLLECTED"
    if rows or status in {"PARTIAL", "FALLBACK"}:
        return "PARTIAL"
    if meta["acquisition"] == "MANUAL_DOWNLOAD" or status == "MANUAL_DOWNLOAD_REQUIRED":
        return "MANUAL_REQUIRED"
    if credentials and not all(item["configured"] for item in credentials):
        return "CREDENTIAL_REQUIRED"
    if status in {"NEEDS_API_KEY", "NEEDS_API_APPROVAL", "FAILED", "ERROR"}:
        return "APPROVAL_OR_FIX_REQUIRED"
    if meta["acquisition"] in {"OPEN_API", "OPEN_FILE", "OPEN_WEB", "DERIVED"}:
        return "AVAILABLE"
    return "NOT_COLLECTED"


def build_readiness(db: Any) -> dict[str, Any]:
    stored = {row.id: row for row in db.scalars(select(DataSource))}
    source_ids = list(REGISTRY) + sorted(set(stored) - set(REGISTRY))
    rows = []
    is_offline = offline_mode()
    for source_id in source_ids:
        source = stored.get(source_id)
        meta = REGISTRY.get(source_id, dict(label=source.name if source else source_id, acquisition="CATALOG", collection_dataset=None, credentials=[], scopes={}, products=[], uses=[]))
        credentials = _credential_rows(meta["credentials"])
        state = _state(source, meta, credentials)
        status = source.status if source else "NOT_COLLECTED"
        blocker = None
        if state == "CREDENTIAL_REQUIRED":
            blocker = "환경변수 미설정: " + ", ".join(item["name"] for item in credentials if not item["configured"])
        elif state == "APPROVAL_OR_FIX_REQUIRED":
            blocker = source.quality if source and source.quality not in {"자료 없음", ""} else "서비스 활용 승인 또는 최근 오류 확인 필요"
        elif state == "MANUAL_REQUIRED":
            blocker = "공식 포털에서 원본 파일을 내려받아 업로드해야 합니다."
        collectable = bool(meta["collection_dataset"] and not is_offline and state in {"AVAILABLE", "PARTIAL", "COLLECTED", "NOT_COLLECTED"})
        rows.append({
            "id": source_id, "name": source.name if source else meta["label"],
            "organization": source.organization if source else None,
            "source_url": source.source_url if source else None,
            "status": status, "state": state, "acquisition": meta["acquisition"],
            "collection_dataset": meta["collection_dataset"], "collectable_now": collectable,
            "credentials": credentials, "scopes": meta["scopes"], "products": meta["products"], "uses": meta["uses"],
            "raw_rows": source.raw_row_count if source else 0,
            "normalized_rows": source.normalized_row_count if source else 0,
            "reference_period": source.reference_period if source else None,
            "limitation": source.limitation if source else None,
            "blocker": blocker,
        })
    counts = Counter(row["state"] for row in rows)
    raw_assets = db.scalar(select(func.count()).select_from(RawDataAsset)) or 0
    normalized = sum(int(row["normalized_rows"] or 0) for row in rows)
    grids = db.scalar(select(func.count()).select_from(Grid)) or 0
    observations = db.scalar(select(func.count()).select_from(EnergyMonthly)) or 0
    pipeline = [
        {"id": "acquire", "label": "수집", "value": len(rows), "detail": "공식 API·공개자료·수동 원본"},
        {"id": "raw", "label": "원본 보존", "value": raw_assets, "detail": "응답·파일·출처·시각"},
        {"id": "normalize", "label": "정규화", "value": normalized, "detail": "단위·기간·결측 상태"},
        {"id": "spatial", "label": "공간 연결", "value": grids, "detail": "EPSG:5179 500m 격자"},
        {"id": "analyze", "label": "분석", "value": observations, "detail": "월별 에너지 관측"},
        {"id": "decision", "label": "의사결정", "value": 4, "detail": "지도·탄소·모델·보고서"},
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(), "offline_mode": is_offline,
        "summary": {"total_sources": len(rows), "states": dict(counts), "collectable_now": sum(row["collectable_now"] for row in rows)},
        "pipeline": pipeline, "sources": rows,
        "truth_rules": ["0행은 미수집이며 실제 사용량 0과 다릅니다.", "행정구역 통계를 500m 격자에 임의 배분하지 않습니다.", "단위와 배출계수가 검증되지 않은 에너지원은 탄소로 합산하지 않습니다."],
    }
