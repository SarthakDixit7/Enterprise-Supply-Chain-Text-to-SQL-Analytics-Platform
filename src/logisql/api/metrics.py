from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class MetricsSnapshot:
    queries_total: int
    queries_succeeded: int
    queries_failed: int
    queries_rejected_busy: int
    in_flight: int
    latency_samples: int
    avg_latency_ms: float | None
    p95_latency_ms: float | None


class QueryMetrics:
    """Small in-process counter set for the query endpoint.

    Each worker process tracks its own numbers; aggregate across workers if the
    API is deployed with more than one. Latency history is bounded so the
    process cannot grow without limit.
    """

    def __init__(self, max_latency_samples: int = 500) -> None:
        self._latencies: deque[float] = deque(maxlen=max_latency_samples)
        self.queries_total = 0
        self.queries_succeeded = 0
        self.queries_failed = 0
        self.queries_rejected_busy = 0
        self.in_flight = 0

    def record_start(self) -> None:
        self.queries_total += 1
        self.in_flight += 1

    def record_finish(self, *, success: bool, latency_ms: float) -> None:
        self.in_flight = max(0, self.in_flight - 1)
        if success:
            self.queries_succeeded += 1
        else:
            self.queries_failed += 1
        self._latencies.append(max(0.0, latency_ms))

    def record_rejected_busy(self) -> None:
        self.queries_rejected_busy += 1

    def snapshot(self) -> MetricsSnapshot:
        samples = sorted(self._latencies)
        if samples:
            average = round(sum(samples) / len(samples), 2)
            index = max(0, math.ceil(0.95 * len(samples)) - 1)
            p95 = round(samples[index], 2)
        else:
            average = None
            p95 = None

        return MetricsSnapshot(
            queries_total=self.queries_total,
            queries_succeeded=self.queries_succeeded,
            queries_failed=self.queries_failed,
            queries_rejected_busy=self.queries_rejected_busy,
            in_flight=self.in_flight,
            latency_samples=len(samples),
            avg_latency_ms=average,
            p95_latency_ms=p95,
        )


__all__ = ["MetricsSnapshot", "QueryMetrics"]
