from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
        session_replication_role=None,
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


def test_wrap_sync_query_adds_local_session_replication_role():
    synchronizer = _make_synchronizer('/tmp/refs', is_dir=True)
    synchronizer.args.session_replication_role = 'replica'

    wrapped = synchronizer._wrap_sync_query(
        'delete from public.countries where id = 1;'
    )

    assert wrapped == (
        "begin;\n"
        "set local session_replication_role = 'replica';\n"
        "delete from public.countries where id = 1;\n"
        "commit;"
    )


def test_wrap_sync_query_without_role_wraps_in_transaction():
    synchronizer = _make_synchronizer('/tmp/refs', is_dir=True)

    query = 'delete from public.countries where id = 1;'
    assert synchronizer._wrap_sync_query(query) == '\n'.join([
        'begin;',
        query,
        'commit;',
    ])


@pytest.mark.asyncio
async def test_collect_sync_changes_ignores_row_order_only_difference():
    synchronizer = _make_synchronizer('/tmp/refs', is_dir=True)
    synchronizer.registry.get.return_value = _sync_table('public', 'countries')

    src_tables = {
        ('public', 'countries'): [
            {'id': 2, 'name': 'beta'},
            {'id': 1, 'name': 'alpha'},
        ],
    }
    dst_tables = {
        ('public', 'countries'): [
            {'id': 1, 'name': 'alpha'},
            {'id': 2, 'name': 'beta'},
        ],
    }

    changes = await synchronizer.collect_sync_changes(src_tables, dst_tables)

    assert changes == []


def test_get_diff_shows_row_order_difference():
    synchronizer = _make_synchronizer('/tmp/refs', is_dir=True)

    src_tables = {
        ('public', 'countries'): [
            {'id': 2, 'name': 'beta'},
            {'id': 1, 'name': 'alpha'},
        ],
    }
    dst_tables = {
        ('public', 'countries'): [
            {'id': 1, 'name': 'alpha'},
            {'id': 2, 'name': 'beta'},
        ],
    }

    diff = synchronizer.get_diff(src_tables, dst_tables)

    assert diff == [
        (
            ('public', 'countries'),
            [{'id': 2, 'name': 'beta'}, {'id': 1, 'name': 'alpha'}],
            [{'id': 1, 'name': 'alpha'}, {'id': 2, 'name': 'beta'}],
        ),
    ]


def test_find_row_attribute_mismatches_for_matching_primary_keys():
    synchronizer = _make_synchronizer('/tmp/refs', is_dir=True)
    sync_table = _sync_table('public', 'countries')

    mismatches = synchronizer._find_row_attribute_mismatches(
        sync_table,
        [{'id': 1, 'name': 'alpha', 'code': 'ru'}],
        [{'id': 1, 'name': 'alpha'}],
    )

    assert mismatches == [
        "file row #1 and database row #1 (primary key (1,)): "
        "file columns ['code', 'id', 'name'], database columns ['id', 'name']",
    ]


def test_find_row_attribute_mismatches_for_insert_row_with_extra_columns():
    synchronizer = _make_synchronizer('/tmp/refs', is_dir=True)
    sync_table = _sync_table('public', 'countries')

    mismatches = synchronizer._find_row_attribute_mismatches(
        sync_table,
        [
            {'id': 1, 'name': 'alpha'},
            {'id': 2, 'name': 'beta', 'code': 'de'},
        ],
        [{'id': 1, 'name': 'alpha'}],
    )

    assert mismatches == [
        "file row #2 (primary key (2,)): "
        "file columns ['code', 'id', 'name'], database columns ['id', 'name']",
    ]


def test_filter_changed_rows_omits_identical_rows():
    synchronizer = _make_synchronizer('/tmp/refs', is_dir=True)
    sync_table = _sync_table('public', 'countries')

    filtered_src, filtered_dst = synchronizer._filter_changed_rows(
        sync_table,
        [
            {'id': 1, 'name': 'alpha'},
            {'id': 2, 'name': 'beta'},
        ],
        [
            {'id': 1, 'name': 'alpha'},
            {'id': 2, 'name': 'changed'},
        ],
    )

    assert filtered_src == [{'id': 2, 'name': 'beta'}]
    assert filtered_dst == [{'id': 2, 'name': 'changed'}]


