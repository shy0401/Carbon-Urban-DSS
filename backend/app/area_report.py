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
from .reporting import DecisionReport, local_config, narrative_model

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


EFFORT_FACTS = ("effort_target", "effort_new", "effort_all", "effort_met", "effort_offset")


def _signatures(facts: Any) -> set[float]:
    """Distinctive numbers of the facts: not years and not small round shares that any sentence may repeat."""
    out: set[float] = set()
    for fact in facts:
        for n in fact.get("numbers", []):
            v = float(n)
            if (v.is_integer() and 1900 <= v <= 2100) or abs(v) < 100:
                continue
            out.add(v)
    return out


def _mentions_any(text: str, values: set[float]) -> bool:
    tokens = {t.replace(",", "").lstrip("+-") for t in NUMBER.findall(text)}
    tokens |= {t.rstrip("0").rstrip(".") for t in tokens if "." in t}
    return any(_variants(v) & tokens for v in values)


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
    # A reduction amount means nothing without what it is measured against: when the engine states the basis
    # (all metered buildings, or an estimated baseline), a summary that quotes the effort must also quote the basis.
    basis = next((f for f in facts if f["id"] == "effort_basis"), None)
    if basis and _mentions_any(text, _signatures(f for f in facts if f["id"] in EFFORT_FACTS)) and not _mentions_any(text, _signatures([basis])):
        problems.append("감축 기준 설명 없이 감축량 서술")
    # Direction words must agree with the sign of every change they describe ('change' predates signed_pct).
    for fact in facts:
        pct = fact.get("signed_pct")
        if pct is None and fact["id"] == "change" and fact.get("numbers"):
            pct = fact["numbers"][0]
        if not pct:
            continue
        for sentence in re.split(r"(?<=[.!?다])\s+", text):
            if any(v in sentence for v in _variants(pct)):
                if pct > 0 and "감소" in sentence and "증가를 감소로 서술" not in problems:
                    problems.append("증가를 감소로 서술")
                if pct < 0 and "증가" in sentence and "감소를 증가로 서술" not in problems:
                    problems.append("감소를 증가로 서술")
    return problems


AREA_SYSTEM = ("한국어 도시계획 검토 보고서의 요약 문단을 쓴다. 아래 근거 문장 밖의 숫자·연도·사실을 만들지 않는다. "
               "숫자는 근거에 적힌 값 그대로 쓴다. 법적 판단이나 넷제로 달성은 단정하지 않는다. 4~7문장. summary 필드만 출력한다.")
SUMMARY_SCHEMA = {"type": "object", "properties": {"summary": {"type": "string", "maxLength": 1200}}, "required": ["summary"], "additionalProperties": False}


def facts_prompt(facts: list[dict[str, Any]]) -> str:
    """The exact user message the model sees (shared by the app, the training set and the evaluation)."""
    return json.dumps([{"id": f["id"], "text": f["text"]} for f in facts], ensure_ascii=False)


