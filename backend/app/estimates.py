"""추정 계층 (docs/DATA_STANDARD.md 4.1): 관측이 빠진 자리를 관측 표와 **따로** 채운다.

관측 표(energy_monthly, apartment_energy_monthly, sgis_*_admin)는 손대지 않는다. 추정값은 ``estimated_values``에만 쓰고
모든 행에 방법·근거·규칙 판(``RULE_VERSION``)을 남긴다. 화면·보고서는 관측과 나란히 '추정'으로 보이고, 관측 합계에 더하지 않는다.

방법은 전주 자료로 미리 시험(백테스트)해 고른 것이다(``BACKTEST``, 2026-10-27 PC 작업 672·674·675).

1. 건축HUB 빠진 달 (2020~): 같은 지번의 앞뒤 해 같은 달 × (두 해 공통 관측 달 합의 비) — 공통 달이 6개월 이상인 참고 해
   최대 2개의 평균. 참고 해가 없으면 그해 도시 월별 비중으로 나눈다. 채우는 달은 그 지번의 첫 관측과 마지막 관측 **사이**에서
   연속 3개월 이하로 빈 달뿐이다(신축 전·철거 후·긴 공백은 채우지 않는다). 여름 가스 두 달 묶음 청구는 빈 달이 아니다.
2. 건축HUB 2015~2019 (제공기관 미제공): 2021년에 계측된 지번 중 그해 있던 지번(건축물대장 사용승인 연도 기준)만 남기고, 전력은
   2021년 지번 사용량(12개월, 빈 달 채움 포함) × 같은 지역 K-apt '같은 단지끼리' 지수(그해 ÷ 2021년), 가스는 칸별 월 가스 =
   a + b·난방도일 회귀(2021~2023)로 낸다. 2022년 이후 처음 계측된 지번은 넣지 않는다(제공 범위가 넓어진 몫이 과거 사용량처럼
   보이지 않게).
   한전 판매량 지수로 되돌리면 도시 성장(새 건물)이 기존 건물 사용량 감소처럼 들어가 2015년 공동주택 지번이 15% 작게 나와
   (K-apt와 이어진 지번 201곳 검증) 쓰지 않고, 한전 판매량은 시 전체 비율 점검에만 쓴다.
3. K-apt 단지-해: 6개월 이상 관측 → 빠진 달을 1번 방법으로, 6개월 미만 → 가장 가까운 12개월 해 × 전주 같은 단지 지수,
   한 번도 보고하지 않은 단지 → 그해 세대당 전력 중앙값 × 세대수. 사용승인 해는 입주 중이라 추정하지 않는다.
4. SGIS 행정동 인구·가구: 최근 3개 관측 연도의 직선 추세로 다음 해(아직 공표 전)를 낸다.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from sqlalchemy import JSON, DateTime, Float, Integer, String, delete, insert, select
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

RULE_VERSION = "est-1.0"
MAX_GAP_RUN = 3            # 채우는 빈 달: 첫·마지막 관측 사이, 연속 3개월 이하
MIN_COMMON_MONTHS = 6      # 참고 해와 공통 관측 달
NEIGHBOR_OFFSETS = (-1, 1, -2, 2)
MAX_REFS = 2
HUB_FIRST_YEAR = 2020
BACKCAST_FIRST_YEAR = 2015
BACKCAST_BASE_YEARS = (2021, 2022, 2023)   # 2020은 제공기관 결측(9·10월), 2024~는 기준에서 먼 쪽
KAPT_NEIGHBOR_MAX = 3
KAPT_MIN_PEERS = 20
KAPT_MIN_MONTHS_FOR_FILL = 6
POP_TREND_YEARS = 3
BIMONTHLY_GAS_MONTHS = frozenset({6, 7, 8, 9})
MIN_KWH_PER_HOUSEHOLD_YEAR = 600.0      # grid_metrics와 같은 세대당 연 전력 범위(밖이면 추정 버림)
MAX_KWH_PER_HOUSEHOLD_YEAR = 18000.0
KEPCO_BUILDING_USES = ("주택용", "일반용", "교육용")

METHOD_LABELS = {
    "FILL_SAME_ENTITY_NEIGHBOR_YEAR": "같은 지번(단지)의 앞뒤 해 같은 달 × 공통 관측 달 비",
    "FILL_CITY_MONTH_PROFILE": "그해 도시 월별 비중",
    "BACKCAST_SAME_BUILDING": "그해 있던 지번(건축물대장 사용승인)의 2021년 사용량 × 같은 지역 K-apt 같은 단지끼리 지수(그해 ÷ 2021년)",
    "BACKCAST_HDD_REGRESSION": "칸별 월 가스 = a + b·난방도일(기준 해 회귀), 건축물대장 사용승인으로 없던 지번 제외",
    "KAPT_NEIGHBOR_YEAR_CITY_INDEX": "같은 단지 가장 가까운 12개월 해 × 같은 단지끼리의 도시 지수",
    "KAPT_PEER_MEDIAN_PER_HOUSEHOLD": "그해 12개월 관측 단지의 세대당 전력 중앙값 × 세대수",
    "SGIS_LINEAR_TREND_3Y": "최근 3개 관측 연도 직선 추세",
}

# 전주 백테스트(관측을 일부러 가리고 같은 방법으로 낸 값과 비교). 오차 = |추정−관측|/관측.
#  wape: 오차 합 ÷ 관측 합, mdape: 사례별 오차의 중앙값, city_err: 시 전체 합의 차이(부호 있음).
BACKTEST = {
    "date": "2026-10-27",
    "hub_month_fill_electricity": {"tested": 1550, "wape": 0.0989, "mdape": 0.1063, "bias_pct": 1.45},
    "hub_month_fill_gas": {"tested": 1532, "wape": 0.1357, "mdape": 0.1693, "bias_pct": -3.76},
    # 칸별(전력, 12개월 지번, 칸 588~592): 기준 한 해에서 1년 떨어진 해 6.7%(중앙 4.3%, 시 합계 +5.2%), 2년 10~16%, 3년 17~21%
    # (est_calib4). 시 합계가 크게 나오는 몫에는 나중 해에 계측이 늘어난 지번(제공 범위)이 섞여 있다. 공동주택 지번 검증(K-apt 실측
    # 2015~2020, 201곳): 같은 건물 사용량은 기준 해의 97~102%, 한전 지수로 되돌리면 2015년 −15%.
    "hub_backcast_electricity": {"grid_wape_1y": 0.067, "grid_wape_2y": (0.102, 0.161), "grid_wape_3y": (0.171, 0.210),
                                 "grid_mdape_1y": 0.043, "city_err_1y_pct": 5.2, "apartment_same_building_pct": (97.0, 101.7),
                                 "kepco_index_apartment_err_2015_pct": -15.0},
    "hub_backcast_gas": {"grid_wape": (0.10, 0.16), "grid_mdape_gt100mwh": (0.079, 0.103), "city_err_pct": (-1.0, 2.9)},
    "kapt_month_fill": {"tested": 1948, "wape": 0.0587, "mdape": 0.0346},
    "kapt_year_neighbor": {"tested": 1717, "wape": 0.0247, "mdape": 0.0125},
    "kapt_peer_median": {"tested": 2389, "wape": 0.1861, "mdape": 0.1226},
    "sgis_population_trend": {"dongs": 36, "mdape_2024": 0.0125, "mdape_2023": 0.0184, "carry_last_mdape_2024": 0.022},
}


class EstimatedValue(Base):
    """One estimated value (never an observation). ``value`` is in ``unit``; ``basis`` keeps the inputs it came from."""
    __tablename__ = "estimated_values"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # dataset|region|key|energy_type|period
    dataset: Mapped[str] = mapped_column(String, index=True)   # hub_grid_year | kapt_complex_year | sgis_population | sgis_households
    region_code: Mapped[str] = mapped_column(String, index=True)
    key: Mapped[str] = mapped_column(String, index=True)       # grid_id | complex_code | adm_code
    energy_type: Mapped[str | None] = mapped_column(String, nullable=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String)
    data_class: Mapped[str] = mapped_column(String, default="ESTIMATED")
    method: Mapped[str] = mapped_column(String)
    basis: Mapped[dict] = mapped_column(JSON, default=dict)
    rule_version: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# --------------------------------------------------------------------------- pure helpers (tested without a database)
def month_index(year: int, month: int, first_year: int) -> int:
    return (year - first_year) * 12 + (month - 1)


def fillable(observed: Iterable[int], energy_type: str, first_year: int, max_run: int = MAX_GAP_RUN) -> list[int]:
    """Month indexes to fill: between the entity's first and last observation, in a run of at most ``max_run`` empty
    months. A gas month in June~September followed by an observed month is a two-month bill, not a gap."""
    have = sorted(set(observed))
    if len(have) < 2:
        return []
    present = set(have)
    out: list[int] = []
    for a, b in zip(have, have[1:]):
        run = list(range(a + 1, b))
        if not run or len(run) > max_run:
            continue
        for t in run:
            month = t % 12 + 1
            if energy_type == "GAS" and month in BIMONTHLY_GAS_MONTHS and (t + 1) in present:
                continue
            out.append(t)
    return out


def neighbor_year_estimate(series: dict[int, float], t: int, *, min_common: int = MIN_COMMON_MONTHS,
                           offsets: Iterable[int] = NEIGHBOR_OFFSETS, max_refs: int = MAX_REFS) -> tuple[float | None, list[int]]:
    """Month ``t`` from the same entity's other years: other[m] × Σ common months this year / Σ the same months that year.

    ``series`` maps month index → observed kWh (one entity). Returns (estimate, reference year offsets)."""
    year0 = t - t % 12
    this_year = {i: series[i] for i in range(year0, year0 + 12) if i in series and i != t}
    refs: list[float] = []
    used: list[int] = []
    for k in offsets:
        if (t + 12 * k) not in series:
            continue
        common = [i for i in this_year if (i + 12 * k) in series]
        if len(common) < min_common:
            continue
        denominator = sum(series[i + 12 * k] for i in common)
        if denominator <= 0:
            continue
        refs.append(series[t + 12 * k] * sum(this_year[i] for i in common) / denominator)
        used.append(k)
        if len(refs) >= max_refs:
            break
    return (sum(refs) / len(refs), used) if refs else (None, [])


def profile_estimate(series: dict[int, float], t: int, profile: dict[int, float] | None, min_months: int = MIN_COMMON_MONTHS) -> float | None:
    """Month ``t`` from the year's observed months and the city's monthly shares of that year (``profile``: month 1..12 → share)."""
    if not profile:
        return None
    year0 = t - t % 12
    months = [i for i in range(year0, year0 + 12) if i in series and i != t]
    if len(months) < min_months:
        return None
    share = sum(profile.get(i % 12 + 1, 0.0) for i in months)
    target = profile.get(t % 12 + 1)
    if not share or target is None:
        return None
    return sum(series[i] for i in months) * target / share


def city_profiles(entities: dict[Any, dict[int, float]], energy_type: str, first_year: int, years: Iterable[int]) -> dict[int, dict[int, float]]:
    """Per year, the monthly shares of the entities observed in all 12 months (gas: also two-month summer bills)."""
    out: dict[int, dict[int, float]] = {}
    for year in years:
        totals = [0.0] * 12
        base = month_index(year, 1, first_year)
        for series in entities.values():
            months = [base + i for i in range(12)]
            have = [t for t in months if t in series]
            if len(have) < 12:
                continue
            for i, t in enumerate(months):
                totals[i] += series[t]
        grand = sum(totals)
        if grand > 0:
            out[year] = {i + 1: v / grand for i, v in enumerate(totals)}
    return out


def fill_entity(series: dict[int, float], energy_type: str, first_year: int, profiles: dict[int, dict[int, float]]) -> dict[int, tuple[float, str]]:
    """Estimated months of one entity: month index → (kWh, method)."""
    out: dict[int, tuple[float, str]] = {}
    for t in fillable(series, energy_type, first_year):
        value, _ = neighbor_year_estimate(series, t)
        method = "FILL_SAME_ENTITY_NEIGHBOR_YEAR"
        if value is None:
            value = profile_estimate(series, t, profiles.get(first_year + t // 12))
            method = "FILL_CITY_MONTH_PROFILE"
        if value is not None:
            out[t] = (max(0.0, value), method)
    return out


def linear_trend(points: dict[int, float], target: int) -> float | None:
    """Least-squares line through (year, value) evaluated at ``target`` (None with fewer than 2 points)."""
    if len(points) < 2:
        return None
    xs, ys = list(points), list(points.values())
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if not sxx:
        return my
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return my + slope * (target - mx)


def fit_line(xs: list[float], ys: list[float]) -> tuple[float, float] | None:
    """(intercept, slope) of y = a + b·x, None when x does not vary."""
    if len(xs) < 2:
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if not sxx:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return my - slope * mx, slope


def plausible_household_kwh(kwh: float | None, households: int | None) -> bool:
    if kwh is None or not households:
        return kwh is not None
    per = kwh / households
    return MIN_KWH_PER_HOUSEHOLD_YEAR <= per <= MAX_KWH_PER_HOUSEHOLD_YEAR


# --------------------------------------------------------------------------- 건축HUB (2020~ fill, 2015~2019 back-cast)
def _hub_series(db: Any, grid_of: dict[str, str], energy_type: str, first_year: int, last_year: int) -> dict[str, dict[int, float]]:
    from .energy_parcels import HUB, parcel_pnu
    from .models import EnergyMonthly
    sigungu = sorted({pnu[:5] for pnu in grid_of})
    out: dict[str, dict[int, float]] = defaultdict(dict)
    if not sigungu:
        return out
    query = (select(EnergyMonthly.sigungu_code, EnergyMonthly.bjdong_code, EnergyMonthly.lot_type, EnergyMonthly.bun, EnergyMonthly.ji,
                    EnergyMonthly.use_ym, EnergyMonthly.usage_kwh)
             .where(EnergyMonthly.source == HUB, EnergyMonthly.energy_type == energy_type, EnergyMonthly.sigungu_code.in_(sigungu),
                    EnergyMonthly.use_ym.between(f"{first_year}01", f"{last_year}12"), EnergyMonthly.usage_kwh.is_not(None)))
    for sg, bd, lot, bun, ji, ym, kwh in db.execute(query).yield_per(20000):
        pnu = parcel_pnu(sg, bd, lot, bun, ji)
        if pnu not in grid_of:
            continue
        t = month_index(int(ym[:4]), int(ym[4:6]), first_year)
        series = out[pnu]
        series[t] = series.get(t, 0.0) + float(kwh)
    return out


def _register_first_year(db: Any, sigungu: Iterable[str]) -> tuple[dict[str, int], set[str]]:
    """PNU → earliest 사용승인 연도 of its register buildings, and PNUs with a building of unknown year (assumed old)."""
    from sqlalchemy import func
    from .official import BuildingRegister
    first: dict[str, int] = {}
    unknown: set[str] = set()
    codes = sorted(set(sigungu))
    if not codes:
        return first, unknown
    try:
        rows = db.execute(select(BuildingRegister.parcel_code, BuildingRegister.approval_year)
                          .where(func.substr(BuildingRegister.parcel_code, 1, 5).in_(codes)))
        for pnu, year in rows:
            if not pnu:
                continue
            if year is None:
                unknown.add(pnu)
            elif pnu not in first or year < first[pnu]:
                first[pnu] = int(year)
    except Exception:  # noqa: BLE001 - register not collected
        db.rollback()
    return first, unknown


def _kepco_monthly(db: Any, sc: Any) -> dict[tuple[int, int], float]:
    """(year, month) → 한전 주택·일반·교육용 판매량 kWh of the region's 시·군 (empty when the region is not in the file)."""
    from .regional_stats import KepcoSigunguMonthly, kepco_key
    out: dict[tuple[int, int], float] = {}
    sido = str(sc.code)[:2]
    names = {sc.short, sc.name.split()[-1] if sc.name else sc.short}
    try:
        rows = db.execute(select(KepcoSigunguMonthly.year, KepcoSigunguMonthly.sido, KepcoSigunguMonthly.sgg, KepcoSigunguMonthly.category,
                                 KepcoSigunguMonthly.months).where(KepcoSigunguMonthly.kind == "contract",
                                                                  KepcoSigunguMonthly.category.in_(KEPCO_BUILDING_USES)))
        parts: dict[tuple[int, int], dict[str, float]] = defaultdict(dict)
        for year, sido_name, sgg, category, months in rows:
            key = kepco_key(sido_name, sgg)
            if not key or key[0] != sido or key[1] not in names:
                continue
            for i, v in enumerate((months or [])[:12]):
                if v is not None:
                    parts[(int(year), i + 1)][category] = parts[(int(year), i + 1)].get(category, 0.0) + float(v)
        for ym, by in parts.items():
            if all(c in by for c in KEPCO_BUILDING_USES):
                out[ym] = sum(by.values())
    except Exception:  # noqa: BLE001 - table missing
        db.rollback()
    return out


