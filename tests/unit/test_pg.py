from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pg_data_yaml.pg import Pg


@pytest.mark.asyncio
async def test_execute_runs_query_with_signal_handler():
    pg = Pg(MagicMock())
    pg.con = MagicMock()
    pg.con.execute = AsyncMock()

    async def passthrough(coro):
        return await coro

    with patch.object(pg, '_run_with_signal_handler', new=AsyncMock(side_effect=passthrough)):
        await pg.execute("update public.countries set name = 'x';")

    pg.con.execute.assert_awaited_once_with("update public.countries set name = 'x';")


@pytest.mark.asyncio
async def test_run_with_signal_handler_propagates_cancelled_error():
    pg = Pg(MagicMock())

    async def cancelled_coro():
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await pg._run_with_signal_handler(cancelled_coro())
