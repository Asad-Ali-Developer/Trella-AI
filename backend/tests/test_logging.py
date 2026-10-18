import io
import logging
from contextlib import redirect_stderr, redirect_stdout

from app.core.logging import filter_sensitive_data, setup_logging


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


def test_setup_logging_formats_standard_library_records() -> None:
    root_logger = logging.getLogger()
    sqlalchemy_logger = logging.getLogger("sqlalchemy.engine")
    previous_handlers = root_logger.handlers
    previous_level = root_logger.level
    previous_sqlalchemy_level = sqlalchemy_logger.level
    stdout = io.StringIO()
    stderr = io.StringIO()

    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            setup_logging()
            sqlalchemy_logger.setLevel(logging.INFO)
            sqlalchemy_logger.info("database query")
    finally:
        root_logger.handlers = previous_handlers
        root_logger.setLevel(previous_level)
        sqlalchemy_logger.setLevel(previous_sqlalchemy_level)

    assert "database query" in stdout.getvalue()
    assert "Logging error" not in stderr.getvalue()
