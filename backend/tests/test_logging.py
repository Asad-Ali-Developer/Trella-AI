from app.core.logging import filter_sensitive_data


def test_filter_sensitive_data_redacts_credentials() -> None:
    event_dict = {
        "event": "user_authenticated",
        "email": "user@example.com",
        "password": "SuperSecretPassword123",
        "access_token": "ey1234567890",
        "api_key": "sec_12345",
        "safe_field": "ok_value",
    }
    filtered = filter_sensitive_data(None, "info", event_dict)
    assert filtered["email"] == "user@example.com"
    assert filtered["safe_field"] == "ok_value"
    assert filtered["password"] == "[REDACTED]"
    assert filtered["access_token"] == "[REDACTED]"
    assert filtered["api_key"] == "[REDACTED]"
