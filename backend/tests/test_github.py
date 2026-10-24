import uuid
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.encryption import encryption
from app.modules.auth.models import User
from app.modules.connections.models import ProviderAccount, WorkspaceConnection
from app.modules.connections.repository import ConnectionRepository
from app.modules.github.client import GithubAPIError, _next_link
from app.modules.github.models import GithubCommit, GithubRepository
from app.modules.github.sync import sync_github_repository
from app.modules.trello.models import TrelloClientRecord
from app.modules.workspaces.models import Membership, MembershipRole, Workspace


async def _create_github_user(async_client: AsyncClient) -> str:
    email = f"github_{uuid.uuid4().hex[:8]}@example.com"
    response = await async_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "name": "GitHub Tester", "password": "Password123!"},
    )
    assert response.status_code == 201
    async_client.headers["Origin"] = "http://localhost:3000"
    async_client.headers["X-CSRF-Token"] = async_client.cookies.get("csrf_token", "")
    return email


async def _workspace(
    async_client: AsyncClient,
    name: str,
) -> uuid.UUID:
    response = await async_client.post("/api/v1/workspaces", json={"name": name})
    assert response.status_code == 201
    return uuid.UUID(response.json()["id"])


async def _user(db_session: AsyncSession, email: str) -> User:
    return (await db_session.execute(select(User).where(User.email == email))).scalar_one()


async def _link_github(
    db_session: AsyncSession,
    user: User,
    workspace: Workspace,
    *,
    username: str,
) -> WorkspaceConnection:
    return await ConnectionRepository(db_session).upsert_provider_connection(
        workspace_id=workspace.id,
        provider="github",
        user_id=user.id,
        encrypted_token=encryption.encrypt(f"token-for-{username}"),
        external_account_id=f"github-account-{username}",
        external_username=username,
    )