def _hdd_monthly(db: Any, sc: Any, first_year: int, last_year: int) -> dict[tuple[int, int], float]:
    from .regions import weather_rows
    out = {}
    for w in weather_rows(db, sc.code, f"{first_year}01", f"{last_year}12"):
        if w.hdd is not None:
            out[(int(w.use_ym[:4]), int(w.use_ym[4:6]))] = float(w.hdd)
    return out


def hub_fill(series: dict[str, dict[int, float]], energy_type: str, first_year: int, years: list[int]) -> tuple[dict[str, dict[int, tuple[float, str]]], dict[int, dict[int, float]]]:
    profiles = city_profiles(series, energy_type, first_year, years)
    return {pnu: fill_entity(s, energy_type, first_year, profiles) for pnu, s in series.items()}, profiles


def hub_grid_years(series: dict[str, dict[int, float]], fills: dict[str, dict[int, tuple[float, str]]], grid_of: dict[str, str],
                   energy_type: str, first_year: int, years: list[int]) -> dict[tuple[str, int], dict[str, Any]]:
    """(grid, year) → observed months of every parcel + filled months (the 보정 합계) with counts."""
    from .grid_metrics import annual_complete
    out: dict[tuple[str, int], dict[str, Any]] = {}
    for pnu, s in series.items():
        grid = grid_of.get(pnu)
        if not grid:
            continue
        f = fills.get(pnu, {})
        for year in years:
            base = month_index(year, 1, first_year)
            obs = {t - base + 1: s[t] for t in range(base, base + 12) if t in s}
            est = {t - base + 1: f[t][0] for t in range(base, base + 12) if t in f}
            if not obs and not est:
                continue
            item = out.setdefault((grid, year), {"observed_all_kwh": 0.0, "filled_kwh": 0.0, "complete_parcels": 0, "partial_parcels": 0,
                                                 "filled_parcels": 0, "filled_months": 0, "unfilled_parcels": 0, "profile_months": 0})
            item["observed_all_kwh"] += sum(obs.values())
            if annual_complete(energy_type, list(obs)):
                item["complete_parcels"] += 1
                continue
            item["partial_parcels"] += 1
            if est:
                item["filled_parcels"] += 1
                item["filled_months"] += len(est)
                item["filled_kwh"] += sum(est.values())
                item["profile_months"] += sum(1 for t in range(base, base + 12) if t in f and f[t][1] == "FILL_CITY_MONTH_PROFILE")
                if not annual_complete(energy_type, list(obs) + list(est)):
                    item["unfilled_parcels"] += 1
            else:
                item["unfilled_parcels"] += 1
    return out


