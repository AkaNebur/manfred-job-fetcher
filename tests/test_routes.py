"""Route smoke tests plus a guard for the sync-handler contract.

Route handlers must stay plain ``def`` (not ``async def``): they call blocking,
synchronous services, so FastAPI must run them in its threadpool to avoid blocking
the event loop. ``test_route_handlers_are_synchronous`` fails if that regresses.
"""
import inspect

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import app as app_module
import routes

client = TestClient(app_module.app)


def _handlers():
    return [r.endpoint for r in routes.router.routes if isinstance(r, APIRoute)]


def test_route_handlers_are_synchronous():
    async_handlers = [fn.__name__ for fn in _handlers() if inspect.iscoroutinefunction(fn)]
    assert async_handlers == [], (
        f"Handlers must be sync so blocking work runs in the threadpool: {async_handlers}"
    )


def test_health_endpoint_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_job_skills_unknown_offer_returns_404():
    resp = client.get("/job-skills/999999")
    assert resp.status_code == 404


def test_send_notifications_without_webhook_returns_400():
    resp = client.post("/send-notifications")
    assert resp.status_code == 400


def test_cleanup_notifications_without_webhook_returns_400():
    resp = client.delete("/cleanup-notifications")
    assert resp.status_code == 400
