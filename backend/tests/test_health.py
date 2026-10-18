import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_root_health_check_returns_200(async_client: AsyncClient) -> None:
    """Verify that root /health endpoint responds with 200 and expected payload."""
    response = await async_client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "client-insights-api"
    assert "version" in data
    assert "environment" in data


@pytest.mark.asyncio
async def test_api_v1_health_check_returns_200(async_client: AsyncClient) -> None:
    """Verify that versioned /api/v1/health endpoint responds with 200 and expected payload."""
    response = await async_client.get("/api/v1/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "client-insights-api"
    assert data["version"] == "0.1.0"
