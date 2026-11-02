import uuid
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.modules.auth import router as auth_router


@pytest.mark.asyncio
async def test_signup_success(async_client: AsyncClient) -> None:
    unique_email = f"user_{uuid.uuid4().hex[:8]}@example.com"
    payload = {
        "email": unique_email,
        "name": "Alex Developer",
        "password": "Password123!",
    }
    response = await async_client.post("/api/v1/auth/signup", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "user" in data
    assert data["user"]["email"] == unique_email
    assert data["user"]["name"] == "Alex Developer"
    assert data["user"]["is_active"] is True
    assert "tokens" not in data
    assert "access_token" not in data
    assert "refresh_token" not in data
    set_cookie_headers = response.headers.get_list("set-cookie")
    assert any(
        "access_token=" in value and "httponly" in value.lower() for value in set_cookie_headers
    )
    assert any(
        "refresh_token=" in value and "httponly" in value.lower() for value in set_cookie_headers
    )
    assert response.cookies.get("csrf_token")


@pytest.mark.asyncio
async def test_signup_duplicate_email(async_client: AsyncClient) -> None:
    unique_email = f"dupe_{uuid.uuid4().hex[:8]}@example.com"
    payload = {
        "email": unique_email,
        "name": "Duplicate User",
        "password": "Password123!",
    }
    res1 = await async_client.post("/api/v1/auth/signup", json=payload)
    assert res1.status_code == 201

    res2 = await async_client.post("/api/v1/auth/signup", json=payload)
    assert res2.status_code == 409
    assert "already exists" in res2.json()["detail"]


@pytest.mark.asyncio
async def test_signup_validation_errors(async_client: AsyncClient) -> None:
    # Weak password (< 8 chars)
    res_weak = await async_client.post(
        "/api/v1/auth/signup",
        json={"email": "valid@example.com", "name": "Valid", "password": "short"},
    )
    assert res_weak.status_code == 422

    # Invalid email format
    res_bad_email = await async_client.post(
        "/api/v1/auth/signup",
        json={"email": "not-an-email", "name": "Valid", "password": "Password123!"},
    )
    assert res_bad_email.status_code == 422


@pytest.mark.asyncio
async def test_login_flow(async_client: AsyncClient) -> None:
    unique_email = f"login_{uuid.uuid4().hex[:8]}@example.com"
    password = "CorrectPassword123!"
    await async_client.post(
        "/api/v1/auth/signup",
        json={"email": unique_email, "name": "Login Tester", "password": password},
    )

    # Valid login
    res_login = await async_client.post(
        "/api/v1/auth/login",
        json={"email": unique_email, "password": password},
    )
    assert res_login.status_code == 200
    data = res_login.json()
    assert data["user"]["email"] == unique_email
    assert "tokens" not in data
    assert res_login.cookies.get("access_token")
    assert res_login.cookies.get("refresh_token")

    # Invalid password
    res_wrong_pw = await async_client.post(
        "/api/v1/auth/login",
        json={"email": unique_email, "password": "WrongPassword!"},
    )
    assert res_wrong_pw.status_code == 401

    # Nonexistent user
    res_nonexistent = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "nonexistent@example.com", "password": "SomePassword123!"},
    )
    assert res_nonexistent.status_code == 401


@pytest.mark.asyncio
async def test_token_refresh(async_client: AsyncClient) -> None:
    unique_email = f"refresh_{uuid.uuid4().hex[:8]}@example.com"
    await async_client.post(
        "/api/v1/auth/signup",
        json={"email": unique_email, "name": "Refresher", "password": "Password123!"},
    )
    # Successful refresh
    csrf_token = async_client.cookies.get("csrf_token")
    assert csrf_token is not None
    headers: dict[str, str] = {
        "Origin": "http://localhost:3000",
        "X-CSRF-Token": csrf_token,
    }
    res_refresh = await async_client.post(
        "/api/v1/auth/refresh",
        headers=headers,
    )
    assert res_refresh.status_code == 204
    assert res_refresh.content == b""
    assert res_refresh.cookies.get("access_token")
    assert res_refresh.cookies.get("refresh_token")

    # Invalid refresh token
    async_client.cookies.set("refresh_token", "invalid_jwt_token_123")
    headers["X-CSRF-Token"] = async_client.cookies.get("csrf_token") or ""
    res_bad = await async_client.post(
        "/api/v1/auth/refresh",
        headers=headers,
    )
    assert res_bad.status_code == 401

    # Cookie-authenticated writes reject missing CSRF proof.
    res_no_csrf = await async_client.post("/api/v1/auth/logout")
    assert res_no_csrf.status_code == 403


@pytest.mark.asyncio
async def test_get_me_endpoint(async_client: AsyncClient) -> None:
    unique_email = f"me_{uuid.uuid4().hex[:8]}@example.com"
    res_unauth = await async_client.get("/api/v1/auth/me")
    assert res_unauth.status_code == 401

    await async_client.post(
        "/api/v1/auth/signup",
        json={"email": unique_email, "name": "Current User", "password": "Password123!"},
    )

    # Authenticated request
    res_me = await async_client.get("/api/v1/auth/me")
    assert res_me.status_code == 200
    assert res_me.json()["email"] == unique_email
    assert res_me.json()["name"] == "Current User"

    # Tampered token
    res_bad_token = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer fake.tampered.token"},
    )
    assert res_bad_token.status_code == 401