def local_narrative(facts: list[dict[str, Any]], model: str | None = None) -> str:
    base, _ = local_config()
    with httpx.Client(timeout=120, trust_env=False) as client:
        response = client.post(base + "/api/generate", json={
            "model": model or narrative_model(), "stream": False, "format": SUMMARY_SCHEMA, "system": AREA_SYSTEM, "prompt": facts_prompt(facts),
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
    return {"mode": "LOCAL_SLM_NARRATIVE", "model": narrative_model(), "paragraphs": [text],
            "validation": "모든 숫자·방향 표현이 계산 엔진 근거와 일치", "violations": [],
            "evidence": [f["text"] for f in facts]}


class AreaReportInput(AnalyzeInput):
    use_local_model: bool = False
    title: str | None = Field(default=None, max_length=80)


def _snapshot(request: AreaReportInput) -> dict[str, Any]:
    with Session() as db:
        result = analyze(db, request.area.model_dump(), request.from_year, request.to_year, request.event_year, request.window,
                         request.plan.model_dump() if request.plan else None, request.target_pct, request.pv_yield_kwh_per_kw, region=request.region,
                         effort_basis=request.effort_basis)
    history = result["history"]
    history_public = {k: v for k, v in history.items() if k != "area"}
    area = {k: v for k, v in history["area"].items() if k != "geometry"}
    snapshot = {
        "kind": "AREA", "version": 1, "title": request.title or f"{history['area']['label']} 개발 영향·감축 검토",
        "created_at": now().isoformat(), "request": request.model_dump(exclude={"use_local_model"}),
        "area": area, "geometry": history["area"].get("geometry"), "history": history_public,
        "before_after": result["before_after"], "effort": result["effort"], "facts": result["facts"], "region": result.get("region"),
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
    be = (h.get("building_energy") or {}).get("years") or {}
    if be:
        rows = ["| 연도 | 계측 지번 | 12개월 전력 지번 | 전력 kWh | 가스 kWh | 전력 원단위 kWh/m² | 전력 탄소 kgCO2eq |", "| --- | --- | --- | --- | --- | --- | --- |"]
        for year in sorted(be, key=lambda y: int(y)):
            v = be[year]
            rows.append(f"| {year}{' (일부 결측·비교 제외)' if v.get('provider_gap') else ''} | {v['parcels']:,} | {v['electricity_complete']:,} | {fmt(v.get('electricity_kwh'))} | {fmt(v.get('gas_kwh'))} | "
                        f"{'자료 없음' if v.get('kwh_per_m2') is None else format(v['kwh_per_m2'], ',.1f')} | {fmt(v.get('electricity_carbon_kgco2eq'))} |")
        t = (h.get("building_energy") or {}).get("trend")
        if t and t.get("same_change_pct") is not None:
            rows.append("")
            rows.append(f"같은 지번 비교({t['from']}→{t['to']}): 두 해 모두 12개월 계측된 지번 {t['same_parcels']:,}곳의 전력 {t['same_from_kwh']:,.0f} → {t['same_to_kwh']:,.0f} kWh "
                        f"({t['same_change_pct']:+.1f}%). {t['to']}년에만 계측 {t['new_parcels']:,}곳 {t['new_kwh']:,.0f} kWh, {t['from']}년에만 계측 {t['gone_parcels']:,}곳 {t['gone_kwh']:,.0f} kWh "
                        "(신축·계량 변경·다른 지번으로의 기록 이동이 섞일 수 있음).")
        lines += ["## 건물 전체 에너지 (건축HUB 전 지번)", "\n".join(rows),
                  "상가·업무·학교·대형 공동주택 등 건축HUB가 계측하는 모든 지번의 합계입니다. 단독주택, 200세대 미만 공동주택, 산업·수송용은 제공 범위 밖입니다. 원단위는 같은 필지의 건축물대장 연면적 기준입니다."
                  + "".join(f" {year}년: {be[year]['provider_gap']}." for year in sorted(be, key=lambda y: int(y)) if be[year].get("provider_gap"))]
    sg = h.get("sgis_grid") or {}
    if sg.get("overlap"):
        o = sg["overlap"]
        pct = lambda v: "자료 부족" if v is None else f"{v:,.1f}%"  # noqa: E731
        lines += [f"## 지역 특성 (SGIS {sg['year']}년 1km 격자)",
                  f"구역이 걸친 1km 격자 {sg['cells']}개(통계 있는 격자 {sg['cells_with_stats']}개)의 합계입니다. 구역은 이 격자 면적의 {sg['coverage_pct']:,.1f}%입니다.",
                  "\n".join(["| 항목 | 값 |", "| --- | --- |",
                             f"| 인구 | {fmt(o.get('population'))} |", f"| 가구 | {fmt(o.get('households'))} |", f"| 주택 | {fmt(o.get('housing'))} |",
                             f"| 사업체 | {fmt(o.get('businesses'))} |", f"| 종사자 | {fmt(o.get('workers'))} |",
                             f"| 65세 이상 비율 | {pct(o.get('elderly_pct'))} |", f"| 1인가구 비율 | {pct(o.get('single_household_pct'))} |",
                             f"| 2000년 이전 준공 주택 비율 | {pct(o.get('old_housing_pct'))} |", f"| 아파트 비율 | {pct(o.get('apartment_pct'))} |"]),
                  "공식 격자 통계(공공데이터포털, 기준시점 6월 30일)이며 비밀보호를 위해 5 미만 값은 0 또는 5로 확률 대체되고 그 이상은 최대 ±7의 잡음이 들어 있습니다. 통계가 없는 격자는 0이 아니라 통계 없음입니다."]
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