@pytest.mark.asyncio
async def test_github_oauth_uses_single_use_state_and_encrypts_reusable_account(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.modules.github.service.settings.GITHUB_CLIENT_ID", "github-client")
    monkeypatch.setattr("app.modules.github.service.settings.GITHUB_CLIENT_SECRET", "github-secret")
    email = await _create_github_user(async_client)
    workspace_id = await _workspace(async_client, "GitHub OAuth workspace")
    async_client.headers["X-Workspace-Id"] = str(workspace_id)

    authorize_response = await async_client.get("/api/v1/connections/github/authorize")
    assert authorize_response.status_code == 200
    authorization_url = authorize_response.json()["authorization_url"]
    query = parse_qs(urlparse(authorization_url).query)
    assert query["client_id"] == ["github-client"]
    assert query["redirect_uri"] == ["http://localhost:3000/dashboard/github/callback"]
    assert query["scope"] == ["read:user repo"]

    class FakeGithubClient:
        def __init__(self, token: str) -> None:
            self.token = token

        async def __aenter__(self) -> "FakeGithubClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        @staticmethod
        async def exchange_code(code: str) -> str:
            assert code == "one-time-code"
            return "gho-secret-token"

        async def get_user(self) -> dict[str, object]:
            return {"id": 938475, "login": "octo-user"}

    monkeypatch.setattr("app.modules.github.service.GithubClient", FakeGithubClient)
    callback = await async_client.post(
        "/api/v1/connections/github/callback",
        json={
            "code": "one-time-code",
            "state": query["state"][0],
            "workspace_id": str(workspace_id),
        },
    )

    assert callback.status_code == 200
    assert callback.json()["connected"] is True
    assert callback.json()["username"] == "octo-user"
    account = (
        await db_session.execute(
            select(ProviderAccount).where(
                ProviderAccount.provider == "github",
                ProviderAccount.user_id == (await _user(db_session, email)).id,
            )
        )
    ).scalar_one()
    assert account.encrypted_token != "gho-secret-token"
    assert encryption.decrypt(account.encrypted_token) == "gho-secret-token"

    replay = await async_client.post(
        "/api/v1/connections/github/callback",
        json={
            "code": "one-time-code",
            "state": query["state"][0],
            "workspace_id": str(workspace_id),
        },
    )
    assert replay.status_code == 400


@pytest.mark.asyncio
async def test_github_account_can_be_reused_and_repositories_stay_workspace_scoped(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = await _create_github_user(async_client)
    first_workspace_id = await _workspace(async_client, "First GitHub workspace")
    second_workspace_id = await _workspace(async_client, "Second GitHub workspace")
    user = await _user(db_session, email)
    first_workspace = (
        await db_session.execute(select(Workspace).where(Workspace.id == first_workspace_id))
    ).scalar_one()
    first_connection = await _link_github(
        db_session,
        user,
        first_workspace,
        username="shared-github-user",
    )
    first_repo = GithubRepository(
        workspace_id=first_workspace_id,
        connection_id=first_connection.id,
        github_repo_id="9001",
        full_name="octo/shared-project",
        description="Project repository",
        url="https://github.com/octo/shared-project",
        default_branch="main",
        private=True,
        included=True,
        sync_status="completed",
    )
    ignored_repo = GithubRepository(
        workspace_id=first_workspace_id,
        connection_id=first_connection.id,
        github_repo_id="9002",
        full_name="octo/not-selected",
        description=None,
        url="https://github.com/octo/not-selected",
        default_branch="main",
        private=False,
        included=False,
    )
    db_session.add_all([first_repo, ignored_repo])
    await db_session.flush()
    commit = GithubCommit(
        workspace_id=first_workspace_id,
        repository_id=first_repo.id,
        sha="a" * 40,
        message="Add workspace-aware integration",
        author_name="Octo User",
        author_login="octo-user",
        committed_at=datetime.now(UTC),
        url="https://github.com/octo/shared-project/commit/" + "a" * 40,
    )
    db_session.add(commit)
    await db_session.commit()

    async_client.headers["X-Workspace-Id"] = str(second_workspace_id)
    status_response = await async_client.get("/api/v1/connections/github")
    accounts_response = await async_client.get("/api/v1/connections/github/accounts")
    link_response = await async_client.post(
        "/api/v1/connections/github/accounts/link",
        json={"account_id": status_response.json()["account_id"]}
        if status_response.json()["connected"]
        else {"account_id": str(first_connection.provider_account_id)},
    )
    assert status_response.status_code == 200
    assert status_response.json()["connected"] is False
    assert accounts_response.status_code == 200
    assert len(accounts_response.json()) == 1
    assert link_response.status_code == 200
    assert link_response.json()["username"] == "shared-github-user"

    class FakeGithubClient:
        def __init__(self, token: str) -> None:
            assert token == "token-for-shared-github-user"

        async def __aenter__(self) -> "FakeGithubClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def list_repositories(self) -> list[dict[str, object]]:
            return [
                {
                    "id": 9001,
                    "full_name": "octo/shared-project",
                    "description": "Project repository",
                    "html_url": "https://github.com/octo/shared-project",
                    "default_branch": "main",
                    "private": True,
                }
            ]

    monkeypatch.setattr("app.modules.github.service.GithubClient", FakeGithubClient)
    repositories_response = await async_client.post(
        "/api/v1/connections/github/repositories/refresh",
        json={},
    )
    assert repositories_response.status_code == 200
    assert repositories_response.json() == [
        {
            "id": "9001",
            "full_name": "octo/shared-project",
            "description": "Project repository",
            "url": "https://github.com/octo/shared-project",
            "default_branch": "main",
            "private": True,
            "included": False,
            "client_id": None,
            "sync_status": "not_started",
            "last_synced_at": None,
            "sync_error": None,
        }
    ]

    scheduled_ids: list[uuid.UUID] = []

    async def schedule_sync(repository_id: uuid.UUID) -> None:
        scheduled_ids.append(repository_id)

    monkeypatch.setattr("app.modules.github.router.enqueue_repository_sync", schedule_sync)
    selection_response = await async_client.put(
        "/api/v1/connections/github/repositories",
        json={"repositories": [{"id": "9001", "included": True, "client_id": None}]},
    )
    assert selection_response.status_code == 200
    assert selection_response.json()["saved"] == 1
    assert len(scheduled_ids) == 1
    selected_repositories = await async_client.get("/api/v1/connections/github/repositories")
    assert selected_repositories.json()[0]["included"] is True

    async_client.headers["X-Workspace-Id"] = str(second_workspace_id)
    context = await async_client.get("/api/v1/context")
    assert context.status_code == 200
    context_items = [item for chunk in context.json()["chunks"] for item in chunk["items"]]
    assert not any(item["item_type"] == "commit" for item in context_items)


@pytest.mark.asyncio
async def test_github_commits_appear_only_for_included_repositories_and_matching_client(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    email = await _create_github_user(async_client)
    workspace_id = await _workspace(async_client, "GitHub context workspace")
    user = await _user(db_session, email)
    workspace = (
        await db_session.execute(select(Workspace).where(Workspace.id == workspace_id))
    ).scalar_one()
    connection = await _link_github(db_session, user, workspace, username="context-user")
    client = TrelloClientRecord(workspace_id=workspace_id, name="Acme")
    db_session.add(client)
    await db_session.flush()
    included = GithubRepository(
        workspace_id=workspace_id,
        connection_id=connection.id,
        github_repo_id="9101",
        full_name="octo/acme",
        description=None,
        url="https://github.com/octo/acme",
        default_branch="main",
        private=True,
        included=True,
        client_id=client.id,
        sync_status="completed",
        last_synced_at=datetime.now(UTC),
    )
    excluded = GithubRepository(
        workspace_id=workspace_id,
        connection_id=connection.id,
        github_repo_id="9102",
        full_name="octo/other",
        description=None,
        url="https://github.com/octo/other",
        default_branch="main",
        private=False,
        included=False,
    )
    db_session.add_all([included, excluded])
    await db_session.flush()
    db_session.add_all(
        [
            GithubCommit(
                workspace_id=workspace_id,
                repository_id=repo.id,
                sha=sha * 40,
                message=message,
                author_name="Octo User",
                author_login="octo-user",
                committed_at=datetime.now(UTC),
                url=f"{repo.url}/commit/{sha * 40}",
            )
            for repo, sha, message in (
                (included, "b", "Add customer portal improvements"),
                (excluded, "c", "Change unrelated settings"),
            )
        ]
    )
    await db_session.commit()
    async_client.headers["X-Workspace-Id"] = str(workspace_id)

    full_context = await async_client.get("/api/v1/context")
    client_context = await async_client.get(f"/api/v1/context?client_id={client.id}")
    assert full_context.status_code == client_context.status_code == 200

    full_items = [item for chunk in full_context.json()["chunks"] for item in chunk["items"]]
    client_items = [item for chunk in client_context.json()["chunks"] for item in chunk["items"]]
    commits = [item for item in full_items if item["item_type"] == "commit"]
    assert len(commits) == 1
    assert commits[0]["title"] == "Add customer portal improvements"
    assert commits[0]["source_name"] == "octo/acme"
    assert "Change unrelated settings" not in str(full_items)
    assert [item["title"] for item in client_items if item["item_type"] == "commit"] == [
        "Add customer portal improvements"
    ]


@pytest.mark.asyncio
async def test_github_commit_sync_is_idempotent(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"github_sync_{uuid.uuid4().hex[:8]}@example.com"
    user = User(email=email, name="Sync User", hashed_password="unused")
    db_session.add(user)
    await db_session.flush()
    workspace = Workspace(
        name="Commit sync workspace",
        slug=f"sync-{uuid.uuid4().hex[:8]}",
        owner_id=user.id,
    )
    db_session.add(workspace)
    await db_session.flush()
    db_session.add(
        Membership(workspace_id=workspace.id, user_id=user.id, role=MembershipRole.OWNER)
    )
    connection = await _link_github(db_session, user, workspace, username="sync-user")
    repository = GithubRepository(
        workspace_id=workspace.id,
        connection_id=connection.id,
        github_repo_id="9201",
        full_name="octo/sync-project",
        description=None,
        url="https://github.com/octo/sync-project",
        default_branch="main",
        private=False,
        included=True,
    )
    db_session.add(repository)
    await db_session.flush()

    class FakeGithubClient:
        def __init__(self, token: str) -> None:
            assert token == "token-for-sync-user"

        async def __aenter__(self) -> "FakeGithubClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def list_commits(
            self,
            full_name: str,
            *,
            since: datetime | None,
        ) -> list[dict[str, object]]:
            assert full_name == "octo/sync-project"
            return [
                {
                    "sha": "d" * 40,
                    "html_url": f"https://github.com/{full_name}/commit/{'d' * 40}",
                    "author": {"login": "octo-user"},
                    "commit": {
                        "message": "Add sync coverage",
                        "author": {"name": "Octo User", "date": "2026-10-24T08:00:00Z"},
                        "committer": {"date": "2026-10-24T08:00:00Z"},
                    },
                }
            ]

    monkeypatch.setattr("app.modules.github.sync.GithubClient", FakeGithubClient)

    first_count = await sync_github_repository(db_session, repository)
    second_count = await sync_github_repository(db_session, repository)
    commits = await db_session.scalars(
        select(GithubCommit).where(GithubCommit.repository_id == repository.id)
    )

    assert first_count == second_count == 1
    assert len(commits.all()) == 1


def test_github_client_rejects_pagination_links_to_other_hosts() -> None:
    with pytest.raises(GithubAPIError, match="unexpected host"):
        _next_link(
            '<https://attacker.example/steal-token?page=2>; rel="next"',
            "https://api.github.com/",
        )
