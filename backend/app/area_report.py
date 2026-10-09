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

from .area import AnalyzeInput, analyze, benchmark, benchmark_position, only_in
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
# Output token budget. Qwen splits every digit into its own token, so a number-heavy Korean summary can approach one token
# per character; the training targets run up to llm_dataset.MAX_SUMMARY (1,100) characters. With 600 the JSON was cut
# mid-string for the longer summaries (2026-10-05: 23 of 40 held-out answers of the retrained model).
NARRATIVE_MAX_TOKENS = 1280
# The retrained writer answers in 30~90 s on the PC's CPU Ollama (longer summaries); loading the model adds ~30 s.
# The nginx proxies in front of the API wait 240 s (frontend/nginx.conf, deploy/gateway.conf), so this must stay below that
# minus the area analysis itself. Keeping the model loaded for 10 minutes avoids the reload between consecutive reports.
NARRATIVE_TIMEOUT_S = 180
NARRATIVE_KEEP_ALIVE = "10m"


# Facts the summary is written from. The long context sentences (SGIS 1km grid totals, the 2020 provider gap,
# comparison-gap notes, the rules line) stay in the report body but are not sent to the model: they made the
# prompt longer than the 2,048-token training window and no summary sentence is built from them.
# The checker still sees every fact, so a number from those sentences is not flagged as invented.
NARRATIVE_FACTS = frozenset({
    "scope", "coverage", "development", "register", "building_energy", "building_energy_trend",
    "latest_energy", "latest_carbon", "latest_intensity", "event", "before_after", "change", "new_share",
    "estimated_change", "effort_fallback", "effort_basis", "effort_target", "effort_met", "effort_new", "effort_all", "effort_offset",
})


def facts_prompt(facts: list[dict[str, Any]]) -> str:
    """The exact user message the model sees (shared by the app, the training set and the evaluation)."""
    return json.dumps([{"id": f["id"], "text": f["text"]} for f in facts if f["id"] in NARRATIVE_FACTS], ensure_ascii=False)


