from httpx import AsyncClient


async def test_live(client: AsyncClient) -> None:
    r = await client.get("/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_health_reports_db_and_redis_separately(client: AsyncClient) -> None:
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["redis"]["status"] == "ok"


async def test_correlation_id_propagated_and_generated(client: AsyncClient) -> None:
    r = await client.get("/health/live", headers={"X-Correlation-ID": "abc12345-test"})
    assert r.headers["X-Correlation-ID"] == "abc12345-test"
    r2 = await client.get("/health/live", headers={"X-Correlation-ID": "bad id with spaces"})
    assert r2.headers["X-Correlation-ID"] != "bad id with spaces"
    assert r2.headers["X-Content-Type-Options"] == "nosniff"


async def test_error_envelope_for_unknown_route(client: AsyncClient) -> None:
    r = await client.get("/api/v1/does-not-exist")
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "not_found"
    assert err["correlation_id"]