def hub_backcast(series: dict[str, dict[int, float]], fills: dict[str, dict[int, tuple[float, str]]], grid_of: dict[str, str], energy_type: str,
                 first_year: int, target_years: list[int], *, first_built: dict[str, int], unknown_year: set[str],
                 kepco: dict[tuple[int, int], float], hdd: dict[tuple[int, int], float],
                 same_index: dict[int, tuple[float, int]] | None = None,
                 base_years: tuple[int, ...] = BACKCAST_BASE_YEARS) -> dict[tuple[str, int], dict[str, Any]]:
    """(grid, year) → back-cast annual kWh for years before 건축HUB (see module doc, method 2)."""
    # parcel × month base = mean over the base years of observed-or-filled values, for the parcels metered in the first base
    # year: the back-cast then continues the observed series of the same parcels (a parcel first metered in 2022~2023 widens
    # the provider's coverage, not the use of 2015~2019 — 2026-10-27, 건축HUB/한전 비율 2021 0.71 → 2025 0.80)
    anchor = range(month_index(base_years[0], 1, first_year), month_index(base_years[0], 12, first_year) + 1)
    base: dict[str, dict[int, float]] = {}
    for pnu, s in series.items():
        if pnu not in grid_of or not any(t in s for t in anchor):
            continue
        f = fills.get(pnu, {})
        months: dict[int, list[float]] = defaultdict(list)
        for year in base_years:
            for m in range(1, 13):
                t = month_index(year, m, first_year)
                if t in s:
                    months[m].append(s[t])
                elif t in f:
                    months[m].append(f[t][0])
        if months:
            base[pnu] = {m: sum(v) / len(v) for m, v in months.items()}
    if not base:
        return {}

    def exists(pnu: str, year: int) -> bool:
        if pnu in unknown_year or pnu not in first_built:
            return True
        return first_built[pnu] <= year

    annual_base = {p: sum(v.values()) for p, v in base.items()}
    total_base = sum(annual_base.values())
    out: dict[tuple[str, int], dict[str, Any]] = {}
    if energy_type == "ELECTRICITY":
        # Same buildings, same use: the 2015~2020 K-apt series of the apartment parcels metered by 건축HUB stays within ±3% of
        # 2021~2023 (est_calib3: 201 parcels), while the 한전 판매량 index falls to 0.85 in 2015 because the city added
        # buildings. So each parcel that existed keeps its anchor-year use × the region's same-complex K-apt index (weather,
        # habits); parcels not yet built (건축물대장 사용승인) are left out. The anchor is one year, the first base year (2021):
        # the error grows with the distance from the anchor and a three-year mean reaches further (est_calib4: anchor 1 year
        # away 6.7% of the grid totals, 2 years 10~16%, 3 years 17~21%; 2022~2024 mean → 2021 10.8%). Only parcels with all 12
        # months of the anchor year (observed or filled) count. Without a K-apt index the anchor is kept as is (1.0).
        anchor_year = base_years[0]
        anchor_annual: dict[str, float] = {}
        for p in base:
            s, f = series[p], fills.get(p, {})
            months = [s.get(month_index(anchor_year, m, first_year), f[month_index(anchor_year, m, first_year)][0]
                            if month_index(anchor_year, m, first_year) in f else None) for m in range(1, 13)]
            if all(v is not None for v in months):
                anchor_annual[p] = sum(months)
        total_anchor = sum(anchor_annual.values())
        for year in target_years:
            idx, peers = (same_index or {}).get(year, (1.0, 0))
            per_grid: dict[str, float] = defaultdict(float)
            parcels: dict[str, int] = defaultdict(int)
            alive_kwh = 0.0
            for p, kwh in anchor_annual.items():
                if exists(p, year):
                    per_grid[grid_of[p]] += kwh * idx
                    parcels[grid_of[p]] += 1
                    alive_kwh += kwh
            share = alive_kwh / total_anchor if total_anchor else None
            kepco_year = sum(kepco[(year, m)] for m in range(1, 13)) if all((year, m) in kepco for m in range(1, 13)) else None
            for grid, kwh in per_grid.items():
                out[(grid, year)] = {"value": kwh, "parcels": parcels[grid], "same_index": round(idx, 4), "index_peers": peers,
                                     "exist_share": round(share, 4) if share else None, "anchor_year": anchor_year,
                                     "kepco_kwh": round(kepco_year, 1) if kepco_year else None}
        return out
    # GAS: grid monthly regression on heating degree days over the base years
    grid_month: dict[str, dict[tuple[int, int], float]] = defaultdict(lambda: defaultdict(float))
    for pnu in base:
        s, f = series[pnu], fills.get(pnu, {})
        for year in base_years:
            for m in range(1, 13):
                t = month_index(year, m, first_year)
                v = s.get(t, f[t][0] if t in f else None)
                if v is not None:
                    grid_month[grid_of[pnu]][(year, m)] += v
    grid_base_annual: dict[str, float] = defaultdict(float)
    for p, v in annual_base.items():
        grid_base_annual[grid_of[p]] += v
    for year in target_years:
        h = [hdd.get((year, m)) for m in range(1, 13)]
        if any(v is None for v in h):
            continue
        alive_annual: dict[str, float] = defaultdict(float)
        parcels: dict[str, int] = defaultdict(int)
        for p in base:
            if exists(p, year):
                alive_annual[grid_of[p]] += annual_base[p]
                parcels[grid_of[p]] += 1
        for grid, months in grid_month.items():
            if not grid_base_annual[grid] or not alive_annual.get(grid):
                continue
            pts = [(hdd[k], v) for k, v in months.items() if k in hdd]
            fit = fit_line([x for x, _ in pts], [y for _, y in pts]) if len(pts) >= 12 else None
            if fit:
                predicted = sum(max(0.0, fit[0] + fit[1] * x) for x in h)
            else:
                by_m: dict[int, list[float]] = defaultdict(list)
                for (y, m), v in months.items():
                    by_m[m].append(v)
                predicted = sum(sum(v) / len(v) for v in by_m.values())
            share = alive_annual[grid] / grid_base_annual[grid]
            out[(grid, year)] = {"value": predicted * share, "parcels": parcels[grid], "exist_share": round(share, 4),
                                 "regression": bool(fit), "base_years": list(base_years)}
    return out


