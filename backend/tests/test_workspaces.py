import uuid

import pytest
from fastapi import APIRouter, Depends
from httpx import AsyncClient

from app.core.deps import get_current_workspace, require_workspace_role
from app.main import app
from app.modules.workspaces.models import Membership, MembershipRole, Workspace

# Internal route used exclusively to test workspace security dependencies
internal_router = APIRouter(prefix="/internal-test-context")


@internal_router.get("/protected")
async def protected_workspace_endpoint(
    ctx: tuple[Workspace, Membership] = Depends(get_current_workspace),
) -> dict[str, str]:
    workspace, membership = ctx
    return {"workspace_name": workspace.name, "role": membership.role.value}


@internal_router.get("/owner-only")
async def owner_only_endpoint(
    ctx: tuple[Workspace, Membership] = Depends(require_workspace_role(MembershipRole.OWNER)),
) -> dict[str, str]:
    return {"status": "owner_verified"}


app.include_router(internal_router)


async def _create_test_user(
    async_client: AsyncClient,
    email_prefix: str = "user",
) -> tuple[str, str]:
    """Helper to register a user and return (email, access_token)."""
    email = f"{email_prefix}_{uuid.uuid4().hex[:8]}@example.com"
    res = await async_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "name": "Workspace Tester", "password": "Password123!"},
    )
    assert res.status_code == 201
    token = res.json()["tokens"]["access_token"]
    return email, token


@pytest.mark.asyncio
async def test_create_workspace_success(async_client: AsyncClient) -> None:
    _, token = await _create_test_user(async_client, "creator")
    slug = f"alpha-growth-{uuid.uuid4().hex[:6]}"
    response = await async_client.post(
        "/api/v1/workspaces",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Alpha Growth Agency", "slug": slug},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Alpha Growth Agency"
    assert data["slug"] == slug
    assert data["role"] == "owner"
    assert "id" in data


@pytest.mark.asyncio
async def test_create_workspace_unauthenticated(async_client: AsyncClient) -> None:
    response = await async_client.post(
        "/api/v1/workspaces",
        json={"name": "No Auth Agency"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_user_workspaces(async_client: AsyncClient) -> None:
    _, token = await _create_test_user(async_client, "lister")
    await async_client.post(
        "/api/v1/workspaces",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Workspace One"},
    )
    await async_client.post(
        "/api/v1/workspaces",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Workspace Two"},
    )

    response = await async_client.get(
        "/api/v1/workspaces",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    workspaces = response.json()
    assert len(workspaces) >= 2
    names = [ws["name"] for ws in workspaces]
    assert "Workspace One" in names
    assert "Workspace Two" in names


@pytest.mark.asyncio
async def test_get_workspace_details_success(async_client: AsyncClient) -> None:
    _, token = await _create_test_user(async_client, "details")
    create_res = await async_client.post(
        "/api/v1/workspaces",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Details Agency"},
    )
    ws_id = create_res.json()["id"]

    response = await async_client.get(
        f"/api/v1/workspaces/{ws_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == ws_id
    assert response.json()["role"] == "owner"


@pytest.mark.asyncio
async def test_workspace_isolation_access_denied(async_client: AsyncClient) -> None:
    _, token_a = await _create_test_user(async_client, "user_a")
    create_res = await async_client.post(
        "/api/v1/workspaces",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "User A Private Workspace"},
    )
    ws_a_id = create_res.json()["id"]

    _, token_b = await _create_test_user(async_client, "user_b")
    response_b = await async_client.get(
        f"/api/v1/workspaces/{ws_a_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response_b.status_code == 403
    assert "do not have access" in response_b.json()["detail"]


@pytest.mark.asyncio
async def test_workspace_dependencies_and_role_enforcement(async_client: AsyncClient) -> None:
    _, token = await _create_test_user(async_client, "role_tester")
    create_res = await async_client.post(
        "/api/v1/workspaces",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Security Agency"},
    )
    ws_id = create_res.json()["id"]

    # Valid X-Workspace-Id header
    res_protected = await async_client.get(
        "/internal-test-context/protected",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": ws_id},
    )
    assert res_protected.status_code == 200
    assert res_protected.json()["workspace_name"] == "Security Agency"
    assert res_protected.json()["role"] == "owner"

    # Valid owner-only endpoint
    res_owner = await async_client.get(
        "/internal-test-context/owner-only",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": ws_id},
    )
    assert res_owner.status_code == 200
    assert res_owner.json()["status"] == "owner_verified"

    # Missing X-Workspace-Id header -> 422 Unprocessable Entity
    res_missing_header = await async_client.get(
        "/internal-test-context/protected",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_missing_header.status_code == 422

    # Random non-existent workspace ID header -> 403 Forbidden (not a member)
    fake_ws_id = str(uuid.uuid4())
    res_forbidden = await async_client.get(
        "/internal-test-context/protected",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": fake_ws_id},
    )
    assert res_forbidden.status_code == 403
