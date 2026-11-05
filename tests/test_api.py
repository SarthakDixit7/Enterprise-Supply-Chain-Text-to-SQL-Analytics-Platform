from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from logisql.api.main import create_app
from logisql.config import Settings
from tests.helpers import FakeLLM


@pytest.fixture
def client(test_settings: Settings):
    app = create_app(test_settings, llm=FakeLLM())
    with TestClient(app) as test_client:
        yield test_client


def test_health(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"] is True
    assert payload["llm_configured"] is True
    assert payload["dialect"] == "sqlite"


def test_schema_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/schema")
    assert response.status_code == 200
    payload = response.json()
    names = {table["name"] for table in payload["tables"]}
    assert "orders" in names
    assert any("order_items.order_id -> orders.order_id" in rel for rel in payload["relationships"])


def test_examples_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/examples")
    assert response.status_code == 200
    assert len(response.json()["examples"]) >= 5


def test_query_endpoint(client: TestClient) -> None:
    response = client.post(
        "/api/v1/query",
        json={"question": "How many orders are there by status?", "row_limit": 25},
        headers={"X-Request-ID": "client-request-123"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["request_id"] == "client-request-123"
    assert response.headers["X-Request-ID"] == "client-request-123"
    assert float(response.headers["X-Process-Time-Ms"]) >= 0
    assert payload["row_count"] > 0
    assert payload["chart"] is not None
    assert payload["model"] == "llama-3.3-70b-versatile"
    assert payload["schema_tables"] == 5


def test_overview_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/overview")
    assert response.status_code == 200
    payload = response.json()
    assert payload["orders"] == 120
    assert payload["delivered_orders"] > 0
    assert payload["item_count"] > 0
    assert payload["sellers"] == 40
    assert payload["products"] == 160
    assert payload["gross_item_value"] > 0
    assert payload["measurable_delivered"] >= payload["late_orders"]
    assert payload["on_time_rate"] is not None
    assert 0.0 <= payload["on_time_rate"] <= 1.0
    assert payload["first_order_at"]
    assert payload["last_order_at"]


def test_overview_endpoint_can_force_refresh(client: TestClient) -> None:
    assert client.get("/api/v1/overview").status_code == 200
    refreshed = client.get("/api/v1/overview", params={"force": True})
    assert refreshed.status_code == 200
    assert refreshed.json()["orders"] == 120


def test_query_rejects_short_question(client: TestClient) -> None:
    response = client.post("/api/v1/query", json={"question": "a"})
    assert response.status_code == 422


def test_query_requires_groq_key(test_settings: Settings) -> None:
    settings = test_settings.model_copy(update={"groq_api_key": None})
    app = create_app(settings, llm=FakeLLM())
    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/v1/query",
            json={"question": "How many orders are there?"},
        )
    assert response.status_code == 503
    assert "GROQ_API_KEY" in response.json()["detail"]


def test_root(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["name"] == "LogiSQL-Agent API"
