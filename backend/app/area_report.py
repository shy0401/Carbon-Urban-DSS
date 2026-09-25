"""Area reports (past vs present, before/after development, reduction effort).

Numbers come only from the calculation engine (``area.analyze``). The local model may
write the summary in its own words, but every number, year and direction word it uses is
checked against the engine's facts by ``verify_narrative``. Any mismatch replaces the
model's text with the verified template, so a published report never carries a number
the engine did not produce.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import Field

from .area import AnalyzeInput, analyze
from .db import Session
from .models import now
from .reporting import DecisionReport, local_config

router = APIRouter(prefix="/api/area-reports", tags=["area-reports"])

NUMBER = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
FORBIDDEN = ("넷제로 달성", "탄소중립 달성", "법적으로 적합", "인허가 가능", "허가 가능", "확실히", "보장합니다")


def _variants(value: float | int) -> set[str]:
    """Display forms a correct sentence may use for one engine number."""
    out: set[str] = set()
    v = float(value)
    for digits in (0, 1, 2, 3):
        rounded = round(v, digits)
        text = f"{rounded:.{digits}f}"
        out.add(text)
        out.add(f"{abs(rounded):.{digits}f}")
        if digits == 0:
            out.add(str(int(round(v))))
            out.add(str(abs(int(round(v)))))
    # thousands / 만 units commonly used in Korean prose
    if abs(v) >= 1000:
        out.add(f"{v / 1000:.1f}")
    if abs(v) >= 10000:
        out.add(f"{v / 10000:.1f}")
        out.add(f"{v / 10000:.0f}")
    if abs(v) >= 1_000_000:
        out.add(f"{v / 1_000_000:.1f}")
    return {t.rstrip("0").rstrip(".") if "." in t else t for t in out} | out


def allowed_numbers(facts: list[dict[str, Any]]) -> set[str]:
    allowed: set[str] = set()
    for fact in facts:
        for n in fact.get("numbers", []):
            allowed |= _variants(n)
        for token in NUMBER.findall(fact["text"]):
            allowed.add(token.replace(",", "").lstrip("+"))
    return allowed


def verify_narrative(text: str, facts: list[dict[str, Any]]) -> list[str]:
    """Return violations; an empty list means every number and claim is backed by a fact."""
    problems: list[str] = []
    if not text or not text.strip():
        return ["빈 문장"]
    allowed = allowed_numbers(facts)
    for token in NUMBER.findall(text):
        clean = token.replace(",", "").lstrip("+")
        variants = {clean, clean.lstrip("-")}
        if "." in clean:
            variants.add(clean.rstrip("0").rstrip("."))
        if not variants & allowed:
            problems.append(f"근거에 없는 숫자: {token}")
    for phrase in FORBIDDEN:
        if phrase in text:
            problems.append(f"허용하지 않는 단정 표현: {phrase}")
    # Direction words must agree with the sign of the change they describe.
    change = next((f for f in facts if f["id"] == "change"), None)
    if change and change.get("numbers"):
        pct = change["numbers"][0]
        for sentence in re.split(r"(?<=[.!?다])\s+", text):
            if any(v in sentence for v in _variants(pct)):
                if pct > 0 and "감소" in sentence:
                    problems.append("증가를 감소로 서술")
                if pct < 0 and "증가" in sentence:
                    problems.append("감소를 증가로 서술")
    return problems


AREA_SYSTEM = ("한국어 도시계획 검토 보고서의 요약 문단을 쓴다. 아래 근거 문장 밖의 숫자·연도·사실을 만들지 않는다. "
               "숫자는 근거에 적힌 값 그대로 쓴다. 법적 판단이나 넷제로 달성은 단정하지 않는다. 4~7문장. summary 필드만 출력한다.")
SUMMARY_SCHEMA = {"type": "object", "properties": {"summary": {"type": "string", "maxLength": 1200}}, "required": ["summary"], "additionalProperties": False}


def facts_prompt(facts: list[dict[str, Any]]) -> str:
    """The exact user message the model sees (shared by the app, the training set and the evaluation)."""
    return json.dumps([{"id": f["id"], "text": f["text"]} for f in facts], ensure_ascii=False)


def local_narrative(facts: list[dict[str, Any]], model: str | None = None) -> str:
    base, default_model = local_config()
    with httpx.Client(timeout=120, trust_env=False) as client:
        response = client.post(base + "/api/generate", json={
            "model": model or default_model, "stream": False, "format": SUMMARY_SCHEMA, "system": AREA_SYSTEM, "prompt": facts_prompt(facts),
            "options": {"temperature": 0, "seed": 42, "num_predict": 600, "num_ctx": 4096}, "keep_alive": "2m"})
        response.raise_for_status()
        body = response.json()
        if not body.get("done"):
            raise ValueError("Incomplete generation")
        return str(json.loads(body["response"])["summary"])


def summarize_area(facts: list[dict[str, Any]], use_local: bool) -> dict[str, Any]:
    template = {"mode": "TEMPLATE", "model": None, "paragraphs": [f["text"] for f in facts],
                "validation": "계산 엔진 근거 문장 사용", "violations": []}
    if not use_local:
        return template
    try:
        text = local_narrative(facts)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return dict(template, mode="TEMPLATE_FALLBACK", reason="로컬 모델에 연결할 수 없어 검증된 서식으로 작성했습니다.")
    problems = verify_narrative(text, facts)
    if problems:
        return dict(template, mode="TEMPLATE_FALLBACK", reason="로컬 모델 문장이 근거와 달라 검증된 서식으로 바꿨습니다.", violations=problems, rejected=text)
    return {"mode": "LOCAL_SLM_NARRATIVE", "model": local_config()[1], "paragraphs": [text],
            "validation": "모든 숫자·방향 표현이 계산 엔진 근거와 일치", "violations": [],
            "evidence": [f["text"] for f in facts]}


class AreaReportInput(AnalyzeInput):
    use_local_model: bool = False
    title: str | None = Field(default=None, max_length=80)


def _snapshot(request: AreaReportInput) -> dict[str, Any]:
    with Session() as db:
        result = analyze(db, request.area.model_dump(), request.from_year, request.to_year, request.event_year, request.window,
                         request.plan.model_dump() if request.plan else None, request.target_pct, request.pv_yield_kwh_per_kw)
    history = result["history"]
    history_public = {k: v for k, v in history.items() if k != "area"}
    area = {k: v for k, v in history["area"].items() if k != "geometry"}
    snapshot = {
        "kind": "AREA", "version": 1, "title": request.title or f"{history['area']['label']} 개발 영향·감축 검토",
        "created_at": now().isoformat(), "request": request.model_dump(exclude={"use_local_model"}),
        "area": area, "geometry": history["area"].get("geometry"), "history": history_public,
        "before_after": result["before_after"], "effort": result["effort"], "facts": result["facts"],
        # kept for the shared report list
        "year": request.to_year, "grid_id": None,
    }
    snapshot["evidence_hash"] = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    return snapshot


@router.post("", status_code=201)
def create_area_report(request: AreaReportInput) -> dict[str, Any]:
    try:
        snapshot = _snapshot(request)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from None
    snapshot["summary"] = summarize_area(snapshot["facts"], request.use_local_model)
    rid = str(uuid.uuid4())
    with Session() as db:
        db.add(DecisionReport(id=rid, snapshot=snapshot))
        db.commit()
    return {"id": rid, **snapshot}


@router.get("")
def list_area_reports() -> list[dict[str, Any]]:
    from sqlalchemy import select
    with Session() as db:
        rows = db.scalars(select(DecisionReport).order_by(DecisionReport.created_at.desc()).limit(200))
        return [{"id": r.id, "created_at": r.created_at.isoformat(), "title": r.snapshot.get("title"), "mode": r.snapshot.get("summary", {}).get("mode")}
                for r in rows if r.snapshot.get("kind") == "AREA"][:50]


@router.get("/{report_id}")
def get_area_report(report_id: str) -> dict[str, Any]:
    with Session() as db:
        r = db.get(DecisionReport, report_id)
        if not r or r.snapshot.get("kind") != "AREA":
            raise HTTPException(404, "지역 보고서를 찾을 수 없습니다")
        return {"id": r.id, **r.snapshot}


def area_markdown(s: dict[str, Any]) -> str:
    lines = [f"# {s['title']}", f"지역: {s['area']['label']} | 기간: {s['history']['years'][0]}~{s['history']['years'][-1]} | 작성: {s['created_at']}",
             "## 검토 요약"] + list(s["summary"]["paragraphs"])
    lines += ["## 연도별 관측"]
    table = ["| 연도 | 전력 kWh (12개월 관측 지번) | 전력 탄소 kgCO2eq | 난방도일 | 냉방도일 | 인구 | 사용승인 세대 |", "| --- | --- | --- | --- | --- | --- | --- |"]
    h = s["history"]
    def at(table: dict[Any, Any], year: int) -> dict[str, Any]:
        # JSON storage turns integer year keys into strings; accept both.
        return table.get(str(year)) or table.get(year) or {}

    def fmt(value: float | None) -> str:
        return "자료 없음" if value is None else f"{value:,.0f}"

    for y in h["years"]:
        e, w, p, ev = at(h["energy"], y), at(h["weather"], y), at(h["population"], y), at(h["events"], y)
        elec = e.get("electricity", {})
        table.append(f"| {y} | {fmt(elec.get('kwh'))} ({elec.get('complete_parcels', 0)}곳) | {fmt(e.get('electricity_carbon_kgco2eq'))} | {fmt(w.get('hdd'))} | {fmt(w.get('cdd'))} | {fmt(p.get('population'))} | {int(ev.get('households') or 0):,} |")
    lines.append("\n".join(table))
    lines += ["## 해석 범위", h.get("factor_basis", ""), "관측이 없는 연도는 0이 아니라 자료 없음입니다. 행정동 통계는 격자·반경에 배분하지 않았습니다.",
              "운영 단계 1차 추정이며 법적 적합성이나 넷제로 달성을 판정하지 않습니다."]
    if s.get("effort") and s["effort"].get("available"):
        lines += ["## 감축 노력 계산의 가정"] + [f"- {a}" for a in s["effort"]["assumptions"]]
    lines += ["## 재현 정보", f"근거 SHA256: {s['evidence_hash']}", f"작성 방식: {s['summary']['mode']} — {s['summary']['validation']}"]
    return "\n\n".join(lines) + "\n"


@router.get("/{report_id}/markdown")
def download_area_report(report_id: str) -> Response:
    report = get_area_report(report_id)
    return Response(area_markdown(report), media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="area-report-{report_id}.md"'})