def test_filter_changed_rows_includes_insert_and_delete():
    synchronizer = _make_synchronizer('/tmp/refs', is_dir=True)
    sync_table = _sync_table('public', 'countries')

    filtered_src, filtered_dst = synchronizer._filter_changed_rows(
        sync_table,
        [{'id': 1, 'name': 'alpha'}, {'id': 3, 'name': 'new'}],
        [{'id': 1, 'name': 'alpha'}, {'id': 2, 'name': 'old'}],
    )

    assert filtered_src == [{'id': 3, 'name': 'new'}]
    assert filtered_dst == [{'id': 2, 'name': 'old'}]


@pytest.mark.asyncio
async def test_sync_exits_on_row_attribute_mismatch(capsys):
    synchronizer = _make_synchronizer('/tmp/refs', is_dir=True)
    synchronizer.args.yes = True
    synchronizer.registry.load = AsyncMock()
    synchronizer.load_tables = AsyncMock(return_value={
        ('public', 'countries'): [{'id': 1, 'name': 'alpha', 'code': 'ru'}],
    })
    synchronizer.extractor.get_tables_data = AsyncMock(return_value={
        ('public', 'countries'): [{'id': 1, 'name': 'alpha'}],
    })
    synchronizer.registry.get = AsyncMock(return_value=_sync_table('public', 'countries'))
    synchronizer.apply_changes = AsyncMock()

    with pytest.raises(SystemExit) as exc_info:
        await synchronizer.sync(show_diff_only=False)

    assert exc_info.value.code == 1
    stderr = capsys.readouterr().err
    assert 'table public.countries row attribute mismatch' in stderr
    assert 'file row #1 and database row #1' in stderr


@pytest.mark.asyncio
async def test_sync_prints_diff_for_tables_with_commands():
    synchronizer = _make_synchronizer('/tmp/refs', is_dir=True)
    synchronizer.args.yes = True
    synchronizer.registry.load = AsyncMock()
    synchronizer.load_tables = AsyncMock(return_value={
        ('public', 'countries'): [{'id': 1, 'name': 'new'}],
    })
    synchronizer.extractor.get_tables_data = AsyncMock(return_value={
        ('public', 'countries'): [{'id': 1, 'name': 'old'}],
    })
    synchronizer.registry.get = AsyncMock(return_value=_sync_table('public', 'countries'))
    synchronizer.print_diff = MagicMock()
    synchronizer.apply_changes = AsyncMock()

    await synchronizer.sync(show_diff_only=False)

    synchronizer.print_diff.assert_called_once_with([
        (
            ('public', 'countries'),
            [{'id': 1, 'name': 'new'}],
            [{'id': 1, 'name': 'old'}],
        ),
    ])
    synchronizer.apply_changes.assert_awaited_once()


@pytest.mark.asyncio
async def test_sync_prints_only_changed_rows_in_diff():
    synchronizer = _make_synchronizer('/tmp/refs', is_dir=True)
    synchronizer.args.yes = True
    synchronizer.registry.load = AsyncMock()
    synchronizer.load_tables = AsyncMock(return_value={
        ('public', 'countries'): [
            {'id': 1, 'name': 'same'},
            {'id': 2, 'name': 'new'},
        ],
    })
    synchronizer.extractor.get_tables_data = AsyncMock(return_value={
        ('public', 'countries'): [
            {'id': 1, 'name': 'same'},
            {'id': 2, 'name': 'old'},
        ],
    })
    synchronizer.registry.get = AsyncMock(return_value=_sync_table('public', 'countries'))
    synchronizer.print_diff = MagicMock()
    synchronizer.apply_changes = AsyncMock()

    await synchronizer.sync(show_diff_only=False)

    synchronizer.print_diff.assert_called_once_with([
        (
            ('public', 'countries'),
            [{'id': 2, 'name': 'new'}],
            [{'id': 2, 'name': 'old'}],
        ),
    ])