# --------------------------------------------------------------------------- K-apt
def kapt_estimates(monthly: dict[str, dict[int, float]], info: dict[str, dict[str, Any]], first_year: int, years: list[int]) -> dict[tuple[str, int], dict[str, Any]]:
    """(complex, year) → estimated annual kWh for complex-years without 12 observed months (module doc, method 3)."""
    profiles = city_profiles(monthly, "ELECTRICITY", first_year, years)
    annual: dict[str, dict[int, float]] = defaultdict(dict)
    for code, s in monthly.items():
        for year in years:
            base = month_index(year, 1, first_year)
            if all((base + i) in s for i in range(12)):
                annual[code][year] = sum(s[base + i] for i in range(12))
    # per year: kWh per household of the complete complexes (peer median)
    per_household: dict[int, list[float]] = defaultdict(list)
    for code, by in annual.items():
        hh = (info.get(code) or {}).get("households")
        for year, kwh in by.items():
            if hh and plausible_household_kwh(kwh, hh):
                per_household[year].append(kwh / hh)
    out: dict[tuple[str, int], dict[str, Any]] = {}
    for code, meta in info.items():
        approved = meta.get("approval_year")
        s = monthly.get(code, {})
        observed_years = sorted({first_year + t // 12 for t in s})
        for year in years:
            if year in annual.get(code, {}):
                continue
            if approved is not None and approved >= year:
                continue  # not built, or the year of 사용승인 (moving in)
            if approved is None and (not observed_years or not observed_years[0] <= year <= observed_years[-1]):
                continue
            base = month_index(year, 1, first_year)
            obs = {base + i: s[base + i] for i in range(12) if (base + i) in s}
            result = None
            if len(obs) >= KAPT_MIN_MONTHS_FOR_FILL:
                filled = 0.0
                methods: dict[str, int] = defaultdict(int)
                ok = True
                for t in range(base, base + 12):
                    if t in obs:
                        continue
                    value, _ = neighbor_year_estimate(s, t)
                    method = "FILL_SAME_ENTITY_NEIGHBOR_YEAR"
                    if value is None:
                        value = profile_estimate(s, t, profiles.get(year))
                        method = "FILL_CITY_MONTH_PROFILE"
                    if value is None:
                        ok = False
                        break
                    filled += max(0.0, value)
                    methods[method] += 1
                if ok:
                    main = max(methods, key=methods.get) if methods else "FILL_SAME_ENTITY_NEIGHBOR_YEAR"
                    result = {"value": sum(obs.values()) + filled, "method": main, "observed_months": len(obs),
                              "observed_kwh": round(sum(obs.values()), 1), "filled_kwh": round(filled, 1), "methods": dict(methods)}
            if result is None and annual.get(code):
                refs = sorted(annual[code], key=lambda r: (abs(r - year), r))
                for ref in refs:
                    if abs(ref - year) > KAPT_NEIGHBOR_MAX:
                        break
                    both = [c for c, by in annual.items() if c != code and year in by and ref in by]
                    if len(both) < KAPT_MIN_PEERS:
                        continue
                    idx = sum(annual[c][year] for c in both) / sum(annual[c][ref] for c in both)
                    result = {"value": annual[code][ref] * idx, "method": "KAPT_NEIGHBOR_YEAR_CITY_INDEX", "observed_months": len(obs),
                              "observed_kwh": round(sum(obs.values()), 1) if obs else None, "ref_year": ref, "city_index": round(idx, 4), "peers": len(both)}
                    break
            if result is None and not s and meta.get("households") and len(per_household.get(year, [])) >= KAPT_MIN_PEERS:
                med = statistics.median(per_household[year])
                result = {"value": med * int(meta["households"]), "method": "KAPT_PEER_MEDIAN_PER_HOUSEHOLD", "observed_months": 0,
                          "kwh_per_household": round(med, 1), "peers": len(per_household[year]), "households": int(meta["households"])}
            if result and plausible_household_kwh(result["value"], meta.get("households")):
                out[(code, year)] = result
    return out


def same_complex_index(monthly: dict[str, dict[int, float]], first_year: int, years: list[int],
                       base_years: tuple[int, ...] = BACKCAST_BASE_YEARS, min_peers: int = KAPT_MIN_PEERS) -> dict[int, tuple[float, int]]:
    """year → (Σ that year ÷ Σ base-year mean, complexes) over the complexes with 12 observed months in that year and every base year."""
    annual: dict[str, dict[int, float]] = defaultdict(dict)
    for code, s in monthly.items():
        for year in set(years) | set(base_years):
            base = month_index(year, 1, first_year)
            if base >= 0 and all((base + i) in s for i in range(12)):
                annual[code][year] = sum(s[base + i] for i in range(12))
    out: dict[int, tuple[float, int]] = {}
    for year in years:
        peers = [c for c, by in annual.items() if year in by and all(b in by for b in base_years)]
        if len(peers) < min_peers:
            continue
        denominator = sum(sum(annual[c][b] for b in base_years) / len(base_years) for c in peers)
        if denominator > 0:
            out[year] = (sum(annual[c][year] for c in peers) / denominator, len(peers))
    return out


# --------------------------------------------------------------------------- SGIS 행정동
def sgis_trend(values: dict[str, dict[int, float]], targets: list[int], window: int = POP_TREND_YEARS) -> dict[tuple[str, int], dict[str, Any]]:
    """(adm_code, year) → straight-line value from the latest ``window`` observed years, for years after the last observation."""
    out = {}
    for code, by in values.items():
        observed = sorted(y for y, v in by.items() if v is not None)
        if len(observed) < window:
            continue
        last = observed[-window:]
        if last[-1] - last[0] != window - 1:
            continue  # not consecutive years
        for year in targets:
            if year <= observed[-1] or year - observed[-1] > 2:
                continue
            value = linear_trend({y: by[y] for y in last}, year)
            if value is not None:
                out[(code, year)] = {"value": max(0.0, round(value)), "years": last, "last_observed": round(by[last[-1]])}
    return out


# --------------------------------------------------------------------------- orchestration (CLI: estimate-gaps)
def _row(dataset: str, region: str, key: str, energy_type: str | None, year: int, value: float | None, unit: str, method: str,
         basis: dict[str, Any], data_class: str = "ESTIMATED") -> dict[str, Any]:
    return {"id": f"{dataset}|{region}|{key}|{energy_type or '-'}|{year}", "dataset": dataset, "region_code": region, "key": key,
            "energy_type": energy_type, "year": year, "value": None if value is None else round(float(value), 1), "unit": unit,
            "data_class": data_class, "method": method, "basis": basis, "rule_version": RULE_VERSION, "created_at": datetime.now(timezone.utc)}


def estimate_region(db: Any, region: str | None = None, last_year: int | None = None, log: Callable[[str], None] = print) -> dict[str, Any]:
    """Recompute every estimate of one study region and replace its rows in ``estimated_values``."""
    from .energy_parcels import _parcel_grid
    from .kapt import ApartmentComplex
    from .regions import scope
    from .settings import DEFAULT_YEAR
    sc = scope(db, region)
    last_year = int(last_year or DEFAULT_YEAR)
    rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"region": sc.code, "rule_version": RULE_VERSION, "last_year": last_year}

    # K-apt (first: its same-complex index carries the 건축HUB back-cast)
    same_index: dict[int, tuple[float, int]] = {}
    try:
        from .area import approval_year
        from .kapt_energy import ApartmentEnergyMonthly
        info: dict[str, dict[str, Any]] = {}
        for c in db.scalars(select(ApartmentComplex)):
            if sc.owns_complex(c.bjd_code, c.grid_id):
                info[c.kapt_code] = {"households": c.households, "approval_year": approval_year(c.approval_date)}
        monthly: dict[str, dict[int, float]] = defaultdict(dict)
        first = BACKCAST_FIRST_YEAR
        q = select(ApartmentEnergyMonthly.complex_code, ApartmentEnergyMonthly.year_month, ApartmentEnergyMonthly.electricity_quantity).where(
            ApartmentEnergyMonthly.quality_status == "SUCCESS", ApartmentEnergyMonthly.electricity_quantity.is_not(None),
            ApartmentEnergyMonthly.year_month.between(f"{first}01", f"{last_year}12"))
        for code, ym, kwh in db.execute(q):
            if code in info:
                ym = str(ym).replace("-", "")
                monthly[code].setdefault(month_index(int(ym[:4]), int(ym[4:6]), first), float(kwh))
        kapt_years = list(range(first, last_year + 1))
        same_index = same_complex_index(monthly, first, kapt_years, base_years=BACKCAST_BASE_YEARS[:1])  # relative to the anchor year (2021)
        kest = kapt_estimates(monthly, info, first, kapt_years)
        for (code, year), v in kest.items():
            rows.append(_row("kapt_complex_year", sc.code, code, "ELECTRICITY", year, v.pop("value"), "kWh", v.pop("method"), v))
        summary["kapt"] = {"complexes": len(info), "estimated_complex_years": len(kest),
                           "same_complex_index": {y: v[0] for y, v in sorted(same_index.items())}}
        log(f"K-apt: 단지 {len(info):,}, 추정 단지-해 {len(kest):,}")
    except Exception as exc:  # noqa: BLE001 - K-apt tables optional
        db.rollback()
        summary["kapt"] = {"error": type(exc).__name__}

    # 건축HUB
    grid_of = _parcel_grid(db, sc.grid_ids)
    hub_years = list(range(HUB_FIRST_YEAR, last_year + 1))
    first_built, unknown_year = _register_first_year(db, {p[:5] for p in grid_of})
    kepco = _kepco_monthly(db, sc)
    hdd = _hdd_monthly(db, sc, BACKCAST_FIRST_YEAR, last_year)
    summary["kepco_months"] = len(kepco)
    for energy_type in ("ELECTRICITY", "GAS"):
        series = _hub_series(db, grid_of, energy_type, HUB_FIRST_YEAR, last_year)
        if not series:
            continue
        fills, _ = hub_fill(series, energy_type, HUB_FIRST_YEAR, hub_years)
        grid_years = hub_grid_years(series, fills, grid_of, energy_type, HUB_FIRST_YEAR, hub_years)
        for (grid, year), v in grid_years.items():
            total = v["observed_all_kwh"] + v["filled_kwh"]
            method = "FILL_SAME_ENTITY_NEIGHBOR_YEAR" if v["filled_months"] > v["profile_months"] else ("FILL_CITY_MONTH_PROFILE" if v["filled_months"] else "OBSERVED_ALL_MONTHS")
            rows.append(_row("hub_grid_year", sc.code, grid, energy_type, year, total, "kWh", method,
                             {k: (round(x, 1) if isinstance(x, float) else x) for k, x in v.items()}))
        before = list(range(BACKCAST_FIRST_YEAR, HUB_FIRST_YEAR))
        back = hub_backcast(series, fills, grid_of, energy_type, HUB_FIRST_YEAR, before, first_built=first_built, unknown_year=unknown_year,
                            kepco=kepco, hdd=hdd, same_index=same_index)
        method = "BACKCAST_SAME_BUILDING" if energy_type == "ELECTRICITY" else "BACKCAST_HDD_REGRESSION"
        for (grid, year), v in back.items():
            rows.append(_row("hub_grid_year", sc.code, grid, energy_type, year, v.pop("value"), "kWh", method, v))
        city = {y: round(sum(r["value"] for r in rows if r["dataset"] == "hub_grid_year" and r["energy_type"] == energy_type and r["year"] == y) / 1e6, 1)
                for y in range(BACKCAST_FIRST_YEAR, last_year + 1)}
        summary[f"hub_{energy_type.lower()}"] = {
            "parcels": len(series), "filled_parcels": sum(1 for f in fills.values() if f), "filled_months": sum(len(f) for f in fills.values()),
            "grid_years": len(grid_years), "backcast_grid_years": len(back), "backcast_years": sorted({y for _, y in back}), "region_gwh": city}
        if energy_type == "ELECTRICITY" and kepco:
            summary["hub_electricity"]["share_of_kepco_buildings"] = {
                y: round(city[y] * 1e6 / sum(kepco[(y, m)] for m in range(1, 13)), 4)
                for y in city if city[y] and all((y, m) in kepco for m in range(1, 13))}
        log(f"건축HUB {energy_type}: 지번 {len(series):,}, 채운 달 {summary[f'hub_{energy_type.lower()}']['filled_months']:,}, 되돌림 칸-해 {len(back):,}")
        del series, fills

    # SGIS 행정동 인구·가구
    try:
        from .sgis import SgisHouseholdAdmin, SgisPopulationAdmin
        targets = list(range(last_year - 1, last_year + 1))
        for model, attr, dataset, unit in ((SgisPopulationAdmin, "population_count", "sgis_population", "persons"),
                                           (SgisHouseholdAdmin, "household_count", "sgis_households", "households")):
            values: dict[str, dict[int, float]] = defaultdict(dict)
            for r in db.scalars(select(model).where(model.value_status == "OBSERVED")):
                v = getattr(r, attr)
                if v is not None and (sc.owns_sgis(r.adm_code) if sc.sgis_codes else True):
                    values[r.adm_code][int(r.reference_year)] = float(v)
            est = sgis_trend(values, targets)
            for (code, year), v in est.items():
                rows.append(_row(dataset, sc.code, code, None, year, v.pop("value"), unit, "SGIS_LINEAR_TREND_3Y", v))
            summary[dataset] = len(est)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        summary["sgis"] = {"error": type(exc).__name__}

    db.execute(delete(EstimatedValue).where(EstimatedValue.region_code == sc.code))
    for i in range(0, len(rows), 5000):
        db.execute(insert(EstimatedValue), rows[i:i + 5000])
    db.commit()
    summary["rows"] = len(rows)
    return summary


# --------------------------------------------------------------------------- readers (area analysis)
def area_inputs(db: Any, region_code: str, years: list[int]) -> dict[str, Any]:
    """Estimated rows of one region for ``years``: {'hub': {year: {grid: {etype: {...}}}}, 'kapt': {year: {code: {...}}}, 'sgis': {...}}."""
    out: dict[str, Any] = {"hub": {}, "kapt": {}, "population": {}, "households": {}, "rule_version": None, "created_at": None}
    try:
        rows = db.execute(select(EstimatedValue.dataset, EstimatedValue.key, EstimatedValue.energy_type, EstimatedValue.year, EstimatedValue.value,
                                 EstimatedValue.method, EstimatedValue.basis, EstimatedValue.rule_version, EstimatedValue.created_at)
                          .where(EstimatedValue.region_code == region_code, EstimatedValue.year.between(years[0], years[-1]))).all()
    except Exception:  # noqa: BLE001 - table not created yet
        db.rollback()
        return out
    for dataset, key, etype, year, value, method, basis, version, created in rows:
        out["rule_version"] = version
        if created and (out["created_at"] is None or created > out["created_at"]):
            out["created_at"] = created
        item = {"value": value, "method": method, "basis": basis or {}}
        if dataset == "hub_grid_year":
            out["hub"].setdefault(year, {}).setdefault(key, {})[etype] = item
        elif dataset == "kapt_complex_year":
            out["kapt"].setdefault(year, {})[key] = item
        elif dataset == "sgis_population":
            out["population"].setdefault(year, {})[key] = item
        elif dataset == "sgis_households":
            out["households"].setdefault(year, {})[key] = item
    if out["created_at"] is not None:
        out["created_at"] = out["created_at"].isoformat()
    return out


def area_block(history: dict[str, Any], est: dict[str, Any] | None) -> dict[str, Any]:
    """The area's estimated series next to the observed ones (never added into the observed values)."""
    if not est or not (est.get("hub") or est.get("kapt") or est.get("population")):
        return {"available": False}
    area = history["area"]
    years = history["years"]
    grids = set(area["grid_ids"])
    codes = set(area["complex_codes"])
    complexes = {c["kapt_code"]: c for c in history.get("complexes") or []}
    observed_be = (history.get("building_energy") or {}).get("years") or {}
    buildings: dict[int, dict[str, Any]] = {}
    for year in years:
        by_grid = (est.get("hub") or {}).get(year) or {}
        inside = [v for g, v in by_grid.items() if g in grids]
        if not inside:
            continue
        entry: dict[str, Any] = {"year": year, "backcast": year < HUB_FIRST_YEAR}
        for etype, key in (("ELECTRICITY", "electricity"), ("GAS", "gas")):
            items = [v[etype] for v in inside if etype in v and v[etype]["value"] is not None]
            if not items:
                entry[f"{key}_kwh"] = None
                continue
            entry[f"{key}_kwh"] = round(sum(i["value"] for i in items), 1)
            entry[f"{key}_grids"] = len(items)
            if year >= HUB_FIRST_YEAR:
                entry[f"{key}_filled_kwh"] = round(sum(i["basis"].get("filled_kwh", 0.0) for i in items), 1)
                entry[f"{key}_filled_parcels"] = sum(int(i["basis"].get("filled_parcels", 0)) for i in items)
                entry[f"{key}_filled_months"] = sum(int(i["basis"].get("filled_months", 0)) for i in items)
                entry[f"{key}_unfilled_parcels"] = sum(int(i["basis"].get("unfilled_parcels", 0)) for i in items)
            else:
                entry[f"{key}_method"] = items[0]["method"]
                entry[f"{key}_parcels"] = sum(int(i["basis"].get("parcels", 0)) for i in items)
                if etype == "ELECTRICITY":
                    entry["same_index"] = items[0]["basis"].get("same_index")
                    entry["exist_share"] = items[0]["basis"].get("exist_share")
        obs = observed_be.get(year) or observed_be.get(str(year)) or {}
        entry["electricity_observed_kwh"] = obs.get("electricity_kwh")
        entry["provider_gap"] = bool(obs.get("provider_gap"))
        buildings[year] = entry
    apartments: dict[int, dict[str, Any]] = {}
    energy = history.get("energy") or {}
    for year in years:
        observed = ((energy.get(year) or {}).get("electricity") or {}).get("by_complex") or {}
        observed = {c: v for c, v in observed.items() if c in codes}
        estimated = {c: v for c, v in ((est.get("kapt") or {}).get(year) or {}).items() if c in codes and c not in observed and v["value"] is not None}
        if not estimated:
            continue
        methods: dict[str, int] = defaultdict(int)
        for v in estimated.values():
            methods[v["method"]] += 1
        obs_kwh = sum(observed.values())
        est_kwh = sum(v["value"] for v in estimated.values())
        apartments[year] = {"year": year, "observed_kwh": round(obs_kwh, 1) if observed else None, "observed_complexes": len(observed),
                            "estimated_kwh": round(est_kwh, 1), "estimated_complexes": len(estimated),
                            "total_kwh": round(obs_kwh + est_kwh, 1), "methods": dict(methods),
                            "peer_median_complexes": methods.get("KAPT_PEER_MEDIAN_PER_HOUSEHOLD", 0),
                            "built": sum(1 for c in codes if (complexes.get(c) or {}).get("approval_year") and complexes[c]["approval_year"] < year)}
    population: dict[int, dict[str, Any]] = {}
    admin = set(area.get("admin_codes") or [])
    observed_pop = history.get("population") or {}
    for year in years:
        if (observed_pop.get(year) or {}).get("population") is not None:
            continue
        pop = {c: v for c, v in ((est.get("population") or {}).get(year) or {}).items() if c in admin}
        hh = {c: v for c, v in ((est.get("households") or {}).get(year) or {}).items() if c in admin}
        if admin and len(pop) == len(admin):
            population[year] = {"year": year, "population": round(sum(v["value"] for v in pop.values())),
                                "households": round(sum(v["value"] for v in hh.values())) if len(hh) == len(admin) else None,
                                "adm_codes": len(admin), "trend_years": next(iter(pop.values()))["basis"].get("years")}
    return {"available": bool(buildings or apartments or population), "rule_version": est.get("rule_version"), "created_at": est.get("created_at"),
            "buildings": buildings, "apartments": apartments, "population": population,
            "methods": METHOD_LABELS, "backtest": BACKTEST, "data_class": "ESTIMATED"}


def estimate_facts(history: dict[str, Any], add: Callable[..., None]) -> None:
    """Sentences for the estimated series (each says 추정 and how it was made)."""
    e = history.get("estimates") or {}
    if not e.get("available"):
        return
    b = e.get("buildings") or {}
    back = sorted(y for y, v in b.items() if v.get("backcast") and v.get("electricity_kwh") is not None)
    if back:
        first, last = back[0], back[-1]
        bt = BACKTEST["hub_backcast_electricity"]
        add("estimate_buildings_backcast",
            f"건축HUB가 제공하지 않는 {first}~{last}년 건물 전체 전력은 2021년에 계측된 지번 중 그해 있던 건물(건축물대장 사용승인 기준)의 "
            f"2021년 사용량에 같은 지역 공동주택(K-apt) 같은 단지끼리의 사용량 지수를 곱해 추정했습니다: {first}년 {b[first]['electricity_kwh']:,.0f} kWh, "
            f"{last}년 {b[last]['electricity_kwh']:,.0f} kWh(추정값). 관측 해에 같은 방식으로 시험한 칸별 오차 합은 1년 떨어진 해 {bt['grid_wape_1y'] * 100:,.0f}%, "
            f"3년 떨어진 해 {bt['grid_wape_3y'][1] * 100:,.0f}%였고 더 먼 해는 더 클 수 있습니다.",
            first, b[first]["electricity_kwh"], last, b[last]["electricity_kwh"], 2021, round(bt["grid_wape_1y"] * 100), round(bt["grid_wape_3y"][1] * 100), 1, 3)
    filled = sorted(y for y, v in b.items() if not v.get("backcast") and v.get("electricity_kwh") is not None)
    if filled:
        y = filled[-1]
        v = b[y]
        add("estimate_buildings_fill",
            f"{y}년 건물 전체 전력의 보정 합계(계측된 모든 달 + 첫·마지막 계측 사이에서 3개월 이하로 빈 달 {v.get('electricity_filled_months', 0):,}개월을 같은 지번 앞뒤 해로 채움)는 "
            f"{v['electricity_kwh']:,.0f} kWh이고 그중 추정분은 {v.get('electricity_filled_kwh', 0):,.0f} kWh입니다(추정값).",
            y, v.get("electricity_filled_months", 0), v["electricity_kwh"], v.get("electricity_filled_kwh", 0), 3)
        gap = b.get(2020)
        if gap and gap.get("provider_gap") and gap.get("electricity_filled_kwh"):
            add("estimate_buildings_2020",
                f"2020년은 제공기관 결측 달을 채운 보정 합계가 {gap['electricity_kwh']:,.0f} kWh(추정분 {gap['electricity_filled_kwh']:,.0f} kWh)입니다(추정값).",
                2020, gap["electricity_kwh"], gap["electricity_filled_kwh"])
    a = e.get("apartments") or {}
    if a:
        y = max(a)
        v = a[y]
        peer = (f" 그중 한 번도 보고하지 않은 단지 {v['peer_median_complexes']}곳은 그해 세대당 전력 중앙값으로 추정했습니다."
                if v.get("peer_median_complexes") else "")
        obs_text = f"관측 {v['observed_complexes']}곳 {v['observed_kwh']:,.0f} kWh + " if v.get("observed_kwh") is not None else ""
        add("estimate_apartments",
            f"{y}년 공동주택 전력에서 12개월이 다 관측되지 않은 단지 {v['estimated_complexes']}곳을 같은 단지의 다른 해·달로 채우면 "
            f"{obs_text}추정 {v['estimated_kwh']:,.0f} kWh = {v['total_kwh']:,.0f} kWh입니다(추정값).{peer}",
            y, v["estimated_complexes"], v.get("observed_complexes"), v.get("observed_kwh"), v["estimated_kwh"], v["total_kwh"], v.get("peer_median_complexes") or None)
    p = e.get("population") or {}
    for y in sorted(p):
        v = p[y]
        hh = f", 가구 {v['households']:,}" if v.get("households") is not None else ""
        ty = v.get("trend_years") or []
        add("estimate_population", f"{y}년 행정동 인구는 아직 공표되지 않아 {ty[0]}~{ty[-1]}년 추세로 추정하면 인구 {v['population']:,}명{hh}입니다(추정값)." if ty else
            f"{y}년 행정동 인구 추정은 {v['population']:,}명{hh}입니다(추정값).", y, v["population"], v.get("households"), *(ty[:1] + ty[-1:]))


def describe() -> dict[str, Any]:
    """Methods and backtest for the data standard page (no values)."""
    return {"rule_version": RULE_VERSION, "methods": METHOD_LABELS, "backtest": BACKTEST,
            "parameters": {"max_gap_run": MAX_GAP_RUN, "min_common_months": MIN_COMMON_MONTHS, "backcast_base_years": list(BACKCAST_BASE_YEARS),
                           "kapt_neighbor_max_years": KAPT_NEIGHBOR_MAX, "kapt_min_peers": KAPT_MIN_PEERS, "population_trend_years": POP_TREND_YEARS}}

