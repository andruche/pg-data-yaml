from __future__ import annotations

import argparse
import glob
import os
import sys

from .extractor import Extractor
from .formatter import Formatter
from .pg import Pg, quote_ident, quote_literal
from .registry import SyncTable, TableRegistry
from .str_diff import color_str_diff
from .values import ordered_row, pk_key, rows_equal


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
        diff = self.get_diff(src_tables, dst_tables)
        if not diff:
            print('Nothing to do: all tables are up to date')
            return
        self.print_diff(diff)
        if show_diff_only:
            return
        if self.args.yes or self.confirm(len(diff)):
            await self.apply_changes(diff)

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

    async def apply_changes(self, diff):
        for table_key, src_rows, dst_rows in diff:
            schema, table = table_key
            sync_table = await self.registry.get(schema, table)
            if not sync_table:
                print(
                    f'ERROR: table {schema}.{table} is not in the selected table set',
                    file=sys.stderr,
                )
                sys.exit(1)

            queries = [f'-- table: {schema}.{table}']
            queries.extend(
                self.get_apply_queries(sync_table, src_rows or [], dst_rows or [])
            )
            query = '\n'.join(query for query in queries if query)
            wrapped_query = self._wrap_sync_query(query)
            self.print_query(wrapped_query)
            if not self.args.dry_run:
                await self.pg.execute(wrapped_query)

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
        print(f'\033[33mQUERY{executed}: {query}\033[0m\n')

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