@pytest.mark.asyncio
async def test_sync_skips_diff_when_only_row_order_differs():
    synchronizer = _make_synchronizer('/tmp/refs', is_dir=True)
    synchronizer.args.yes = True
    synchronizer.registry.load = AsyncMock()
    synchronizer.load_tables = AsyncMock(return_value={
        ('public', 'countries'): [
            {'id': 2, 'name': 'beta'},
            {'id': 1, 'name': 'alpha'},
        ],
    })
    synchronizer.extractor.get_tables_data = AsyncMock(return_value={
        ('public', 'countries'): [
            {'id': 1, 'name': 'alpha'},
            {'id': 2, 'name': 'beta'},
        ],
    })
    synchronizer.registry.get = AsyncMock(return_value=_sync_table('public', 'countries'))
    synchronizer.print_diff = MagicMock()
    synchronizer.apply_changes = AsyncMock()

    await synchronizer.sync(show_diff_only=False)

    synchronizer.print_diff.assert_not_called()
    synchronizer.apply_changes.assert_not_called()


@pytest.mark.asyncio
async def test_apply_changes_executes_wrapped_query_in_transaction():
    synchronizer = _make_synchronizer('/tmp/refs', is_dir=True)
    synchronizer.args.dry_run = False
    synchronizer.args.echo_queries = False
    synchronizer.pg.execute = AsyncMock()

    await synchronizer.apply_changes([
        (('public', 'countries'), ['delete from "public"."countries" where "id" = 1;']),
    ])

    synchronizer.pg.execute.assert_awaited_once_with(
        'begin;\n'
        'delete from "public"."countries" where "id" = 1;\n'
        'commit;'
    )


@pytest.mark.asyncio
async def test_apply_changes_executes_wrapped_query_with_session_replication_role():
    synchronizer = _make_synchronizer('/tmp/refs', is_dir=True)
    synchronizer.args.session_replication_role = 'replica'
    synchronizer.args.dry_run = False
    synchronizer.args.echo_queries = False
    synchronizer.pg.execute = AsyncMock()

    await synchronizer.apply_changes([
        (('public', 'countries'), ['delete from "public"."countries" where "id" = 1;']),
    ])

    synchronizer.pg.execute.assert_awaited_once_with(
        'begin;\n'
        "set local session_replication_role = 'replica';\n"
        'delete from "public"."countries" where "id" = 1;\n'
        'commit;'
    )


def test_print_query_formats_multiline_output_with_color_on_tty(capsys):
    synchronizer = _make_synchronizer('/tmp/refs', is_dir=True)
    synchronizer.args.echo_queries = True
    synchronizer.args.dry_run = True

    with patch('pg_data_yaml.synchronizer.sys.stdout.isatty', return_value=True):
        synchronizer.print_query(
            "begin;\n"
            "set local session_replication_role = 'replica';\n"
            'delete from "public"."a" where "id" = 1;\n'
            'commit;'
        )

    assert capsys.readouterr().out == (
        '\033[33m--QUERY (not executed):\n'
        "begin;\n"
        "set local session_replication_role = 'replica';\n"
        'delete from "public"."a" where "id" = 1;\n'
        'commit;\033[0m\n'
        '\n'
    )


def test_print_query_formats_multiline_output_without_color_when_not_tty(capsys):
    synchronizer = _make_synchronizer('/tmp/refs', is_dir=True)
    synchronizer.args.echo_queries = True
    synchronizer.args.dry_run = True

    with patch('pg_data_yaml.synchronizer.sys.stdout.isatty', return_value=False):
        synchronizer.print_query(
            "begin;\n"
            'delete from "public"."a" where "id" = 1;\n'
            'commit;'
        )

    assert capsys.readouterr().out == (
        '--QUERY (not executed):\n'
        'begin;\n'
        'delete from "public"."a" where "id" = 1;\n'
        'commit;\n'
        '\n'
    )


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
