from __future__ import annotations

import argparse
import os

from .formatter import Formatter
from .pg import Pg
from .registry import SyncTable, TableRegistry
from .values import ordered_row


class Extractor:
    ROWS_LIMIT = 50000

    def __init__(self, args: argparse.Namespace, pg: Pg):
        self.args = args
        self.pg = pg
        self.registry = TableRegistry.from_args(pg, args)
        self.formatter = Formatter()

    async def export(self) -> None:
        tables = await self.registry.load()
        for sync_table in tables.values():
            rows_count = await self.get_rows_count(sync_table)
            if rows_count == self.ROWS_LIMIT:
                print(f'Table {sync_table.table} has {rows_count} rows, skipping')
                continue
            rows = await self.fetch_rows(sync_table)
            file_name = sync_table.file_path(self.args.out_dir)
            os.makedirs(os.path.dirname(file_name), exist_ok=True)
            self.formatter.dump(rows, file_name)

    async def fetch_rows(self, sync_table: SyncTable) -> list[dict]:
        rows = await self.pg.fetch(sync_table.select_query())
        return [ordered_row(row) for row in rows]

    async def get_rows_count(self, sync_table: SyncTable) -> list[dict]:
        query = sync_table.select_query()
        query = f'select count(*) from ({query} limit {self.ROWS_LIMIT}) as t'
        rows = await self.pg.fetch(query)
        return rows[0]['count']

    async def get_tables_data(self) -> dict[tuple[str, str], list[dict]]:
        tables = await self.registry.load()
        return {
            key: await self.fetch_rows(sync_table)
            for key, sync_table in tables.items()
        }
