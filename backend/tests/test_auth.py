import uuid

import pytest
from httpx import AsyncClient


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
    assert "tokens" in data
    assert "access_token" in data["tokens"]
    assert "refresh_token" in data["tokens"]
    assert data["tokens"]["token_type"] == "bearer"


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
    assert "access_token" in data["tokens"]

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
    res_signup = await async_client.post(
        "/api/v1/auth/signup",
        json={"email": unique_email, "name": "Refresher", "password": "Password123!"},
    )
    refresh_token = res_signup.json()["tokens"]["refresh_token"]

    # Successful refresh
    res_refresh = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert res_refresh.status_code == 200
    tokens = res_refresh.json()
    assert "access_token" in tokens
    assert "refresh_token" in tokens

    # Invalid refresh token
    res_bad = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "invalid_jwt_token_123"},
    )
    assert res_bad.status_code == 401


@pytest.mark.asyncio
async def test_get_me_endpoint(async_client: AsyncClient) -> None:
    unique_email = f"me_{uuid.uuid4().hex[:8]}@example.com"
    res_signup = await async_client.post(
        "/api/v1/auth/signup",
        json={"email": unique_email, "name": "Current User", "password": "Password123!"},
    )
    access_token = res_signup.json()["tokens"]["access_token"]

    # Authenticated request
    res_me = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert res_me.status_code == 200
    assert res_me.json()["email"] == unique_email
    assert res_me.json()["name"] == "Current User"

    # Unauthenticated request
    res_unauth = await async_client.get("/api/v1/auth/me")
    assert res_unauth.status_code == 401

    # Tampered token
    res_bad_token = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer fake.tampered.token"},
    )
    assert res_bad_token.status_code == 401
