from __future__ import annotations

import argparse
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pg_data_yaml.main import run


@pytest.mark.asyncio
async def test_run_waits_before_close_on_cancelled_error():
    args = argparse.Namespace(command='export')
    pg = MagicMock()
    pg.init = AsyncMock()
    pg.close = AsyncMock()

    with patch('pg_data_yaml.main.Pg', return_value=pg), \
            patch('pg_data_yaml.main.Extractor') as extractor_cls, \
            patch('pg_data_yaml.main.asyncio.sleep', new=AsyncMock()) as sleep_mock, \
            patch('pg_data_yaml.main.sys.exit', side_effect=SystemExit(130)) as exit_mock:
        extractor_cls.return_value.export = AsyncMock(side_effect=asyncio.CancelledError())

        with pytest.raises(SystemExit):
            await run(args)

    sleep_mock.assert_awaited_once_with(0.5)
    pg.close.assert_awaited_once()
    exit_mock.assert_called_once_with(130)
