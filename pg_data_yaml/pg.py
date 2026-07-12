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
        query_task = asyncio.create_task(self.con.fetch(query, *params))
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, query_task.cancel)
        try:
            rows = await query_task
            return [{key: row[key] for key in row.keys()} for row in rows]
        except asyncio.CancelledError:
            await asyncio.sleep(0.5)
            return []
        finally:
            loop.remove_signal_handler(signal.SIGINT)

    async def execute(self, query: str, *params) -> None:
        query_task = asyncio.create_task(self.con.execute(query, *params))
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, query_task.cancel)
        try:
            await query_task
        except asyncio.CancelledError:
            await asyncio.sleep(0.5)
        finally:
            loop.remove_signal_handler(signal.SIGINT)
