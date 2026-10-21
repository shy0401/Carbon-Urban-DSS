"""팀 변화 모델 서비스 (urban-carbon 7차, 윤영준) — Carbon Urban DSS가 개발 계획의 배출 변화를 묻는 작은 HTTP 서버.

* 팀 코드와 학습 표는 저장소에 넣지 않는다. ``TEAM_ROOT``(compose에서 ``data/raw/team_urban_carbon``을 읽기 전용으로
  붙임) 아래 가장 새 묶음의 ``code/``(urban-carbon 저장소 사본: ``src/``, ``config/``, ``data/processed/``)를 그대로 쓴다.
  학습 표에는 국토통계지도(국외 반출 금지) 값이 들어 있어 이 컨테이너 밖으로 표를 내보내지 않는다.
* 시작하면 뒤에서 ``00_합본_7차``로 변화 모델을 학습한다. 팀의 ``urban-carbon predict``와 같은 함수(``_Trained``,
  ``_predict_one``)를 그대로 불러 같은 답을 낸다(seed 5개 × 합계·에너지원 3, 사례 쌍 가중 ×10). 1~3분.
* 칸의 지금 상태는 그 지역 표(``data/processed/<코드>_<이름>/training.csv``)에서, 모델·환산 계수·구간은 ``00_합본_7차``에서.

GET /health, GET /status, POST /predict {"region": "52110", "plans": [{"x": 959500, "y": 1760500, "new": [...],
"removed": [...], "years_after": 3}]} — 칸은 이 도구의 500m 격자 왼쪽 아래 좌표(EPSG:5179).
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import threading
import time
import traceback
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

TEAM_ROOT = Path(os.environ.get("TEAM_ROOT", "/team-root"))
TRAIN = os.environ.get("TEAM_TRAIN", "00_합본_7차")
PORT = int(os.environ.get("PORT", "8090"))
MAX_PLANS = 9

STATE: dict[str, Any] = {"status": "starting", "snapshot": None, "train": TRAIN, "started_at": None, "ready_at": None,
                         "train_seconds": None, "error": None, "versions": {}, "regions": [], "acceptance": [], "pair_inputs": None}
_PREDICT_LOCK = threading.Lock()
_CTX: dict[str, Any] = {}
_TABLES: dict[str, Any] = {}


def find_code() -> tuple[str | None, Path | None]:
    """The newest bundle under TEAM_ROOT that has the team code and the training table."""
    if not TEAM_ROOT.is_dir():
        return None, None
    for snap in sorted((p for p in TEAM_ROOT.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))), reverse=True):
        code = snap / "code"
        if (code / "src" / "urban_carbon").is_dir() and (code / "data" / "processed" / TRAIN / "training.csv").is_file():
            return snap.name, code
    return None, None


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def train() -> None:
    snap, code = find_code()
    if code is None:
        STATE.update(status="unavailable", error=f"팀 인계 묶음이 없습니다: {TEAM_ROOT}/<묶음 날짜>/code (src/urban_carbon, data/processed/{TRAIN})")
        return
    try:
        sys.path.insert(0, str(code / "src"))
        import numpy
        import pandas
        import sklearn
        from urban_carbon.core.paths import ProjectPaths
        from urban_carbon.modeling import predict as P
        from urban_carbon.modeling.settings import load_baseline, load_change

        STATE.update(snapshot=snap, versions={"python": sys.version.split()[0], "numpy": numpy.__version__, "pandas": pandas.__version__,
                                              "scikit-learn": sklearn.__version__})
        paths = ProjectPaths(code)
        config = paths.config_dir / "modeling.yaml"
        settings, change = load_baseline(config), load_change(config)
        if change is None:
            raise RuntimeError(f"{config}에 change_model 절이 없습니다")
        processed = paths.processed_dir
        STATE["regions"] = sorted(p.name for p in processed.iterdir() if p.is_dir() and p.name[:5].isdigit() and p.name[5:6] == "_")
        acceptance = processed / TRAIN / "baseline" / "change_acceptance.csv"
        if acceptance.is_file():
            STATE["acceptance"] = pandas.read_csv(acceptance, encoding="utf-8").to_dict("records")
        STATE.update(status="training", started_at=_now())
        t0 = time.time()
        trained = P._Trained(paths, TRAIN, settings, change, None)
        _CTX.update(P=P, paths=paths, settings=settings, change=change, trained=trained, processed=processed, pandas=pandas)
        STATE.update(status="ready", ready_at=_now(), train_seconds=round(time.time() - t0, 1), pair_inputs=int(len(trained.fitted.columns)))
    except Exception as exc:  # noqa: BLE001 - reported on /status
        traceback.print_exc()
        STATE.update(status="error", error=f"{type(exc).__name__}: {exc}")


def region_folder(code: str) -> Path | None:
    processed: Path = _CTX["processed"]
    found = sorted(p for p in processed.glob(f"{code}_*") if p.is_dir())
    return found[0] if found else None


def cell_context(code: str) -> tuple[Any, str, Any]:
    """(context, dataset name, region filter) for a region code.

    학습 42곳은 팀 예시(``predict --name 00_합본_7차``)처럼 합본 표에서 그 지역 행으로 칸 상태를 고르고, 나머지(시험 10곳·동탄)는
    그 지역 표(``--name <지역> --train 00_합본_7차``)를 쓴다. 모델·환산 계수·구간은 어느 쪽이든 합본으로 학습한 것."""
    trained = _CTX["trained"]
    table = trained.table
    if "region" in table:
        names = sorted({str(v) for v in table["region"].unique() if str(v).startswith(f"{code}_")})
        if names:
            return trained, names[0], names[0]
    folder = region_folder(code)
    if folder is None:
        raise LookupError(f"팀 데이터셋에 지역 {code}이(가) 없습니다(53개 지역만)")
    if folder.name not in _TABLES:
        from urban_carbon.modeling.baseline import load_training
        own = load_training(folder)[0]
        missing = [f for f in trained.features if f not in own]
        if missing:
            raise LookupError(f"{folder.name} 표에 학습 입력 {missing}이(가) 없습니다")
        _TABLES[folder.name] = own
    ctx = copy.copy(trained)
    ctx.folder = folder
    ctx.cell_table = _TABLES[folder.name]
    return ctx, folder.name, None


def grid_id_of(table: Any, x: int, y: int, region: str | None) -> str | None:
    rows = table[(table["x_min_m"].round() == x) & (table["y_min_m"].round() == y)]
    if region is not None and "region" in rows:
        rows = rows[rows["region"].astype(str) == region]
    return str(rows["grid_id_500m"].iloc[0]) if len(rows) else None


def _item(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or "use" not in raw or "floor_area_m2" not in raw:
        raise ValueError("항목마다 use와 floor_area_m2가 필요합니다")
    out = {"use": str(raw["use"]), "floor_area_m2": float(raw["floor_area_m2"])}
    for key in ("dwellings", "buildings", "floors", "height_m"):
        if raw.get(key) is not None:
            out[key] = float(raw[key])
    return out


def predict(body: dict[str, Any]) -> dict[str, Any]:
    import yaml

    P, settings, change = _CTX["P"], _CTX["settings"], _CTX["change"]
    code = str(body.get("region") or "")
    plans = body.get("plans") or []
    if not code.isdigit() or len(code) != 5 or not isinstance(plans, list) or not 1 <= len(plans) <= MAX_PLANS:
        raise ValueError(f"region(5자리 코드)과 plans(1~{MAX_PLANS}개)가 필요합니다")
    ctx, dataset, region = cell_context(code)
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, plan in enumerate(plans):
            grid = grid_id_of(ctx.cell_table, int(plan["x"]), int(plan["y"]), region)
            if grid is None:
                raise LookupError(f"칸 ({plan['x']}, {plan['y']})은 {dataset} 표에서 학습에 쓸 수 있는 해가 없습니다(결측·결함 표시 칸)")
            doc: dict[str, Any] = {"cell": grid, "new": [_item(r) for r in plan.get("new") or []],
                                   "removed": [_item(r) for r in plan.get("removed") or []]}
            if region is not None:
                doc["region"] = region
            if plan.get("years_after") is not None:
                doc["years_after"] = int(plan["years_after"])
            if plan.get("zone"):
                doc["zone"] = str(plan["zone"])
            path = Path(tmp) / f"plan_{i + 1}.yaml"
            path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
            result = P._predict_one(ctx, path, settings, change)
            results.append(result)
    out: dict[str, Any] = {"dataset": dataset, "cell_table": TRAIN if region else dataset, "train": TRAIN, "snapshot": STATE["snapshot"],
                           "results": [dict(asdict(r), describe=P.describe(r)) for r in results], "combined": None}
    if len(results) > 1:
        combined = P.combine(results, P.load_unit_bands(_CTX["trained"].train_folder), change)
        out["combined"] = dict(asdict(combined), describe=P.describe_combined(combined))
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "team-model/1"

    def _send(self, code: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=float).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:  # one short line per request, no bodies
        sys.stderr.write("%s %s\n" % (self.command, self.path.split("?")[0]))

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/health"):
            self._send(200, {"ok": True})
        elif self.path.startswith("/status"):
            self._send(200, STATE)
        else:
            self._send(404, {"detail": "없는 주소"})

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.startswith("/predict"):
            self._send(404, {"detail": "없는 주소"})
            return
        if STATE["status"] != "ready":
            self._send(503, {"detail": {"training": "변화 모델을 학습하는 중입니다(1~3분)", "starting": "시작하는 중입니다"}.get(STATE["status"], STATE.get("error") or STATE["status"]),
                             "status": STATE["status"]})
            return
        try:
            length = min(int(self.headers.get("Content-Length") or 0), 64 * 1024)
            body = json.loads(self.rfile.read(length) or b"{}")
            with _PREDICT_LOCK:
                self._send(200, predict(body))
        except (ValueError, KeyError, TypeError) as exc:
            self._send(422, {"detail": str(exc)})
        except LookupError as exc:
            self._send(404, {"detail": str(exc)})
        except Exception as exc:  # noqa: BLE001 - the team code raises its own ConfigError/RawDataError
            traceback.print_exc()
            self._send(422 if type(exc).__name__ in ("ConfigError", "RawDataError") else 500, {"detail": f"{type(exc).__name__}: {exc}"})


def main() -> None:
    threading.Thread(target=train, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
