"""Training and evaluation data for the local report writer (area summaries).

The local model never computes anything. It only rewrites the calculation engine's verified
sentences (``area.area_facts``) into a short summary. So the training target is built from
those sentences alone, and every target is checked with the same ``verify_narrative`` the app
uses before publishing — a target that fails is dropped, never "fixed".

Output (``DATA_DIR/llm/area-narrative``):
  train.jsonl / eval.jsonl  chat format {"id", "messages": [system, user, assistant]}; eval rows
                            also carry "facts" so ``evaluate`` can verify the model's answer.
  manifest.json             counts, split rule, prompt hash, data coverage at build time.
Evaluation writes eval-<model>-<time>.json next to them.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from .area import ZONE_LABEL, analyze, prepare_inputs
from .area_report import AREA_SYSTEM, facts_prompt, verify_narrative

MAX_SUMMARY = 1100
EVAL_SHARE = 0.15
TARGETS = (0, 10, 20, 30, 40, 50, 60, 80, 100)
PLANS: tuple[dict[str, float], ...] = (
    {"added_floor_area_m2": 0},
    {"added_floor_area_m2": 20000},
    {"added_floor_area_m2": 50000},
    {"added_floor_area_m2": 84000, "removed_floor_area_m2": 12000},
    {"floors": 15, "building_count": 4, "footprint_per_building": 700},
    {"floors": 25, "building_count": 8, "footprint_per_building": 900},
)

# Slots in reading order: (fact ids tried in order, connective used when the slot is not first).
# The building-wide sentences come before the development history, and the reduction basis right before the target, so
# a summary of a commercial area (effort on every metered building) says what the target is measured against.
SLOTS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("scope",), ("",)),
    (("latest_energy", "coverage"), ("", "자료 면에서 ")),
    (("latest_carbon",), ("",)),
    (("building_energy",), ("", "건물 전체로 보면 ")),
    (("building_energy_trend",), ("",)),
    (("event",), ("", "개발 이력을 보면 ")),
    (("change", "estimated_change"), ("", "개발 전후로 ")),  # a before/after difference, not a measured cause ('그 결과')
    (("new_share",), ("",)),
    (("effort_fallback",), ("",)),
    (("effort_basis",), ("",)),
    (("effort_target",), ("", "앞으로의 개발에 대해서는 ")),
    (("effort_met", "effort_all"), ("", "이때 ")),
    (("effort_offset",), ("",)),
)
# Sentences that do not follow from the one before: no connective ('그 결과 관측이 부족해 …' read as a cause).
NO_CONNECTIVE = frozenset({"estimated_change", "effort_basis", "effort_fallback", "building_energy_trend"})
EFFORT_BASES = ("apartments", "apartments", "buildings")


def _stable(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


def reference_summary(facts: list[dict[str, Any]], seed: str = "") -> str | None:
    """A 4~7 sentence summary made only of the engine's sentences (plus number-free connectives)."""
    by_id = {f["id"]: f for f in facts}
    parts: list[str] = []
    used: set[str] = set()
    for ids, connectives in SLOTS:
        fact = next((by_id[i] for i in ids if i in by_id), None)
        if not fact:
            continue
        if fact["id"].startswith("effort_") and fact["id"] != "effort_basis" and "effort_basis" in by_id and "effort_basis" not in used:
            continue  # an effort amount is only quoted together with its basis (the app checker requires it)
        connective = connectives[_stable(seed + fact["id"]) % len(connectives)] if parts and fact["id"] not in NO_CONNECTIVE else ""
        candidate = connective + fact["text"]
        if len(" ".join(parts + [candidate])) > MAX_SUMMARY:
            continue
        parts.append(candidate)
        used.add(fact["id"])
    if len(parts) < 2:
        return None
    return " ".join(parts)


