from __future__ import annotations

import argparse
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from pg_data_yaml.extractor import DEFAULT_ROWS_LIMIT, Extractor
from pg_data_yaml.registry import SyncTable


def _sync_table() -> SyncTable:
    return SyncTable(
        schema='public',
        table='countries',
        custom_select=None,
        where_filter=None,
        pk_columns=['id'],
    )


def _make_extractor(rows_limit: int | None = None) -> Extractor:
    args = argparse.Namespace(
        comment_label='test label',
        table_list_predicate=None,
        out_dir='/tmp/out',
    )
    if rows_limit is not None:
        args.rows_limit = rows_limit
    extractor = Extractor(args, MagicMock())
    extractor.pg.fetch = AsyncMock(return_value=[{'count': 3}])
    return extractor


@pytest.mark.asyncio
async def test_get_rows_count_uses_default_rows_limit():
    extractor = _make_extractor()

    await extractor.get_rows_count(_sync_table())

    assert extractor.rows_limit == DEFAULT_ROWS_LIMIT
    query = extractor.pg.fetch.await_args.args[0]
    assert f'limit {DEFAULT_ROWS_LIMIT}' in query


@pytest.mark.asyncio
async def test_get_rows_count_uses_custom_rows_limit():
    extractor = _make_extractor(rows_limit=100)

    await extractor.get_rows_count(_sync_table())

    query = extractor.pg.fetch.await_args.args[0]
    assert 'limit 100' in query


@pytest.mark.asyncio
async def test_export_propagates_cancelled_error():
    args = argparse.Namespace(
        comment_label='test label',
        table_list_predicate=None,
        out_dir='/tmp/out',
        rows_limit=DEFAULT_ROWS_LIMIT,
    )
    pg = MagicMock()
    pg.fetch = AsyncMock(side_effect=asyncio.CancelledError())
    extractor = Extractor(args, pg)
    extractor.registry.load = AsyncMock(return_value={
        ('public', 'countries'): _sync_table(),
    })

    with pytest.raises(asyncio.CancelledError):
        await extractor.export()
