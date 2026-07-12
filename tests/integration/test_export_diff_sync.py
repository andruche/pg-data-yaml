"""Integration tests for export, diff and sync CLI commands.

Run against a local PostgreSQL instance:

    pip install -e . pytest
    pytest tests/integration -v

Connection defaults: postgres:123456@127.0.0.1:5432/postgres
Override with DD_TEST_DB_* environment variables.
"""

from __future__ import annotations

import pytest

from tests.integration.helpers import (
    COMMENT_LABEL,
    SCHEMA,
    TABLE_LIST_PREDICATE,
    IntegrationContext,
    db_fetch,
    db_fetchval,
    dump_yaml,
    load_yaml,
    run_pg_data_yaml,
)

pytestmark = pytest.mark.integration


def test_01_export_comment_label(ctx: IntegrationContext):
    result = run_pg_data_yaml(
        'export',
        '--comment-label', COMMENT_LABEL,
        '--out-dir', str(ctx.export_dir),
        '--clean',
    )

    assert result.returncode == 0

    ref_data_path = ctx.table_yaml('ref_data')
    ref_filtered_path = ctx.table_yaml('ref_filtered')
    ref_custom_path = ctx.table_yaml('ref_custom')
    pred_data_path = ctx.table_yaml('pred_data')

    assert ref_data_path.is_file()
    assert ref_filtered_path.is_file()
    assert ref_custom_path.is_file()
    assert not pred_data_path.exists()

    ref_data = load_yaml(ref_data_path)
    assert ref_data == [{
        'id': 1,
        'big_value': 9223372036854775807,
        'text_value': 'hello',
        'num_value': '123.45',
        'date_value': '2024-06-15',
        'ts_value': '2024-06-15T12:30:45',
        'tstz_value': '2024-06-15T09:30:45+00:00',
        'inet_value': '192.168.1.1',
    }]

    ref_filtered = load_yaml(ref_filtered_path)
    assert ref_filtered == [{'id': 1, 'name': 'active row', 'active': True}]

    ref_custom = load_yaml(ref_custom_path)
    assert ref_custom == [{'id': 1, 'name': 'visible'}]
    assert 'hidden' not in ref_custom[0]


def test_02_diff_no_changes(ctx: IntegrationContext):
    result = run_pg_data_yaml(
        'diff',
        '--comment-label', COMMENT_LABEL,
        '--source', str(ctx.export_dir),
        check=False,
    )

    assert result.returncode == 0
    assert 'Nothing to do: all tables are up to date' in result.stdout


def test_03_diff_with_changes(ctx: IntegrationContext):
    ref_data_path = ctx.table_yaml('ref_data')
    rows = load_yaml(ref_data_path)
    rows[0]['text_value'] = 'changed in yaml'
    dump_yaml(ref_data_path, rows)

    result = run_pg_data_yaml(
        'diff',
        '--comment-label', COMMENT_LABEL,
        '--source', str(ctx.export_dir),
        check=False,
    )

    assert result.returncode == 0
    assert f'--- {SCHEMA}/ref_data.yaml' in result.stdout
    assert 'Nothing to do: all tables are up to date' not in result.stdout


def test_04_sync_apply_changes(ctx: IntegrationContext):
    result = run_pg_data_yaml(
        'sync',
        '--comment-label', COMMENT_LABEL,
        '--source', str(ctx.export_dir),
        '-y',
    )

    assert result.returncode == 0

    text_value = db_fetchval(
        f'SELECT text_value FROM {SCHEMA}.ref_data WHERE id = 1'
    )
    assert text_value == 'changed in yaml'


def test_05_sync_yaml_into_empty_table(ctx: IntegrationContext):
    empty_yaml = ctx.table_yaml('ref_empty')
    dump_yaml(empty_yaml, [
        {'id': 10, 'name': 'loaded by sync'},
        {'id': 11, 'name': 'also loaded'},
    ])

    result = run_pg_data_yaml(
        'sync',
        '--comment-label', COMMENT_LABEL,
        '--source', str(empty_yaml),
        '-y',
    )

    assert result.returncode == 0

    rows = db_fetch(
        f'SELECT id, name FROM {SCHEMA}.ref_empty ORDER BY id'
    )
    assert rows == [
        {'id': 10, 'name': 'loaded by sync'},
        {'id': 11, 'name': 'also loaded'},
    ]


