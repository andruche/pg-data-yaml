from __future__ import annotations

import argparse
import glob
import os
import sys
import traceback

import asyncpg

from .extractor import Extractor
from .formatter import Formatter
from .pg import Pg, quote_ident, quote_literal
from .registry import SyncTable, TableRegistry
from .str_diff import color_str_diff
from .values import ordered_row, pk_key, rows_equal


def _format_apply_error(exc: BaseException) -> str:
    if isinstance(exc, asyncpg.PostgresError):
        return str(exc)
    return traceback.format_exc()


class Synchronizer:
    def __init__(self, args: argparse.Namespace, pg: Pg):
        self.args = args
        self.pg = pg
        self.extractor = Extractor(args, pg)
        self.registry = TableRegistry.from_args(pg, args)
        self.formatter = Formatter()
        self.is_dir = os.path.isdir(self.args.source)

    async def sync(self, show_diff_only=False):
        await self.registry.load()
        src_tables = await self.load_tables()
        dst_tables = await self.extractor.get_tables_data()
        if self.is_dir:
            self._warn_tables_without_files(src_tables, dst_tables)

        if show_diff_only:
            diff = self.get_diff(src_tables, dst_tables)
            if not diff:
                print('Nothing to do: all tables are up to date')
                return
            self.print_diff(diff)
            return

        await self.validate_sync_row_attributes(src_tables, dst_tables)
        changes = await self.collect_sync_changes(src_tables, dst_tables)
        if not changes:
            print('Nothing to do: all tables are up to date')
            return
        if self.args.quiet < 1:
            diff = await self.build_sync_diff(changes, src_tables, dst_tables)
            self.print_diff(diff)
        if self.args.yes or self.confirm(len(changes)):
            await self.apply_changes(changes)

    async def load_tables(self) -> dict[tuple[str, str], list[dict]]:
        tables = {}
        for file_name in self._source_files():
            try:
                file_table = SyncTable.from_file_path(file_name)
            except ValueError as exc:
                print(f'WARNING: {exc}, skipped', file=sys.stderr)
                continue

            sync_table = await self.registry.get(file_table.schema, file_table.table)
            if sync_table is None:
                print(
                    f'WARNING: table {file_table.schema}.{file_table.table} '
                    f'is not in the selected table set, skipped file {file_name}',
                    file=sys.stderr,
                )
                continue

            data = self.formatter.load(file_name)
            if data is None:
                data = []
            if not isinstance(data, list):
                print(
                    f'ERROR: file {file_name} must contain a yaml list of rows',
                    file=sys.stderr,
                )
                sys.exit(1)

            sync_table = await self.registry.get(file_table.schema, file_table.table)
            rows = []
            seen_pk = set()
            for index, row in enumerate(data, start=1):
                if not isinstance(row, dict):
                    print(
                        f'ERROR: row #{index} in {file_name} must be a mapping',
                        file=sys.stderr,
                    )
                    sys.exit(1)
                row = ordered_row(row)
                missing_pk = [
                    column
                    for column in sync_table.pk_columns
                    if column not in row
                ]
                if missing_pk:
                    print(
                        f'ERROR: row #{index} in {file_name} '
                        f'missing primary key columns: {", ".join(missing_pk)}',
                        file=sys.stderr,
                    )
                    sys.exit(1)
                key = pk_key(row, sync_table.pk_columns)
                if key in seen_pk:
                    print(
                        f'ERROR: duplicate primary key {key!r} in {file_name}',
                        file=sys.stderr,
                    )
                    sys.exit(1)
                seen_pk.add(key)
                rows.append(row)

            key = (file_table.schema, file_table.table)
            if key in tables:
                print(
                    f'ERROR: duplicate table file for {file_table.rel_path}',
                    file=sys.stderr,
                )
                sys.exit(1)
            tables[key] = rows
        return tables

    def _source_files(self) -> list[str]:
        if self.is_dir:
            return sorted(glob.glob(os.path.join(self.args.source, '*', '*.yaml')))
        return [self.args.source]

    def _warn_tables_without_files(self, src_tables, dst_tables):
        for schema, table in sorted(set(dst_tables.keys()) - set(src_tables.keys())):
            print(
                f'WARNING: table {schema}.{table} has no yaml file in source directory, skipped',
                file=sys.stderr,
            )

    def get_diff(self, src_tables, dst_tables):
        if self.is_dir:
            table_keys = set(src_tables.keys()) & set(dst_tables.keys())
        else:
            table_keys = set(src_tables.keys())

        res = []
        for table_key in sorted(table_keys):
            src_rows = src_tables.get(table_key)
            dst_rows = dst_tables.get(table_key)
            if src_rows == dst_rows:
                continue
            res.append((table_key, src_rows, dst_rows))
        return res

    async def validate_sync_row_attributes(self, src_tables, dst_tables):
        if self.is_dir:
            table_keys = set(src_tables.keys()) & set(dst_tables.keys())
        else:
            table_keys = set(src_tables.keys())

        for table_key in sorted(table_keys):
            schema, table = table_key
            sync_table = await self.registry.get(schema, table)
            if not sync_table:
                print(
                    f'ERROR: table {schema}.{table} is not in the selected table set',
                    file=sys.stderr,
                )
                sys.exit(1)

            src_rows = src_tables.get(table_key) or []
            dst_rows = dst_tables.get(table_key) or []
            mismatches = self._find_row_attribute_mismatches(
                sync_table,
                src_rows,
                dst_rows,
            )
            if not mismatches:
                continue

            print(
                f'ERROR: table {schema}.{table} row attribute mismatch',
                file=sys.stderr,
            )
            for message in mismatches[:2]:
                print(message, file=sys.stderr)
            if len(mismatches) > 2:
                print(
                    f'ERROR: ... and {len(mismatches) - 2} more mismatched rows',
                    file=sys.stderr,
                )
            sys.exit(1)

    @staticmethod
    def _find_row_attribute_mismatches(
        sync_table: SyncTable,
        src_rows: list[dict],
        dst_rows: list[dict],
    ) -> list[str]:
        pk_columns = sync_table.pk_columns
        src_by_pk = {
            pk_key(row, pk_columns): (index, row)
            for index, row in enumerate(src_rows, start=1)
        }
        dst_by_pk = {
            pk_key(row, pk_columns): (index, row)
            for index, row in enumerate(dst_rows, start=1)
        }
        src_union = set().union(*(row.keys() for row in src_rows), set())
        dst_union = set().union(*(row.keys() for row in dst_rows), set())

        mismatches = []
        for pk in sorted(set(src_by_pk) & set(dst_by_pk)):
            src_index, src_row = src_by_pk[pk]
            dst_index, dst_row = dst_by_pk[pk]
            src_keys = set(src_row.keys())
            dst_keys = set(dst_row.keys())
            if src_keys == dst_keys:
                continue
            mismatches.append(
                f'file row #{src_index} and database row #{dst_index} '
                f'(primary key {pk!r}): file columns {sorted(src_keys)}, '
                f'database columns {sorted(dst_keys)}'
            )

        for pk, (src_index, src_row) in sorted(src_by_pk.items()):
            if pk in dst_by_pk:
                continue
            src_keys = set(src_row.keys())
            if dst_union and src_keys != dst_union:
                mismatches.append(
                    f'file row #{src_index} (primary key {pk!r}): '
                    f'file columns {sorted(src_keys)}, '
                    f'database columns {sorted(dst_union)}'
                )

        for pk, (dst_index, dst_row) in sorted(dst_by_pk.items()):
            if pk in src_by_pk:
                continue
            dst_keys = set(dst_row.keys())
            if src_union and dst_keys != src_union:
                mismatches.append(
                    f'database row #{dst_index} (primary key {pk!r}): '
                    f'database columns {sorted(dst_keys)}, '
                    f'file columns {sorted(src_union)}'
                )

        return mismatches

    async def collect_sync_changes(self, src_tables, dst_tables):
        if self.is_dir:
            table_keys = set(src_tables.keys()) & set(dst_tables.keys())
        else:
            table_keys = set(src_tables.keys())

        changes = []
        for table_key in sorted(table_keys):
            schema, table = table_key
            sync_table = await self.registry.get(schema, table)
            if not sync_table:
                print(
                    f'ERROR: table {schema}.{table} is not in the selected table set',
                    file=sys.stderr,
                )
                sys.exit(1)

            src_rows = src_tables.get(table_key) or []
            dst_rows = dst_tables.get(table_key) or []
            queries = [
                query
                for query in self.get_apply_queries(sync_table, src_rows, dst_rows)
                if query
            ]
            if queries:
                changes.append((table_key, queries))
        return changes

    async def build_sync_diff(self, changes, src_tables, dst_tables):
        diff = []
        for table_key, _ in changes:
            schema, table = table_key
            sync_table = await self.registry.get(schema, table)
            src_rows = src_tables.get(table_key) or []
            dst_rows = dst_tables.get(table_key) or []
            filtered_src, filtered_dst = self._filter_changed_rows(
                sync_table,
                src_rows,
                dst_rows,
            )
            diff.append((table_key, filtered_src, filtered_dst))
        return diff

    @staticmethod
    def _filter_changed_rows(
        sync_table: SyncTable,
        src_rows: list[dict],
        dst_rows: list[dict],
    ) -> tuple[list[dict], list[dict]]:
        pk_columns = sync_table.pk_columns
        src_by_pk = {pk_key(row, pk_columns): row for row in src_rows}
        dst_by_pk = {pk_key(row, pk_columns): row for row in dst_rows}

        filtered_src = []
        filtered_dst = []
        for pk in sorted(set(src_by_pk) | set(dst_by_pk)):
            src_row = src_by_pk.get(pk)
            dst_row = dst_by_pk.get(pk)
            if src_row is None:
                filtered_dst.append(dst_row)
            elif dst_row is None:
                filtered_src.append(src_row)
            elif not rows_equal(src_row, dst_row):
                filtered_dst.append(dst_row)
                filtered_src.append(src_row)
        return filtered_src, filtered_dst

    def print_diff(self, diff):
        for table_key, src_rows, dst_rows in diff:
            schema, table = table_key
            header = f'--- {schema}/{table}.yaml'
            print(header)
            print(
                color_str_diff(
                    self.formatter.dump(dst_rows if dst_rows is not None else None),
                    self.formatter.dump(src_rows if src_rows is not None else None),
                )
            )

    @staticmethod
    def confirm(changed_tables_count):
        result = input(
            f'Are you sure you want to change {changed_tables_count} tables? (y/n): '
        )
        return result == 'y'

    async def apply_changes(self, changes):
        show_progress = not self.args.echo_queries and self.args.quiet < 2
        had_errors = False
        for table_key, queries in changes:
            schema, table = table_key
            table_name = f'{schema}.{table}'
            if show_progress:
                print(f'{table_name}...', end='', flush=True)
            query = '\n'.join(queries)
            wrapped_query = self._wrap_sync_query(query)
            self.print_query(wrapped_query)
            if not self.args.dry_run:
                try:
                    await self.pg.execute(wrapped_query)
                except Exception as exc:
                    had_errors = True
                    error_text = _format_apply_error(exc)
                    if show_progress:
                        print(f' ERROR: {error_text.rstrip()}')
                    elif self.args.skip_error:
                        print(f'{table_name}... ERROR: {error_text.rstrip()}')
                    else:
                        raise
                    if not self.args.skip_error:
                        sys.exit(1)
                    await self.pg.rollback()
                    continue
            if show_progress:
                print(' ok')
        if had_errors:
            sys.exit(1)

    def _wrap_sync_query(self, query: str) -> str:
        lines = ['begin;']
        role = self.args.session_replication_role
        if role:
            lines.append(f'set local session_replication_role = {quote_literal(role)};')
        lines.extend([query, 'commit;'])
        return '\n'.join(lines)

    def print_query(self, query):
        if not self.args.echo_queries:
            return
        executed = ' (not executed)' if self.args.dry_run else ''
        text = f'--QUERY{executed}:\n{query}'
        if sys.stdout.isatty():
            text = f'\033[33m{text}\033[0m'
        print(f'{text}\n')

    def get_apply_queries(self, sync_table: SyncTable, src_rows: list[dict], dst_rows: list[dict]):
        src_by_pk = {pk_key(row, sync_table.pk_columns): row for row in src_rows}
        dst_by_pk = {pk_key(row, sync_table.pk_columns): row for row in dst_rows}

        for pk in src_by_pk:
            if pk not in dst_by_pk:
                continue
            if not all(column in src_by_pk[pk] for column in sync_table.pk_columns):
                raise ValueError(
                    f'missing primary key columns in source row for {sync_table.qualified_name}'
                )

        table = f'{quote_ident(sync_table.schema)}.{quote_ident(sync_table.table)}'
        queries = []

        for pk, dst_row in dst_by_pk.items():
            if pk not in src_by_pk:
                queries.append(self._delete_query(table, sync_table.pk_columns, dst_row))

        for pk, src_row in src_by_pk.items():
            dst_row = dst_by_pk.get(pk)
            if dst_row is None:
                queries.append(self._insert_query(table, src_row))
            elif not rows_equal(src_row, dst_row):
                queries.append(
                    self._update_query(table, sync_table.pk_columns, src_row, dst_row)
                )

        return queries

    def _insert_query(self, table: str, row: dict) -> str:
        columns = ', '.join(quote_ident(column) for column in row)
        values = ', '.join(quote_literal(value) for value in row.values())
        return f'insert into {table}({columns}) values ({values});'

    def _update_query(
        self,
        table: str,
        pk_columns: list[str],
        src_row: dict,
        dst_row: dict,
    ) -> str:
        pk_set = set(pk_columns)
        changes = {
            column: value
            for column, value in src_row.items()
            if column not in pk_set and value != dst_row.get(column)
        }
        if not changes:
            return ''
        values = ', '.join(
            f'{quote_ident(column)} = {quote_literal(value)}'
            for column, value in changes.items()
        )
        where = ' and '.join(
            f'{quote_ident(column)} = {quote_literal(src_row[column])}'
            for column in pk_columns
        )
        return f'update {table} set {values} where {where};'

    def _delete_query(self, table: str, pk_columns: list[str], row: dict) -> str:
        where = ' and '.join(
            f'{quote_ident(column)} = {quote_literal(row[column])}'
            for column in pk_columns
        )
        return f'delete from {table} where {where};'
