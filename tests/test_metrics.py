from __future__ import annotations

from logisql.api.metrics import QueryMetrics


def test_empty_snapshot_has_no_latency_stats() -> None:
    snapshot = QueryMetrics().snapshot()
    assert snapshot.queries_total == 0
    assert snapshot.latency_samples == 0
    assert snapshot.avg_latency_ms is None
    assert snapshot.p95_latency_ms is None


def test_records_success_failure_and_busy() -> None:
    metrics = QueryMetrics()
    metrics.record_start()
    metrics.record_finish(success=True, latency_ms=10.0)
    metrics.record_start()
    metrics.record_finish(success=False, latency_ms=30.0)
    metrics.record_rejected_busy()

    snapshot = metrics.snapshot()
    assert snapshot.queries_total == 2
    assert snapshot.queries_succeeded == 1
    assert snapshot.queries_failed == 1
    assert snapshot.queries_rejected_busy == 1
    assert snapshot.in_flight == 0
    assert snapshot.latency_samples == 2
    assert snapshot.avg_latency_ms == 20.0
    assert snapshot.p95_latency_ms == 30.0


def test_in_flight_tracks_open_requests() -> None:
    metrics = QueryMetrics()
    metrics.record_start()
    metrics.record_start()
    assert metrics.snapshot().in_flight == 2

    metrics.record_finish(success=True, latency_ms=5.0)
    assert metrics.snapshot().in_flight == 1


def test_latency_history_is_bounded() -> None:
    metrics = QueryMetrics(max_latency_samples=3)
    for latency in (1.0, 2.0, 3.0, 4.0, 5.0):
        metrics.record_start()
        metrics.record_finish(success=True, latency_ms=latency)

    snapshot = metrics.snapshot()
    assert snapshot.queries_total == 5
    assert snapshot.latency_samples == 3
    assert snapshot.avg_latency_ms == 4.0
    assert snapshot.p95_latency_ms == 5.0
