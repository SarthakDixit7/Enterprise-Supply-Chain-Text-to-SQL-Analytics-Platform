from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from logisql.api.main import create_app
from logisql.config import Settings
from tests.helpers import FakeLLM


def test_query_returns_429_when_the_only_worker_is_busy(test_settings: Settings) -> None:
    settings = test_settings.model_copy(
        update={"max_concurrent_queries": 1, "query_queue_timeout_seconds": 0.05}
    )
    app = create_app(settings, llm=FakeLLM())
    started = threading.Event()

    async def slow_run(**_: object) -> dict[str, object]:
        started.set()
        await asyncio.sleep(0.6)
        return {
            "status": "success",
            "headline": "ok",
            "summary": "",
            "columns": ["order_count"],
            "rows": [{"order_count": 1}],
            "row_count": 1,
        }

    with TestClient(app) as client:
        client.app.state.container.agent.run = slow_run

        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(
                client.post,
                "/api/v1/query",
                json={"question": "How many orders are there?"},
            )
            assert started.wait(timeout=2.0)

            busy = client.post(
                "/api/v1/query",
                json={"question": "How many sellers are there?"},
            )
            assert busy.status_code == 429
            assert busy.headers["Retry-After"] == "5"
            assert busy.json()["request_id"]
            assert "capacity" in busy.json()["detail"]

            completed = first.result(timeout=5.0)
            assert completed.status_code == 200
            assert completed.json()["status"] == "success"

        metrics = client.get("/api/v1/metrics").json()
        assert metrics["queries_total"] == 1
        assert metrics["queries_succeeded"] == 1
        assert metrics["queries_rejected_busy"] == 1
        assert metrics["in_flight"] == 0
