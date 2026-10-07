"""Heating/cooling degree days — the single rule every weather source uses (docs/DATA_STANDARD.md 5.10).

HDD = Σ max(18 − T, 0) and CDD = Σ max(T − 24, 0) over the daily mean temperature T (°C·day), the bases of the
한국가스공사 "월별 시도별 냉난방도일 통계현황" (also used by the team dataset urban-carbon, config/rules.yaml).
A month with any day missing gets no value: a partial sum would look like a mild month.
"""
from __future__ import annotations

from typing import Iterable

HDD_BASE_C = 18.0
CDD_BASE_C = 24.0
RULE = "HDD 18°C · CDD 24°C"
RULE_ID = "hdd18-cdd24"


def degree_days(daily_means: Iterable[float | None], expected_days: int) -> tuple[float | None, float | None]:
    """(HDD, CDD) of one month from its daily mean temperatures; (None, None) unless every day is known."""
    known = [float(t) for t in daily_means if t is not None]
    if not known or len(known) < expected_days:
        return None, None
    return sum(max(HDD_BASE_C - t, 0.0) for t in known), sum(max(t - CDD_BASE_C, 0.0) for t in known)
