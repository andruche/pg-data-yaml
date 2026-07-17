from __future__ import annotations

import asyncio
import datetime
import decimal
import json
import signal
import uuid

import asyncpg


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def quote_literal(value):
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return quote_literal(str(value))
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return quote_literal(value.isoformat())
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, (dict, list)):
        return quote_literal(json.dumps(value))
    if isinstance(value, (bytes, memoryview)):
        return quote_literal(bytes(value).hex())
    raise TypeError(f'Unknown type for quote value: {value!r}')


class Pg:
    con: asyncpg.Connection

    def __init__(self, args):
        self.args = args
        self.con = None

    async def init(self):
        self.con = await asyncpg.connect(
            database=self.args.dbname,
            user=self.args.user,
            password=self.args.password,
            host=self.args.host,
            port=self.args.port,
            statement_cache_size=0,
        )

    async def fetch(self, query: str, *params) -> list[dict]:
        return await self._run_with_signal_handler(self._fetch(query, *params))

    async def _fetch(self, query: str, *params) -> list[dict]:
        rows = await self.con.fetch(query, *params)
        return [{key: row[key] for key in row.keys()} for row in rows]

    async def execute(self, query: str, *params) -> None:
        await self._run_with_signal_handler(self._execute(query, *params))

    async def _execute(self, query: str, *params) -> None:
        await self.con.execute(query, *params)

    async def close(self) -> None:
        if self.con is not None and not self.con.is_closed():
            await self.con.close()

    async def _run_with_signal_handler(self, coro):
        query_task = asyncio.create_task(coro)
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, query_task.cancel)
        try:
            return await query_task
        finally:
            loop.remove_signal_handler(signal.SIGINT)