def test_06_export_after_sync_to_empty_table(ctx: IntegrationContext):
    result = run_pg_data_yaml(
        'export',
        '--comment-label', COMMENT_LABEL,
        '--out-dir', str(ctx.export_dir),
        '--clean',
    )

    assert result.returncode == 0

    exported = load_yaml(ctx.table_yaml('ref_empty'))
    assert exported == [
        {'id': 10, 'name': 'loaded by sync'},
        {'id': 11, 'name': 'also loaded'},
    ]


def test_07_export_table_list_predicate(ctx: IntegrationContext):
    result = run_pg_data_yaml(
        'export',
        '--table-list-predicate', TABLE_LIST_PREDICATE,
        '--out-dir', str(ctx.predicate_export_dir),
        '--clean',
    )

    assert result.returncode == 0

    pred_data_path = ctx.table_yaml('pred_data', ctx.predicate_export_dir)
    ref_data_path = ctx.table_yaml('ref_data', ctx.predicate_export_dir)

    assert pred_data_path.is_file()
    assert not ref_data_path.exists()

    pred_data = load_yaml(pred_data_path)
    assert pred_data == [
        {'id': 1, 'name': 'alpha'},
        {'id': 2, 'name': 'beta'},
    ]


def test_08_diff_and_sync_predicate_table(ctx: IntegrationContext):
    pred_data_path = ctx.table_yaml('pred_data', ctx.predicate_export_dir)
    rows = load_yaml(pred_data_path)
    rows[0]['name'] = 'alpha updated'
    rows.append({'id': 3, 'name': 'gamma'})
    dump_yaml(pred_data_path, rows)

    diff_result = run_pg_data_yaml(
        'diff',
        '--table-list-predicate', TABLE_LIST_PREDICATE,
        '--source', str(ctx.predicate_export_dir),
        check=False,
    )
    assert diff_result.returncode == 0
    assert f'--- {SCHEMA}/pred_data.yaml' in diff_result.stdout

    sync_result = run_pg_data_yaml(
        'sync',
        '--table-list-predicate', TABLE_LIST_PREDICATE,
        '--source', str(ctx.predicate_export_dir),
        '-y',
    )
    assert sync_result.returncode == 0

    db_rows = db_fetch(
        f'SELECT id, name FROM {SCHEMA}.pred_data ORDER BY id'
    )
    assert db_rows == [
        {'id': 1, 'name': 'alpha updated'},
        {'id': 2, 'name': 'beta'},
        {'id': 3, 'name': 'gamma'},
    ]


def test_09_sync_dry_run_does_not_change_database(ctx: IntegrationContext):
    pred_data_path = ctx.table_yaml('pred_data', ctx.predicate_export_dir)
    rows = load_yaml(pred_data_path)
    rows[0]['name'] = 'must not be saved'
    dump_yaml(pred_data_path, rows)

    before = db_fetch(
        f'SELECT id, name FROM {SCHEMA}.pred_data ORDER BY id'
    )

    result = run_pg_data_yaml(
        'sync',
        '--table-list-predicate', TABLE_LIST_PREDICATE,
        '--source', str(ctx.predicate_export_dir),
        '--dry-run',
        '-y',
    )

    assert result.returncode == 0

    after = db_fetch(
        f'SELECT id, name FROM {SCHEMA}.pred_data ORDER BY id'
    )
    assert after == before


def test_10_diff_single_file(ctx: IntegrationContext):
    pred_data_path = ctx.table_yaml('pred_data', ctx.predicate_export_dir)
    rows = load_yaml(pred_data_path)
    rows[1]['name'] = 'beta changed for single-file diff'
    dump_yaml(pred_data_path, rows)

    result = run_pg_data_yaml(
        'diff',
        '--table-list-predicate', TABLE_LIST_PREDICATE,
        '--source', str(pred_data_path),
        check=False,
    )

    assert result.returncode == 0
    assert f'--- {SCHEMA}/pred_data.yaml' in result.stdout


def test_11_sync_single_file(ctx: IntegrationContext):
    pred_data_path = ctx.table_yaml('pred_data', ctx.predicate_export_dir)

    result = run_pg_data_yaml(
        'sync',
        '--table-list-predicate', TABLE_LIST_PREDICATE,
        '--source', str(pred_data_path),
        '-y',
    )

    assert result.returncode == 0

    name = db_fetchval(
        f'SELECT name FROM {SCHEMA}.pred_data WHERE id = 2'
    )
    assert name == 'beta changed for single-file diff'
