import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.runs.schemas import DailyActivityResponse
from app.modules.runs.service import RunService


@pytest.mark.asyncio
async def test_get_daily_activity_service():
    mock_db = AsyncMock()
    service = RunService(mock_db)

    # Mock execute result
    mock_row_1 = MagicMock()
    mock_row_1.day = datetime(2026, 9, 15, tzinfo=UTC).date()
    mock_row_1.count = 2

    mock_row_2 = MagicMock()
    mock_row_2.day = datetime(2026, 9, 16, tzinfo=UTC).date()
    mock_row_2.count = 5

    mock_db.execute.return_value = [mock_row_1, mock_row_2]

    ws_id = uuid.uuid4()
    result = await service.get_daily_activity(workspace_id=ws_id, days=30)

    assert result["total_runs"] == 7
    assert len(result["daily_counts"]) == 2
    assert result["activity_map"]["2026-09-15"] == 2
    assert result["activity_map"]["2026-09-16"] == 5

    validated = DailyActivityResponse.model_validate(result)
    assert validated.total_runs == 7
    assert validated.activity_map["2026-09-15"] == 2