def _areas(inputs: dict[str, Any], limit_circles: int = 24, limit_grids: int = 40) -> list[dict[str, Any]]:
    """Every 행정동, every 용도지역 category, circles around sampled apartment complexes, and sampled 500m grids
    with metered buildings (the area page opens a single grid from the map)."""
    specs: list[dict[str, Any]] = []
    for feature in inputs["admin"]:
        code = feature["properties"].get("adm_code")
        if code:
            specs.append({"type": "admin", "code": str(code)})
    categories = sorted({z.get("dominant_zone") for z in inputs["zoning"].values() if z.get("dominant_zone") in ZONE_LABEL})
    specs += [{"type": "zone", "category": c} for c in categories]
    points = sorted((c for c in inputs["complexes"].values() if c.get("lon") and c.get("lat")), key=lambda c: c["kapt_code"])
    step = max(1, len(points) // max(1, limit_circles))
    for i, c in enumerate(points[::step][:limit_circles]):
        specs.append({"type": "circle", "lon": round(c["lon"], 6), "lat": round(c["lat"], 6), "radius_m": (500, 1000, 1500)[i % 3]})
    metered = (inputs.get("building_energy") or {})
    latest = max(metered) if metered else None
    grids = sorted(metered.get(latest, {})) if latest else []
    step = max(1, len(grids) // max(1, limit_grids))
    specs += [{"type": "grid", "grid_id": g} for g in grids[::step][:limit_grids]]
    return specs


def build_dataset(db: Any, from_year: int, to_year: int, *, out_dir: str | Path | None = None,
                  per_area: int = 6, log: Callable[[str], None] = print, regions: list[str | None] | None = None,
                  per_area_other: int = 3, other_limits: tuple[int, int] = (8, 12)) -> dict[str, Any]:
    """Run the engine over many areas × plans × targets and write verified chat examples.

    ``regions``: study regions to take areas from (default: the original region only). The first region gets
    ``per_area`` analyses per area and the full circle/grid samples; the others ``per_area_other`` and fewer samples
    (``other_limits`` circles, grids), so other regions' wording (region names, building-wide bases, 면 without
    apartments) is learnt without the training set growing past what the 6 GB GPU trains overnight."""
    root = Path(out_dir or Path(os.getenv("DATA_DIR", "data")) / "llm" / "area-narrative")
    root.mkdir(parents=True, exist_ok=True)
    years = list(range(from_year, to_year + 1))
    seen: set[str] = set()
    rows: dict[str, list[dict[str, Any]]] = {"train": [], "eval": []}
    stats = {"areas": 0, "analyses": 0, "failed_analyses": 0, "dropped_unverified": 0, "duplicates": 0, "no_summary": 0}
    coverage: dict[str, Any] = {}
    for r_index, region in enumerate(regions or [None]):
        inputs = prepare_inputs(db, years, region)
        code = (inputs.get("region") or {}).get("code") or "default"
        specs = _areas(inputs) if r_index == 0 else _areas(inputs, *other_limits)
        repeats = per_area if r_index == 0 else per_area_other
        stats["areas"] += len(specs)
        before = (len(rows["train"]), len(rows["eval"]))
        _examples(db, specs, region, inputs, from_year, to_year, repeats, seen, rows, stats, log)
        coverage[code] = {
            "energy_years_observed": sorted({int(r["use_ym"][:4]) for r in inputs["energy"] if r.get("use_ym")}),
            "complexes": len(inputs["complexes"]), "admin_features": len(inputs["admin"]), "areas": len(specs),
            "train": len(rows["train"]) - before[0], "eval": len(rows["eval"]) - before[1],
        }
        log(f"region {code}: areas {len(specs)}, train +{coverage[code]['train']}, eval +{coverage[code]['eval']}")
        del inputs
    return _write(root, rows, stats, coverage, from_year, to_year, regions, log)


def _examples(db: Any, specs: list[dict[str, Any]], region: str | None, inputs: dict[str, Any], from_year: int, to_year: int,
              per_area: int, seen: set[str], rows: dict[str, list[dict[str, Any]]], stats: dict[str, int], log: Callable[[str], None]) -> None:
    for n, spec in enumerate(specs, 1):
        key = json.dumps(spec if region is None else {"region": region, **spec}, sort_keys=True, ensure_ascii=False)
        # Split by area so evaluation areas are never seen in training.
        split = "eval" if (_stable(key) % 1000) / 1000 < EVAL_SHARE else "train"
        for k in range(per_area):
            target = TARGETS[(_stable(key) + k * 3) % len(TARGETS)]
            plan = PLANS[(_stable(key) // 7 + k) % len(PLANS)]
            try:
                result = analyze(db, spec, from_year, to_year, None, 3 if k % 2 == 0 else 2, dict(plan), float(target), None, inputs=inputs,
                                 region=region, effort_basis=EFFORT_BASES[(_stable(key) + k) % len(EFFORT_BASES)])
            except (ValueError, KeyError) as exc:
                stats["failed_analyses"] += 1
                log(f"skip {key}: {str(exc)[:80]}")
                break
            stats["analyses"] += 1
            facts = result["facts"]
            prompt = facts_prompt(facts)
            if prompt in seen:
                stats["duplicates"] += 1
                continue
            seen.add(prompt)
            summary = reference_summary(facts, seed=f"{key}{k}")
            if not summary:
                stats["no_summary"] += 1
                continue
            if verify_narrative(summary, facts):
                stats["dropped_unverified"] += 1
                continue
            example: dict[str, Any] = {
                "id": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16],
                "messages": [
                    {"role": "system", "content": AREA_SYSTEM},
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": json.dumps({"summary": summary}, ensure_ascii=False)},
                ],
            }
            if split == "eval":
                example["facts"] = facts
            rows[split].append(example)
        if n % 10 == 0:
            log(f"{n}/{len(specs)} areas, train {len(rows['train'])}, eval {len(rows['eval'])}")


def _write(root: Path, rows: dict[str, list[dict[str, Any]]], stats: dict[str, int], coverage: dict[str, Any], from_year: int, to_year: int,
           regions: list[str | None] | None, log: Callable[[str], None]) -> dict[str, Any]:
    for split, items in rows.items():
        with (root / f"{split}.jsonl").open("w", encoding="utf-8") as handle:
            for item in items:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    if regions is None and len(coverage) == 1:  # single default region: the manifest keeps its earlier shape
        coverage = next(iter(coverage.values()))
    manifest = {
        "task": "area-narrative", "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "years": [from_year, to_year], "regions": regions or ["default"], "train": len(rows["train"]), "eval": len(rows["eval"]), "stats": stats,
        "split": f"by area key hash, eval share {EVAL_SHARE}", "system_prompt_sha256": hashlib.sha256(AREA_SYSTEM.encode("utf-8")).hexdigest(),
        "format": "chat messages; assistant content is the JSON the app requests ({\"summary\": ...})",
        "coverage": coverage,
        "note": "과거 수집(CollectHistory) 뒤 다시 만들면 관측 전후 비교 문장이 들어간 예시가 늘어납니다.",
    }
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"wrote {root} train {len(rows['train'])} eval {len(rows['eval'])}")
    return manifest


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def evaluate(path: str | Path | None = None, *, model: str | None = None, limit: int | None = None,
             generate: Callable[[list[dict[str, Any]], str | None], str] | None = None,
             log: Callable[[str], None] = print) -> dict[str, Any]:
    """Ask the local model for each held-out example and check every number with ``verify_narrative``.

    pass      = the app would publish the model's text as-is.
    rejected  = the app would replace it with the verified template (so the published report is still correct).
    error     = no answer (model not running, timeout, invalid JSON).
    """
    from .area_report import local_narrative
    from .reporting import narrative_model
    source = Path(path or Path(os.getenv("DATA_DIR", "data")) / "llm" / "area-narrative" / "eval.jsonl")
    if not source.exists():
        raise ValueError(f"평가 파일이 없습니다: {source} (먼저 llm-dataset 실행)")
    call = generate or (lambda facts, m: local_narrative(facts, m))
    name = model or narrative_model()
    results: list[dict[str, Any]] = []
    rows = list(_read_jsonl(source))
    if limit is not None and 0 < limit < len(rows):
        # spread over the whole file: a multi-region eval file lists the regions one after another
        step = len(rows) / limit
        rows = [rows[int(i * step)] for i in range(limit)]
    for i, row in enumerate(rows):
        facts = row["facts"]
        started = time.monotonic()
        try:
            text = call(facts, model)
        except Exception as exc:  # noqa: BLE001 - every failure is a counted outcome
            results.append({"id": row["id"], "outcome": "error", "reason": type(exc).__name__})
            continue
        problems = verify_narrative(text, facts)
        results.append({"id": row["id"], "outcome": "rejected" if problems else "pass", "violations": problems,
                        "seconds": round(time.monotonic() - started, 2), "text": text[:600]})
        log(f"{i + 1}: {'pass' if not problems else 'rejected ' + '; '.join(problems)[:120]}")
    counts = {k: sum(1 for r in results if r["outcome"] == k) for k in ("pass", "rejected", "error")}
    answered = counts["pass"] + counts["rejected"]
    report = {
        "model": name, "file": str(source), "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n": len(results), **counts,
        "pass_rate": round(counts["pass"] / answered, 4) if answered else None,
        "published_error_rate": 0.0,
        "published_error_note": "불합격 문장은 앱이 게시하지 않고 검증된 서식으로 바꾸므로, 게시된 보고서의 숫자 오류는 설계상 0입니다.",
        "violation_kinds": _kinds(results),
        "results": results,
    }
    out = source.parent / f"eval-{name.replace(':', '_').replace('/', '_')}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"pass {counts['pass']} / rejected {counts['rejected']} / error {counts['error']} → {out}")
    return {k: v for k, v in report.items() if k != "results"} | {"saved": str(out)}


def _kinds(results: list[dict[str, Any]]) -> dict[str, int]:
    kinds: dict[str, int] = {}
    for r in results:
        for v in r.get("violations", []):
            kind = v.split(":")[0]
            kinds[kind] = kinds.get(kind, 0) + 1
    return kinds
