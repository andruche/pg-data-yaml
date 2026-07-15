from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from pg_data_yaml.registry import SyncTable
from pg_data_yaml.synchronizer import Synchronizer


def _sync_table(schema: str, table: str) -> SyncTable:
    return SyncTable(
        schema=schema,
        table=table,
        custom_select=None,
        where_filter=None,
        pk_columns=['id'],
    )


def _make_synchronizer(source: str, *, is_dir: bool) -> Synchronizer:
    args = argparse.Namespace(
        source=source,
        yes=True,
        dry_run=False,
        echo_queries=False,
        comment_label='test label',
        table_list_predicate=None,
    )
    synchronizer = Synchronizer(args, MagicMock())
    synchronizer.is_dir = is_dir
    synchronizer.formatter = MagicMock()
    synchronizer.registry = MagicMock()
    synchronizer.registry.get = AsyncMock()
    synchronizer.extractor = MagicMock()
    return synchronizer


@pytest.mark.asyncio
async def test_load_tables_skips_file_when_table_not_in_selection(
    tmp_path: Path,
    capsys,
):
    yaml_file = tmp_path / 'public' / 'countries.yaml'
    yaml_file.parent.mkdir(parents=True)
    yaml_file.write_text('- {id: 1, name: Russia}\n')

    synchronizer = _make_synchronizer(str(tmp_path), is_dir=True)
    synchronizer.registry.get.return_value = None
    synchronizer.formatter.load.return_value = [{'id': 1, 'name': 'Russia'}]

    tables = await synchronizer.load_tables()

    assert tables == {}
    synchronizer.formatter.load.assert_not_called()
    stderr = capsys.readouterr().err
    assert 'table public.countries is not in the selected table set' in stderr


@pytest.mark.asyncio
async def test_load_tables_loads_file_when_table_in_selection(tmp_path: Path):
    yaml_file = tmp_path / 'public' / 'countries.yaml'
    yaml_file.parent.mkdir(parents=True)
    yaml_file.write_text('- {id: 1, name: Russia}\n')

    synchronizer = _make_synchronizer(str(tmp_path), is_dir=True)
    synchronizer.registry.get.return_value = _sync_table('public', 'countries')
    synchronizer.formatter.load.return_value = [{'id': 1, 'name': 'Russia'}]

    tables = await synchronizer.load_tables()

    assert tables == {('public', 'countries'): [{'id': 1, 'name': 'Russia'}]}


def test_get_diff_directory_mode_uses_only_common_tables(capsys):
    synchronizer = _make_synchronizer('/tmp/refs', is_dir=True)

    src_tables = {
        ('public', 'countries'): [{'id': 1}],
        ('public', 'extra_file'): [{'id': 2}],
    }
    dst_tables = {
        ('public', 'countries'): [{'id': 1}],
        ('public', 'missing_file'): [{'id': 3}],
    }

    synchronizer._warn_tables_without_files(src_tables, dst_tables)
    diff = synchronizer.get_diff(src_tables, dst_tables)

    assert diff == []
    stderr = capsys.readouterr().err
    assert 'table public.missing_file has no yaml file in source directory, skipped' in stderr


def test_get_diff_directory_mode_reports_data_changes_for_common_tables():
    synchronizer = _make_synchronizer('/tmp/refs', is_dir=True)

    src_tables = {('public', 'countries'): [{'id': 1, 'name': 'new'}]}
    dst_tables = {('public', 'countries'): [{'id': 1, 'name': 'old'}]}

    diff = synchronizer.get_diff(src_tables, dst_tables)

    assert diff == [
        (('public', 'countries'), [{'id': 1, 'name': 'new'}], [{'id': 1, 'name': 'old'}]),
    ]


def test_get_diff_single_file_mode_ignores_tables_without_source_file():
    synchronizer = _make_synchronizer('/tmp/refs/public/countries.yaml', is_dir=False)

    src_tables = {('public', 'countries'): [{'id': 1, 'name': 'new'}]}
    dst_tables = {
        ('public', 'countries'): [{'id': 1, 'name': 'old'}],
        ('public', 'other'): [{'id': 2}],
    }

    diff = synchronizer.get_diff(src_tables, dst_tables)

    assert diff == [
        (('public', 'countries'), [{'id': 1, 'name': 'new'}], [{'id': 1, 'name': 'old'}]),
    ]