def local_narrative(facts: list[dict[str, Any]], model: str | None = None) -> str:
    base, _ = local_config()
    with httpx.Client(timeout=NARRATIVE_TIMEOUT_S, trust_env=False) as client:
        response = client.post(base + "/api/generate", json={
            "model": model or narrative_model(), "stream": False, "format": SUMMARY_SCHEMA, "system": AREA_SYSTEM, "prompt": facts_prompt(facts),
            "options": {"temperature": 0, "seed": 42, "num_predict": NARRATIVE_MAX_TOKENS, "num_ctx": 4096}, "keep_alive": NARRATIVE_KEEP_ALIVE})
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
                         effort_basis=request.effort_basis, measures=request.measures.model_dump() if request.measures else None)
    history = result["history"]
    facts = list(result["facts"])
    bench = None
    e = result["effort"] or {}
    if e.get("available") and e.get("baseline_mode") == "OBSERVED":
        try:
            with Session() as db:
                table = benchmark(db, list(range(request.from_year, request.to_year + 1)), request.region, e["basis"])
            position = benchmark_position(table, e.get("baseline_year"), e.get("intensity_kwh_per_m2"))
            if position:
                bench = {k: table[k] for k in ("basis", "basis_label", "reference_year", "count", "median", "quintiles", "min", "max", "note")} | {"position": position}
                region_name = (result.get("region") or {}).get("short_name") or "같은 시·군·구"
                facts.insert(next((i for i, f in enumerate(facts) if f["id"] == "rules"), len(facts)), {
                    "id": "benchmark",
                    "text": f"{region_name} 행정동 {position['count']}곳의 {table['reference_year']}년 {table['basis_label']} 관측 전력 원단위(중앙값 {table['median']:,.2f} kWh/m²·년)와 비교하면 "
                            f"이 구역({e['intensity_kwh_per_m2']:,.2f})은 낮은 쪽부터 {position['rank']}번째입니다"
                            + (f"(5분위 중 {position['quintile']}분위)" if position.get("quintile") else "") + ". 건물 구성이 달라 등급이 아니라 위치입니다.",
                    "numbers": [position["count"], table["reference_year"], table["median"], round(e["intensity_kwh_per_m2"], 2), position["rank"],
                                *([position["quintile"]] if position.get("quintile") else [])]})
        except Exception as exc:  # noqa: BLE001 - the comparison is context; the report stands without it
            print("행정동 비교 생략:", type(exc).__name__, exc)
    history_public = {k: v for k, v in history.items() if k != "area"}
    area = {k: v for k, v in history["area"].items() if k != "geometry"}
    snapshot = {
        "kind": "AREA", "version": 1, "title": request.title or f"{history['area']['label']} 개발 영향·감축 검토",
        "created_at": now().isoformat(), "request": request.model_dump(exclude={"use_local_model"}),
        "area": area, "geometry": history["area"].get("geometry"), "history": history_public,
        "before_after": result["before_after"], "effort": result["effort"], "facts": facts, "region": result.get("region"), "benchmark": bench,
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


def _t(kg: float | None) -> str:
    return "자료 없음" if kg is None else f"{kg / 1000:,.1f} tCO2eq/년"


def key_results(s: dict[str, Any]) -> list[tuple[str, str]]:
    """The few lines a reviewer reads first (all values straight from the engine's effort result)."""
    e = s.get("effort") or {}
    if not e:
        return []
    if not e.get("available"):
        return [("감축 노력", e.get("reason") or "계산할 근거가 없습니다")]
    mode = "관측" if e.get("baseline_mode") == "OBSERVED" else "추정"
    basis = f"{e.get('basis_label')} · {e['baseline_year']}년 {mode}"
    if e.get("fallback_from"):
        basis += " (요청한 기준에 근거가 없어 자동 전환)"
    out = [("기준", basis), ("기준 배출", _t(e.get("baseline_kgco2eq"))),
           ("계획 반영 배출(추가 대책 없음)", _t(e.get("bau_kgco2eq"))),
           (f"목표({e['target_pct']:,.0f}% 감축)", _t(e.get("target_kgco2eq"))),
           ("필요 감축량", "추가 감축 불필요" if e.get("already_met") else _t(e.get("required_reduction_kgco2eq")))]
    mix = e.get("mix")
    if mix and not e.get("already_met"):
        out.append(("감축 수단 조합", f"{_t(mix['total_kgco2eq'])} — " + ("목표 달성" if mix["met"] else f"목표까지 {_t(mix['gap_kgco2eq'])} 부족")))
    b = s.get("benchmark")
    if b and b.get("position"):
        out.append(("같은 시·군·구 행정동 비교", f"{b['reference_year']}년 원단위 낮은 쪽부터 {b['position']['rank']}/{b['position']['count']}번째"))
    return out


# 보고서 HTML(인쇄·PDF 저장용)의 장 구성: 기후변화영향평가서(온실가스) 항목 순서 — 대상·방법 → 배출 현황 → 영향 → 목표 → 감축 방안 → 한계.
HTML_SECTIONS = (
    ("1. 검토 대상과 방법", ("scope", "coverage", "rules")),
    ("2. 온실가스 배출 현황 (관측)", ("latest_energy", "latest_carbon", "latest_intensity", "building_energy", "building_energy_trend", "building_energy_gap", "benchmark")),
    ("3. 개발 이력과 전후 영향", ("development", "register", "event", "before_after", "change", "new_share", "estimated_change", "gap_")),
    ("4. 감축 목표와 필요 감축량", ("effort_fallback", "effort_basis", "effort_target", "effort_met")),
    ("5. 감축 방안", ("effort_new", "effort_all", "effort_offset", "effort_pv", "effort_mix", "effort_mix_gap")),
    ("6. 지역 특성 (SGIS 1km 격자)", ("sgis_grid", "sgis_grid_shares")),
)

HTML_STYLE = """
:root{--ink:#1d2430;--muted:#5b6575;--line:#d5dae2;--soft:#f3f5f8;--accent:#1f5f8b}
*{box-sizing:border-box}body{margin:0;background:#fff;color:var(--ink);font:14px/1.6 'Pretendard','Malgun Gothic','Apple SD Gothic Neo',sans-serif}
main{max-width:860px;margin:0 auto;padding:32px 24px 48px}h1{font-size:24px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px;padding-bottom:4px;border-bottom:1px solid var(--line)}
.meta{color:var(--muted);font-size:12.5px}.bar{display:flex;gap:8px;justify-content:flex-end;margin-bottom:16px}
.bar button{font:inherit;padding:6px 14px;border:1px solid var(--line);border-radius:6px;background:var(--soft);cursor:pointer}
table{width:100%;border-collapse:collapse;margin:8px 0;font-size:12.5px}th,td{border:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
th{background:var(--soft);font-weight:600}td.num{text-align:right;font-variant-numeric:tabular-nums}
.key th{width:38%}.key td{font-weight:600}.note{color:var(--muted);font-size:12.5px}ul{padding-left:20px;margin:6px 0}li{margin:3px 0}
.badge{display:inline-block;font-size:11.5px;padding:1px 8px;border-radius:10px;background:var(--soft);border:1px solid var(--line);margin-left:6px}
footer{margin-top:28px;font-size:11.5px;color:var(--muted);word-break:break-all}
@media print{.bar{display:none}main{padding:0}h2{break-after:avoid}table,li{break-inside:avoid}@page{size:A4;margin:16mm 14mm}}
"""


def area_html(s: dict[str, Any]) -> str:
    """Printable report (browser → PDF). Same snapshot as the Markdown: every sentence is an engine fact, every table an engine value."""
    from html import escape

    h = s["history"]
    facts = s["facts"]
    used: set[int] = set()

    def section_facts(prefixes: tuple[str, ...]) -> list[str]:
        out = []
        for i, f in enumerate(facts):
            if i not in used and any(f["id"] == p or (p.endswith("_") and f["id"].startswith(p)) for p in prefixes):
                used.add(i)
                out.append(f["text"])
        return out

    def at(table: dict[Any, Any], year: Any) -> dict[str, Any]:
        return table.get(str(year)) or table.get(year) or {}

    def num(v: float | None, digits: int = 0) -> str:
        return "자료 없음" if v is None else f"{v:,.{digits}f}"

    def kst(value: Any) -> str:
        from datetime import datetime, timedelta, timezone
        try:
            stamp = datetime.fromisoformat(str(value))
            if stamp.tzinfo is None:
                return str(value)[:16]
            return stamp.astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M (KST)")
        except ValueError:
            return str(value)[:19]

    parts = [f"<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
             f"<title>{escape(s['title'])}</title><style>{HTML_STYLE}</style></head><body><main>",
             "<div class=\"bar\"><button type=\"button\" onclick=\"window.print()\">인쇄 · PDF로 저장</button></div>",
             f"<h1>{escape(s['title'])}</h1><p class=\"meta\">지역 {escape(s['area']['label'])} · 기간 {h['years'][0]}~{h['years'][-1]} · 작성 {escape(kst(s['created_at']))}"
             f"<span class=\"badge\">운영 단계 1차 추정</span><span class=\"badge\">{escape(s['summary']['validation'])}</span></p>"]
    key = key_results(s)
    if key:
        parts.append("<h2>핵심 결과</h2><table class=\"key\"><tbody>" + "".join(f"<tr><th>{escape(k)}</th><td>{escape(v)}</td></tr>" for k, v in key) + "</tbody></table>")
    if s["summary"].get("mode") == "LOCAL_SLM_NARRATIVE":
        parts.append("<h2>요약 (로컬 AI 문장, 숫자 검증 통과)</h2>" + "".join(f"<p>{escape(p)}</p>" for p in s["summary"]["paragraphs"]))
    for title, prefixes in HTML_SECTIONS:
        texts = section_facts(prefixes)
        extra = ""
        if title.startswith("2."):
            rows = []
            for y in h["years"]:
                e = at(h["energy"], y)
                elec = e.get("electricity", {})
                if elec.get("kwh") is None and e.get("electricity_carbon_kgco2eq") is None:
                    continue
                rows.append(f"<tr><td>{y}</td><td class=num>{num(elec.get('kwh'))}</td><td class=num>{elec.get('complete_parcels', 0)}</td><td class=num>{num(e.get('electricity_carbon_kgco2eq'))}</td></tr>")
            if rows:
                extra += ("<table><thead><tr><th>연도</th><th>공동주택 전력 kWh (K-apt)</th><th>12개월 관측 단지</th><th>전력 탄소 kgCO2eq</th></tr></thead><tbody>"
                          + "".join(rows) + "</tbody></table>")
            be = (h.get("building_energy") or {}).get("years") or {}
            if be:
                extra += ("<table><thead><tr><th>연도</th><th>건물 전체 전력 kWh (건축HUB)</th><th>12개월 계측 지번</th><th>원단위 kWh/m²</th><th>전력 탄소 kgCO2eq</th></tr></thead><tbody>"
                          + "".join(f"<tr><td>{y}{' (일부 결측·비교 제외)' if be[y].get('provider_gap') else ''}</td><td class=num>{num(be[y].get('electricity_kwh'))}</td>"
                                    f"<td class=num>{be[y].get('electricity_complete', 0):,}</td><td class=num>{num(be[y].get('kwh_per_m2'), 1)}</td><td class=num>{num(be[y].get('electricity_carbon_kgco2eq'))}</td></tr>"
                                    for y in sorted(be, key=lambda v: int(v)))
                          + "</tbody></table>")
        if title.startswith("5.") and (s.get("effort") or {}).get("mix"):
            m = s["effort"]["mix"]
            extra += ("<table><thead><tr><th>감축 수단</th><th>입력</th><th>연간 감축 kWh</th></tr></thead><tbody>"
                      f"<tr><td>신축 건물 전력 절감</td><td class=num>{m['new_efficiency_pct']:,.1f}%</td><td class=num>{num(m['new_kwh'])}</td></tr>"
                      f"<tr><td>기존 건물 전력 절감</td><td class=num>{m['existing_efficiency_pct']:,.1f}%</td><td class=num>{num(m['existing_kwh'])}</td></tr>"
                      f"<tr><td>태양광</td><td class=num>{m['pv_kw']:,.1f} kW</td><td class=num>{num(m['pv_kwh']) if m['pv_counted'] else '발전량 근거 없음'}</td></tr>"
                      f"<tr><th>합계 (kgCO2eq)</th><td></td><td class=num>{num(m['total_kgco2eq'])}</td></tr></tbody></table>"
                      f"<p class=note>{escape(m['basis'])}</p>")
        if texts or extra:
            parts.append(f"<h2>{escape(title)}</h2>" + ("<ul>" + "".join(f"<li>{escape(t)}</li>" for t in texts) + "</ul>" if texts else "") + extra)
    rest = [f["text"] for i, f in enumerate(facts) if i not in used]
    limits = [h.get("factor_basis", ""), "관측이 없는 연도는 0이 아니라 자료 없음입니다. 행정동 통계는 격자·반경에 배분하지 않았습니다.",
              "운영 단계 1차 추정이며 법적 적합성이나 넷제로 달성을 판정하지 않습니다."] + list((s.get("effort") or {}).get("assumptions") or [])
    parts.append("<h2>7. 자료 범위와 한계</h2><ul>" + "".join(f"<li>{escape(t)}</li>" for t in rest + [x for x in limits if x]) + "</ul>")
    parts.append(f"<footer>재현 정보 · 근거 SHA256 {escape(s['evidence_hash'])} · 작성 방식 {escape(s['summary']['mode'])} — {escape(s['summary']['validation'])}"
                 f" · 구역 선정 {escape(s['area'].get('method') or '')}</footer></main></body></html>")
    return "".join(parts)


def area_markdown(s: dict[str, Any]) -> str:
    lines = [f"# {s['title']}", f"지역: {s['area']['label']} | 기간: {s['history']['years'][0]}~{s['history']['years'][-1]} | 작성: {s['created_at']}"]
    key = key_results(s)
    if key:
        lines.append("\n".join(f"- {label}: {value}" for label, value in key))
    lines += ["## 검토 요약"] + list(s["summary"]["paragraphs"])
    lines += ["## 연도별 관측"]
    table = ["| 연도 | 공동주택 전력 kWh (K-apt, 12개월 관측 단지 수) | 전력 탄소 kgCO2eq | 난방도일 | 냉방도일 | 인구 | 사용승인 세대 |", "| --- | --- | --- | --- | --- | --- | --- |"]
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
                        f"({t['same_change_pct']:+.1f}%). 한 해에만 계측된 지번: {only_in(t['to'], t['new_parcels'], t['new_kwh'])}, {only_in(t['from'], t['gone_parcels'], t['gone_kwh'])} "
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


@router.get("/{report_id}/html")
def area_report_html(report_id: str) -> Response:
    """인쇄·PDF 저장용 보고서 (브라우저 인쇄 → PDF). 숫자는 마크다운과 같은 스냅숏에서만 가져온다."""
    report = get_area_report(report_id)
    return Response(area_html(report), media_type="text/html; charset=utf-8")


@router.get("/{report_id}/markdown")
def download_area_report(report_id: str) -> Response:
    report = get_area_report(report_id)
    return Response(area_markdown(report), media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="area-report-{report_id}.md"'})