@pytest.mark.asyncio
async def test_logout_clears_session_cookies(async_client: AsyncClient) -> None:
    await async_client.post(
        "/api/v1/auth/signup",
        json={
            "email": f"logout_{uuid.uuid4().hex[:8]}@example.com",
            "name": "Logout User",
            "password": "Password123!",
        },
    )
    csrf_token = async_client.cookies.get("csrf_token")
    logout_headers: dict[str, str] = {
        "Origin": "http://localhost:3000",
    }
    if csrf_token:
        logout_headers["X-CSRF-Token"] = csrf_token

    response = await async_client.post(
        "/api/v1/auth/logout",
        headers=logout_headers,
    )
    assert response.status_code == 204
    set_cookie_headers = response.headers.get_list("set-cookie")
    assert any(
        "access_token=" in value and "max-age=0" in value.lower() for value in set_cookie_headers
    )
    assert any(
        "refresh_token=" in value and "max-age=0" in value.lower() for value in set_cookie_headers
    )


@pytest.mark.asyncio
async def test_password_reset_request_is_generic_and_reset_token_is_single_use(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SMTP_HOST", "localhost")
    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", "http://localhost:3000")
    welcome_emails: list[tuple[str, str]] = []

    def mock_send_welcome(*args: Any) -> None:
        if len(args) >= 2:
            welcome_emails.append((str(args[0]), str(args[1])))

    monkeypatch.setattr(
        auth_router.send_welcome_email,
        "delay",
        mock_send_welcome,
    )
    email_tasks: list[tuple[str, str]] = []

    def mock_send_reset(*args: Any) -> None:
        if len(args) >= 2:
            email_tasks.append((str(args[0]), str(args[1])))

    monkeypatch.setattr(
        auth_router.send_password_reset_email,
        "delay",
        mock_send_reset,
    )
    email = f"reset_{uuid.uuid4().hex[:8]}@example.com"
    old_password = "OldPassword123!"
    await async_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "name": "Reset User", "password": old_password},
    )
    assert welcome_emails == [(email, "Reset User")]

    known = await async_client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": email},
    )
    unknown = await async_client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "missing@example.com"},
    )
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert len(email_tasks) == 1

    reset_url = email_tasks[0][1]
    token = parse_qs(urlparse(reset_url).query)["token"][0]
    reset = await async_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "password": "NewPassword123!"},
    )
    assert reset.status_code == 204

    reused = await async_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "password": "AnotherPassword123!"},
    )
    assert reused.status_code == 400
    assert (
        await async_client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": old_password},
        )
    ).status_code == 401
    assert (
        await async_client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "NewPassword123!"},
        )
    ).status_code == 200


@pytest.mark.asyncio
async def test_update_profile(async_client: AsyncClient) -> None:
    async_client.headers["Origin"] = "http://localhost:3000"
    email = f"profile_{uuid.uuid4().hex[:8]}@example.com"
    await async_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "name": "Initial Name", "password": "Password123!"},
    )

    csrf = async_client.cookies.get("csrf_token")
    headers: dict[str, str] = {"X-CSRF-Token": csrf} if csrf else {}

    # Update name successfully
    update_res = await async_client.patch(
        "/api/v1/auth/me",
        json={"name": "Updated Name"},
        headers=headers,
    )
    assert update_res.status_code == 200
    assert update_res.json()["name"] == "Updated Name"

    # Verify GET /me returns updated name
    me_res = await async_client.get("/api/v1/auth/me")
    assert me_res.status_code == 200
    assert me_res.json()["name"] == "Updated Name"

    # Validation: empty name
    bad_res = await async_client.patch(
        "/api/v1/auth/me",
        json={"name": ""},
        headers=headers,
    )
    assert bad_res.status_code == 422


@pytest.mark.asyncio
async def test_change_password(async_client: AsyncClient) -> None:
    async_client.headers["Origin"] = "http://localhost:3000"
    email = f"changepw_{uuid.uuid4().hex[:8]}@example.com"
    old_pw = "OriginalPass123!"
    new_pw = "BrandNewPass456!"

    await async_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "name": "Change PW User", "password": old_pw},
    )

    csrf = async_client.cookies.get("csrf_token")
    headers: dict[str, str] = {"X-CSRF-Token": csrf} if csrf else {}

    # Wrong current password
    fail_res = await async_client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "WrongCurrentPassword123!", "new_password": new_pw},
        headers=headers,
    )
    assert fail_res.status_code == 400
    assert "incorrect" in fail_res.json()["detail"].lower()

    # Success change password
    success_res = await async_client.post(
        "/api/v1/auth/change-password",
        json={"current_password": old_pw, "new_password": new_pw},
        headers=headers,
    )
    assert success_res.status_code == 204

    # Verify old password cannot log in
    old_login = await async_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": old_pw},
    )
    assert old_login.status_code == 401

    # Verify new password logs in successfully
    new_login = await async_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": new_pw},
    )
    assert new_login.status_code == 200
