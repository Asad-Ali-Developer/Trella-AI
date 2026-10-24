import uuid

import pytest
from fastapi import APIRouter, Depends
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_workspace, require_workspace_role
from app.main import app
from app.modules.auth.models import User
from app.modules.connections.models import ProviderAccount, WorkspaceConnection
from app.modules.connections.repository import ConnectionRepository
from app.modules.trello.models import TrelloSource
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
) -> str:
    """Register a user and retain the issued auth cookies in the test client."""
    email = f"{email_prefix}_{uuid.uuid4().hex[:8]}@example.com"
    res = await async_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "name": "Workspace Tester", "password": "Password123!"},
    )
    assert res.status_code == 201
    async_client.headers["Origin"] = "http://localhost:3000"
    async_client.headers["X-CSRF-Token"] = async_client.cookies.get("csrf_token", "")
    return email


@pytest.mark.asyncio
async def test_create_workspace_success(async_client: AsyncClient) -> None:
    await _create_test_user(async_client, "creator")
    slug = f"alpha-growth-{uuid.uuid4().hex[:6]}"
    response = await async_client.post(
        "/api/v1/workspaces",
        json={
            "name": "Alpha Growth Agency",
            "description": "Workspace for product delivery.",
            "client_name": "Alpha Growth",
            "slug": slug,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Alpha Growth Agency"
    assert data["description"] == "Workspace for product delivery."
    assert data["client_name"] == "Alpha Growth"
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
    await _create_test_user(async_client, "lister")
    await async_client.post(
        "/api/v1/workspaces",
        json={"name": "Workspace One"},
    )
    await async_client.post(
        "/api/v1/workspaces",
        json={"name": "Workspace Two"},
    )

    response = await async_client.get(
        "/api/v1/workspaces",
    )
    assert response.status_code == 200
    workspaces = response.json()
    assert len(workspaces) >= 2
    names = [ws["name"] for ws in workspaces]
    assert "Workspace One" in names
    assert "Workspace Two" in names


@pytest.mark.asyncio
async def test_get_workspace_details_success(async_client: AsyncClient) -> None:
    await _create_test_user(async_client, "details")
    create_res = await async_client.post(
        "/api/v1/workspaces",
        json={"name": "Details Agency"},
    )
    ws_id = create_res.json()["id"]

    response = await async_client.get(
        f"/api/v1/workspaces/{ws_id}",
    )
    assert response.status_code == 200
    assert response.json()["id"] == ws_id
    assert response.json()["role"] == "owner"


@pytest.mark.asyncio
async def test_workspace_owner_can_update_details(async_client: AsyncClient) -> None:
    await _create_test_user(async_client, "workspace_editor")
    create_response = await async_client.post(
        "/api/v1/workspaces",
        json={
            "name": "Old workspace name",
            "description": "Old description",
            "client_name": "Old client",
        },
    )
    workspace_id = create_response.json()["id"]

    response = await async_client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        json={
            "name": "New workspace name",
            "description": "New workspace description",
            "client_name": "New client",
        },
    )

    assert response.status_code == 200
    assert response.json()["name"] == "New workspace name"
    assert response.json()["description"] == "New workspace description"
    assert response.json()["client_name"] == "New client"
    assert response.json()["slug"] == create_response.json()["slug"]


@pytest.mark.asyncio
async def test_workspace_update_requires_membership(async_client: AsyncClient) -> None:
    await _create_test_user(async_client, "workspace_owner")
    create_response = await async_client.post(
        "/api/v1/workspaces",
        json={"name": "Private workspace"},
    )
    workspace_id = create_response.json()["id"]

    await _create_test_user(async_client, "workspace_guest")
    response = await async_client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        json={"name": "Unauthorized change"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_disconnect_trello_removes_connection_and_its_sources(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    email = await _create_test_user(async_client, "trello_disconnect")
    create_response = await async_client.post(
        "/api/v1/workspaces",
        json={"name": "Disconnect workspace"},
    )
    workspace_id = uuid.UUID(create_response.json()["id"])
    owner = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    account = ProviderAccount(
        user_id=owner.id,
        provider="trello",
        encrypted_token="encrypted-test-token",
        status="active",
        external_account_id="trello-account",
        external_username="trello-user",
    )
    db_session.add(account)
    await db_session.flush()
    connection = WorkspaceConnection(
        workspace_id=workspace_id,
        user_id=owner.id,
        provider="trello",
        status="active",
        provider_account_id=account.id,
    )
    db_session.add(connection)
    await db_session.flush()
    source = TrelloSource(
        workspace_id=workspace_id,
        connection_id=connection.id,
        trello_board_id="trello-board",
        name="Board",
        url="https://trello.com/b/test",
        excluded=False,
    )
    db_session.add(source)
    await db_session.commit()

    async_client.headers["X-Workspace-Id"] = str(workspace_id)
    response = await async_client.delete("/api/v1/connections/trello")

    assert response.status_code == 200
    assert response.json() == {"connected": False, "username": None, "account_id": None}
    assert (
        await db_session.execute(
            select(WorkspaceConnection).where(WorkspaceConnection.id == connection.id)
        )
    ).scalar_one_or_none() is None
    assert (
        await db_session.execute(select(ProviderAccount).where(ProviderAccount.id == account.id))
    ).scalar_one_or_none() is None
    assert (
        await db_session.execute(select(TrelloSource).where(TrelloSource.id == source.id))
    ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_trello_account_can_be_reused_and_unlinked_per_workspace(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    email = await _create_test_user(async_client, "trello_reuse")
    first_workspace_response = await async_client.post(
        "/api/v1/workspaces",
        json={"name": "First Trello workspace"},
    )
    first_workspace_id = uuid.UUID(first_workspace_response.json()["id"])
    owner = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    repository = ConnectionRepository(db_session)
    first_link = await repository.upsert_provider_connection(
        workspace_id=first_workspace_id,
        user_id=owner.id,
        provider="trello",
        encrypted_token="encrypted-test-token",
        external_account_id="shared-trello-account",
        external_username="shared-trello-user",
    )
    account = await repository.get_provider_account(first_link)
    assert account is not None
    first_source = TrelloSource(
        workspace_id=first_workspace_id,
        connection_id=first_link.id,
        trello_board_id="first-board",
        name="First board",
        url="https://trello.com/b/first",
        excluded=False,
    )
    db_session.add(first_source)
    await db_session.commit()

    second_workspace_response = await async_client.post(
        "/api/v1/workspaces",
        json={"name": "Second Trello workspace"},
    )
    second_workspace_id = uuid.UUID(second_workspace_response.json()["id"])
    async_client.headers["X-Workspace-Id"] = str(second_workspace_id)

    accounts_response = await async_client.get("/api/v1/connections/trello/accounts")
    assert accounts_response.status_code == 200
    assert accounts_response.json() == [{"id": str(account.id), "username": "shared-trello-user"}]
    link_response = await async_client.post(
        "/api/v1/connections/trello/accounts/link",
        json={"account_id": str(account.id)},
    )
    assert link_response.status_code == 200
    assert link_response.json()["connected"] is True
    assert link_response.json()["account_id"] == str(account.id)

    second_link = (
        await db_session.execute(
            select(WorkspaceConnection).where(
                WorkspaceConnection.workspace_id == second_workspace_id,
                WorkspaceConnection.provider == "trello",
            )
        )
    ).scalar_one()
    second_source = TrelloSource(
        workspace_id=second_workspace_id,
        connection_id=second_link.id,
        trello_board_id="second-board",
        name="Second board",
        url="https://trello.com/b/second",
        excluded=False,
    )
    db_session.add(second_source)
    await db_session.commit()

    async_client.headers["X-Workspace-Id"] = str(first_workspace_id)
    disconnect_response = await async_client.delete("/api/v1/connections/trello")

    assert disconnect_response.status_code == 200
    assert (
        await db_session.execute(select(ProviderAccount).where(ProviderAccount.id == account.id))
    ).scalar_one_or_none() is not None
    assert (
        await db_session.execute(
            select(WorkspaceConnection).where(
                WorkspaceConnection.workspace_id == first_workspace_id,
                WorkspaceConnection.provider == "trello",
            )
        )
    ).scalar_one_or_none() is None
    assert (
        await db_session.execute(select(TrelloSource).where(TrelloSource.id == first_source.id))
    ).scalar_one_or_none() is None
    assert (
        await db_session.execute(select(TrelloSource).where(TrelloSource.id == second_source.id))
    ).scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_trello_account_cannot_be_reused_by_another_user(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    first_email = await _create_test_user(async_client, "trello_account_owner")
    first_workspace = await async_client.post(
        "/api/v1/workspaces",
        json={"name": "Account owner's workspace"},
    )
    first_owner = (
        await db_session.execute(select(User).where(User.email == first_email))
    ).scalar_one()
    account = ProviderAccount(
        user_id=first_owner.id,
        provider="trello",
        encrypted_token="encrypted-test-token",
        status="active",
        external_account_id="private-trello-account",
        external_username="private-trello-user",
    )
    db_session.add(account)
    await db_session.flush()
    db_session.add(
        WorkspaceConnection(
            workspace_id=uuid.UUID(first_workspace.json()["id"]),
            user_id=first_owner.id,
            provider="trello",
            provider_account_id=account.id,
            status="active",
        )
    )
    await db_session.commit()

    await _create_test_user(async_client, "other_trello_user")
    other_workspace = await async_client.post(
        "/api/v1/workspaces",
        json={"name": "Other user's workspace"},
    )
    async_client.headers["X-Workspace-Id"] = other_workspace.json()["id"]

    accounts_response = await async_client.get("/api/v1/connections/trello/accounts")
    link_response = await async_client.post(
        "/api/v1/connections/trello/accounts/link",
        json={"account_id": str(account.id)},
    )

    assert accounts_response.status_code == 200
    assert accounts_response.json() == []
    assert link_response.status_code == 404


@pytest.mark.asyncio
async def test_workspace_isolation_access_denied(async_client: AsyncClient) -> None:
    await _create_test_user(async_client, "user_a")
    create_res = await async_client.post(
        "/api/v1/workspaces",
        json={"name": "User A Private Workspace"},
    )
    ws_a_id = create_res.json()["id"]

    await _create_test_user(async_client, "user_b")
    response_b = await async_client.get(
        f"/api/v1/workspaces/{ws_a_id}",
    )
    assert response_b.status_code == 403
    assert "do not have access" in response_b.json()["detail"]


@pytest.mark.asyncio
async def test_workspace_dependencies_and_role_enforcement(async_client: AsyncClient) -> None:
    await _create_test_user(async_client, "role_tester")
    create_res = await async_client.post(
        "/api/v1/workspaces",
        json={"name": "Security Agency"},
    )
    ws_id = create_res.json()["id"]

    # Valid X-Workspace-Id header
    res_protected = await async_client.get(
        "/internal-test-context/protected",
        headers={"X-Workspace-Id": ws_id},
    )
    assert res_protected.status_code == 200
    assert res_protected.json()["workspace_name"] == "Security Agency"
    assert res_protected.json()["role"] == "owner"

    # Valid owner-only endpoint
    res_owner = await async_client.get(
        "/internal-test-context/owner-only",
        headers={"X-Workspace-Id": ws_id},
    )
    assert res_owner.status_code == 200
    assert res_owner.json()["status"] == "owner_verified"

    # Missing X-Workspace-Id header -> 422 Unprocessable Entity
    res_missing_header = await async_client.get(
        "/internal-test-context/protected",
    )
    assert res_missing_header.status_code == 422

    # Random non-existent workspace ID header -> 403 Forbidden (not a member)
    fake_ws_id = str(uuid.uuid4())
    res_forbidden = await async_client.get(
        "/internal-test-context/protected",
        headers={"X-Workspace-Id": fake_ws_id},
    )
    assert res_forbidden.status_code == 403
