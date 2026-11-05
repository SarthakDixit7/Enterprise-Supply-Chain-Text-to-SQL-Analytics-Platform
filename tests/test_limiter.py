from __future__ import annotations

import asyncio
from types import SimpleNamespace

from logisql.api.routes import ServerBusyError, _acquire_slot, server_busy_response


async def test_acquire_slot_succeeds_when_capacity_is_free() -> None:
    semaphore = asyncio.Semaphore(1)
    assert await _acquire_slot(semaphore, 0.05) is True
    semaphore.release()


async def test_acquire_slot_times_out_when_saturated() -> None:
    semaphore = asyncio.Semaphore(1)
    await semaphore.acquire()
    try:
        assert await _acquire_slot(semaphore, 0.01) is False
    finally:
        semaphore.release()


def test_server_busy_response_is_retryable() -> None:
    request = SimpleNamespace(state=SimpleNamespace(request_id="req-123"))
    response = server_busy_response(request, ServerBusyError("at capacity"))
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "5"
    assert b"at capacity" in response.body
    assert b"req-123" in response.body
