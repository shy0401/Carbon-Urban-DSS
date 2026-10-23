"""The readiness card counts big tables once per 10 minutes (energy_monthly has millions of rows)."""
from app import readiness


class _Db:
    def __init__(self, calls):
        self.calls = calls

    def scalar(self, statement):
        self.calls.append(statement)
        return 42


def test_pipeline_counts_are_cached_per_process():
    calls: list = []
    readiness._COUNTS.clear()
    assert readiness._cached_count(_Db(calls), "energy_monthly", readiness.EnergyMonthly) == 42
    assert readiness._cached_count(_Db(calls), "energy_monthly", readiness.EnergyMonthly) == 42
    assert len(calls) == 1, "the second call within the TTL must not query the database"
    readiness._COUNTS.clear()
