"""팀 변화 모델(urban-carbon 7차, 윤영준) 연결: 500m 칸에 개발 계획을 넣으면 건물 배출 변화(tCO₂e)와 구간을 돌려준다.

모델은 ``team-model`` 컨테이너(``deploy/team-model/server.py``, compose ``--profile team-model``)가 팀 코드 그대로 학습·예측한다.
이 모듈은 그 서비스에 묻고, 칸의 과거 개발 사례(탄소공간지도 실제 변화와 모델 점수)를 DB에서 함께 준다.

* 값의 구분: 모델 예측은 **추정(시나리오)** 이다. 관측(탄소공간지도)과 섞지 않고, 구간(q10~q90)·경고·자동으로 채운 값을 함께 낸다.
  1,000 tCO₂e 미만의 변화는 방향만 읽는다(팀 시험: 1천 미만 사례 오차 중앙값 2.4).
* 공개 시연 주소: 학습 표·칸 상태에 국토통계지도(국외 반출 금지) 값이 들어 있어 게이트웨이를 거친 요청은 거부한다.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .db import Session

router = APIRouter(prefix="/api/team-model")
SERVICE = os.getenv("TEAM_MODEL_URL", "http://team-model:8090")
RESTRICTED = "팀 변화 모델은 학습 표에 국토통계지도(국외 반출 금지) 값이 있어 공개 시연 주소에서 제공하지 않습니다. 이 PC의 화면에서만 쓸 수 있습니다."
OFF = "팀 변화 모델 서비스가 꺼져 있습니다. 팀 인계 묶음이 있는 PC에서 `docker compose --profile team-model up -d team-model`로 켭니다."
USES = ("residential", "commercial", "large_retail", "office", "officetel", "industrial", "knowledge_industry", "education", "medical_welfare", "other")
# 팀 결과(2026-10-20, 00_합본_7차): 채택 기준과 학습에 없던 10개 지역 153사례 시험. 출처: 팀 인계 문서 5절, docs/results/model-results-ledger.md
ACCURACY = {
    "model": "HistGradientBoosting 변화 모델, seed 5개 평균, 개발 사례 쌍 가중 ×10 (ADR 0028)",
    "train": "42개 지역 259,160행(500m 칸 × 7개 해), 학습 쌍 573,018행",
    "test": [
        {"band": "1천 tCO₂e 미만", "cases": 52, "median_error": 2.4, "within_50pct": 0.21, "sum_ratio": 4.2, "note": "수치로 읽지 않는 구간"},
        {"band": "1천~1만", "cases": 96, "median_error": 0.27, "within_50pct": 0.71, "sum_ratio": 1.09},
        {"band": "1만 이상", "cases": 5, "median_error": 0.30, "within_50pct": 0.80, "sum_ratio": 0.63, "note": "개발 단위 9개 합 0.80"},
        {"band": "1천 이상 전체", "cases": 101, "median_error": 0.27, "within_50pct": 0.67, "sum_ratio": 0.99},
    ],
    "by_use": "주거 0.30 · 복합 0.31 · 상업·업무 0.42 · 기타 비주거 0.46 · 공업 0.60(합 0.63, 범위 밖)",
    "band_coverage": "80% 구간(q10~q90) 시험 포함률 0.81",
    "source": "팀 인계 문서(2026-10-20) 5절",
}


def _public(request: Request) -> bool:
    from .team_grid import is_public
    return is_public(request)


def _call(path: str, body: dict[str, Any] | None = None, timeout: float = 5.0) -> tuple[int, Any]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(SERVICE + path, data=data, headers={"Content-Type": "application/json"} if data else {},
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            return exc.code, {"detail": str(exc)}
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, None


def service_status() -> dict[str, Any]:
    code, body = _call("/status", timeout=3.0)
    if code != 200 or not isinstance(body, dict):
        return {"status": "off", "reason": OFF}
    keep = ("status", "snapshot", "train", "ready_at", "train_seconds", "error", "versions", "acceptance")
    out = {k: body.get(k) for k in keep}
    out["regions"] = [r[:5] for r in body.get("regions") or []]
    if out["status"] == "unavailable":
        out["reason"] = body.get("error")
    return out


def team_dataset(db: Any, region_code: str | None) -> str | None:
    """The team dataset names of a region (``52110_전주시``; a city with 일반구 may have several, comma-joined)."""
    from .team_grid import region_datasets
    names = region_datasets(db, region_code)
    return ", ".join(names) if names else None


def cell_dataset(db: Any, region_code: str | None, x: int, y: int) -> str | None:
    """The team dataset that holds this 500m cell (of a city's 구, the one with the larger part)."""
    from sqlalchemy import select

    from .team_grid import TeamGrid500, region_datasets
    names = region_datasets(db, region_code)
    if not names:
        return None
    rows = db.execute(select(TeamGrid500.dataset, TeamGrid500.total_t).where(TeamGrid500.dataset.in_(names), TeamGrid500.x == x, TeamGrid500.y == y)).all()
    if not rows:
        return None
    best: dict[str, float] = {}
    for name, total in rows:
        best[name] = max(best.get(name, 0.0), total or 0.0)
    return max(sorted(best), key=lambda n: best[n])


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    if _public(request):
        return {"status": "restricted", "reason": RESTRICTED}
    return dict(service_status(), accuracy=ACCURACY)


@router.get("/cell")
def cell(request: Request, grid: str = Query(..., max_length=40), region: str | None = Query(None, max_length=10)) -> dict[str, Any]:
    """칸의 팀 자료: 데이터셋 이름, 이 칸의 개발 사례(모든 전후 해 쌍, 점수가 있는 쌍은 모델 예측과 함께)."""
    if _public(request):
        raise HTTPException(403, RESTRICTED)
    m = re.fullmatch(r"cell_(\d+)_(\d+)", grid)
    if not m:
        raise HTTPException(422, "격자 이름은 cell_<x>_<y>입니다")
    from .regions import region_for_grid
    from .team_grid import dataset_region, developments
    with Session() as db:
        code = region or region_for_grid(db, grid)
        dataset = cell_dataset(db, code, int(m.group(1)), int(m.group(2)))
        cases = [d for d in developments(db, code) if d["grid_id"] == grid] if dataset else []
    scored = [d for d in cases if d.get("model")]
    # the model answers per team region (a 구 of a city has its own table): the code to send with /predict
    return {"region": code, "dataset": dataset, "model_region": dataset_region(dataset) if dataset else None, "grid": grid,
            "cases": cases, "scored": len(scored)}


Use = Literal["residential", "commercial", "large_retail", "office", "officetel", "industrial", "knowledge_industry", "education",
              "medical_welfare", "other"]


class Item(BaseModel):
    use: Use = "residential"
    floor_area_m2: float = Field(gt=0, le=3_000_000)
    dwellings: float | None = Field(default=None, ge=0, le=50_000)


class PlanIn(BaseModel):
    grid: str = Field(pattern=r"^cell_\d+_\d+$", max_length=40)
    new: list[Item] = Field(default_factory=list, max_length=10)
    removed: list[Item] = Field(default_factory=list, max_length=10)
    years_after: int | None = Field(default=None, ge=1, le=10)


class PredictIn(BaseModel):
    region: str | None = Field(default=None, max_length=10)
    plans: list[PlanIn] = Field(min_length=1, max_length=9)


def _xy(grid: str) -> tuple[int, int]:
    m = re.fullmatch(r"cell_(\d+)_(\d+)", grid)
    assert m  # checked by the model
    return int(m.group(1)), int(m.group(2))


@router.post("/predict")
def predict(body: PredictIn, request: Request) -> dict[str, Any]:
    """개발 계획(칸마다 신축·철거 용도별 연면적)의 배출 변화 예측. 여러 칸이면 개발 단위로 합친 값도 준다."""
    if _public(request):
        raise HTTPException(403, RESTRICTED)
    if any(not p.new and not p.removed for p in body.plans):
        raise HTTPException(422, "칸마다 신축이나 철거를 하나 이상 적어 주세요")
    from .regions import region_for_grid
    with Session() as db:
        code = body.region or region_for_grid(db, body.plans[0].grid)
    if not code:
        raise HTTPException(422, "지역을 알 수 없습니다")
    plans = []
    for p in body.plans:
        x, y = _xy(p.grid)
        plans.append({"x": x, "y": y, "new": [i.model_dump(exclude_none=True) for i in p.new],
                      "removed": [i.model_dump(exclude_none=True) for i in p.removed], "years_after": p.years_after})
    status_code, answer = _call("/predict", {"region": code, "plans": plans}, timeout=240.0)
    if status_code == 0:
        raise HTTPException(503, OFF)
    if status_code != 200:
        detail = (answer or {}).get("detail") if isinstance(answer, dict) else None
        raise HTTPException(status_code if status_code in (404, 422, 503) else 502, detail or "팀 변화 모델이 답하지 못했습니다")
    for r, p in zip(answer.get("results") or [], body.plans):
        r["grid"] = p.grid
    answer["data_class"] = "SCENARIO"
    answer["note"] = ("팀 변화 모델의 추정입니다(탄소공간지도 건물 배출의 변화, tCO₂e/년). 관측과 섞지 않습니다. "
                      "1,000 tCO₂e 미만은 방향만 읽고, 구간은 사례 잔차의 q10~q90입니다.")
    return answer
