from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

from .pg import Pg, quote_ident
from .sync_comment import parse_table_comment


@dataclass(frozen=True)
class SyncTable:
    schema: str
    table: str
    custom_select: str | None
    where_filter: str | None
    pk_columns: list[str]

    @property
    def qualified_name(self) -> str:
        return f'{self.schema}.{self.table}'

    def select_query(self) -> str:
        pk_order = ', '.join(quote_ident(column) for column in self.pk_columns)
        table = f'{quote_ident(self.schema)}.{quote_ident(self.table)}'
        if self.custom_select:
            return self.custom_select
        if self.where_filter:
            return f'select * from {table} where {self.where_filter} order by {pk_order}'
        return f'select * from {table} order by {pk_order}'

    def file_path(self, base_dir: str) -> str:
        return os.path.join(base_dir, self.schema, f'{self.table}.yaml')

    @property
    def rel_path(self) -> str:
        return f'{self.schema}/{self.table}.yaml'

    @classmethod
    def from_file_path(cls, path: str) -> 'SyncTable':
        table = os.path.splitext(os.path.basename(path))[0]
        schema = os.path.basename(os.path.dirname(path))
        if not schema or schema == '.' or not table:
            raise ValueError(f'invalid table file path: {path}')
        return cls(
            schema=schema,
            table=table,
            custom_select=None,
            where_filter=None,
            pk_columns=[],
        )


class TableRegistry:
    def __init__(
        self,
        pg: Pg,
        *,
        comment_label: str | None = None,
        table_list_predicate: str | None = None,
    ):
        if comment_label is not None and table_list_predicate is not None:
            raise ValueError(
                'comment_label and table_list_predicate are mutually exclusive'
            )
        if comment_label is None and table_list_predicate is None:
            raise ValueError(
                'either comment_label or table_list_predicate is required'
            )
        self.pg = pg
        self.comment_label = comment_label
        self.table_list_predicate = table_list_predicate
        self._tables: dict[tuple[str, str], SyncTable] = {}

    @classmethod
    def from_args(cls, pg: Pg, args: argparse.Namespace) -> 'TableRegistry':
        return cls(
            pg,
            comment_label=getattr(args, 'comment_label', None),
            table_list_predicate=getattr(args, 'table_list_predicate', None),
        )

    def _build_table_filter(self) -> tuple[str, list]:
        base = """
            c.relkind = 'r'
            and n.nspname not in ('pg_catalog', 'information_schema')
        """.strip()

        if self.table_list_predicate is not None:
            return f'{base} and ({self.table_list_predicate})', []

        return (
            f"{base} and pg_catalog.obj_description(c.oid, 'pg_class') ilike $1",
            [f'%{self.comment_label}%'],
        )

    def _parse_row_comment(self, comment: str | None):
        if self.table_list_predicate is not None:
            return None
        return parse_table_comment(comment, self.comment_label)

    async def load(self) -> dict[tuple[str, str], SyncTable]:
        filter_sql, params = self._build_table_filter()
        rows = await self.pg.fetch(f'''
            select n.nspname as schema_name,
                   c.relname as table_name,
                   pg_catalog.obj_description(c.oid, 'pg_class') as comment
              from pg_catalog.pg_class c
              join pg_catalog.pg_namespace n on n.oid = c.relnamespace
             where {filter_sql}
             order by n.nspname, c.relname
        ''', *params)

        tables = {}
        for row in rows:
            schema = row['schema_name']
            table = row['table_name']
            parsed = self._parse_row_comment(row['comment'])
            pk_columns = await self._get_pk_columns(schema, table)
            if not pk_columns:
                print(
                    f'WARNING: table {schema}.{table} has no primary key, skipped',
                    file=sys.stderr,
                )
                continue

            sync_table = SyncTable(
                schema=schema,
                table=table,
                custom_select=parsed.custom_select if parsed else None,
                where_filter=parsed.where_filter if parsed else None,
                pk_columns=pk_columns,
            )
            tables[(schema, table)] = sync_table

        self._tables = tables
        return tables

    async def get(self, schema: str, table: str) -> SyncTable | None:
        if not self._tables:
            await self.load()
        return self._tables.get((schema, table))

    async def _get_pk_columns(self, schema: str, table: str) -> list[str]:
        rows = await self.pg.fetch('''
            select kcu.column_name
              from information_schema.table_constraints tc
              join information_schema.key_column_usage kcu
                on tc.constraint_name = kcu.constraint_name
               and tc.table_schema = kcu.table_schema
               and tc.table_name = kcu.table_name
             where tc.constraint_type = 'PRIMARY KEY'
               and tc.table_schema = $1
               and tc.table_name = $2
             order by kcu.ordinal_position
        ''', schema, table)
        return [row['column_name'] for row in rows]
