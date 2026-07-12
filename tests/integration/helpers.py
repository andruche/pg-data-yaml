from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import asyncpg
import pytest
import yaml

SCHEMA = 'dd_integration'
COMMENT_LABEL = 'synchronized directory'
TABLE_LIST_PREDICATE = f"n.nspname = '{SCHEMA}' and c.relname like 'pred_%'"

DB_CONFIG = {
    'host': os.environ.get('DD_TEST_DB_HOST', '127.0.0.1'),
    'port': int(os.environ.get('DD_TEST_DB_PORT', '5432')),
    'user': os.environ.get('DD_TEST_DB_USER', 'postgres'),
    'password': os.environ.get('DD_TEST_DB_PASSWORD', '123456'),
    'database': os.environ.get('DD_TEST_DB_NAME', 'postgres'),
}


def _run_async(coro):
    return asyncio.run(coro)


async def _with_connection():
    return await asyncpg.connect(**DB_CONFIG)


def db_execute(query: str, *params) -> None:
    async def run():
        conn = await _with_connection()
        try:
            await conn.execute(query, *params)
        finally:
            await conn.close()

    _run_async(run())


def db_fetch(query: str, *params) -> list[dict[str, Any]]:
    async def run():
        conn = await _with_connection()
        try:
            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]
        finally:
            await conn.close()

    return _run_async(run())


def db_fetchval(query: str, *params):
    async def run():
        conn = await _with_connection()
        try:
            return await conn.fetchval(query, *params)
        finally:
            await conn.close()

    return _run_async(run())


async def _setup_schema() -> None:
    conn = await _with_connection()
    try:
        await conn.execute(f'DROP SCHEMA IF EXISTS {SCHEMA} CASCADE')
        await conn.execute(f'CREATE SCHEMA {SCHEMA}')

        await conn.execute(f'''
            CREATE TABLE {SCHEMA}.ref_data (
                id int PRIMARY KEY,
                big_value bigint NOT NULL,
                text_value text NOT NULL,
                num_value numeric(10, 2) NOT NULL,
                date_value date NOT NULL,
                ts_value timestamp NOT NULL,
                tstz_value timestamptz NOT NULL,
                inet_value inet NOT NULL
            )
        ''')
        await conn.execute(f'''
            COMMENT ON TABLE {SCHEMA}.ref_data IS '{COMMENT_LABEL}'
        ''')
        await conn.execute(f'''
            INSERT INTO {SCHEMA}.ref_data (
                id, big_value, text_value, num_value,
                date_value, ts_value, tstz_value, inet_value
            ) VALUES (
                1,
                9223372036854775807,
                'hello',
                123.45,
                '2024-06-15',
                '2024-06-15 12:30:45',
                '2024-06-15 09:30:45+00',
                '192.168.1.1'
            )
        ''')

        await conn.execute(f'''
            CREATE TABLE {SCHEMA}.ref_filtered (
                id int PRIMARY KEY,
                name text NOT NULL,
                active boolean NOT NULL
            )
        ''')
        await conn.execute(f'''
            COMMENT ON TABLE {SCHEMA}.ref_filtered IS '{COMMENT_LABEL}(active)'
        ''')
        await conn.execute(f'''
            INSERT INTO {SCHEMA}.ref_filtered (id, name, active) VALUES
                (1, 'active row', true),
                (2, 'inactive row', false)
        ''')

        await conn.execute(f'''
            CREATE TABLE {SCHEMA}.ref_custom (
                id int PRIMARY KEY,
                name text NOT NULL,
                hidden text NOT NULL
            )
        ''')
        await conn.execute(f'''
            COMMENT ON TABLE {SCHEMA}.ref_custom IS
            '{COMMENT_LABEL}(select id, name from {SCHEMA}.ref_custom order by id)'
        ''')
        await conn.execute(f'''
            INSERT INTO {SCHEMA}.ref_custom (id, name, hidden) VALUES
                (1, 'visible', 'secret')
        ''')

        await conn.execute(f'''
            CREATE TABLE {SCHEMA}.ref_empty (
                id int PRIMARY KEY,
                name text NOT NULL
            )
        ''')
        await conn.execute(f'''
            COMMENT ON TABLE {SCHEMA}.ref_empty IS '{COMMENT_LABEL}'
        ''')

        await conn.execute(f'''
            CREATE TABLE {SCHEMA}.pred_data (
                id int PRIMARY KEY,
                name text NOT NULL
            )
        ''')
        await conn.execute(f'''
            INSERT INTO {SCHEMA}.pred_data (id, name) VALUES
                (1, 'alpha'),
                (2, 'beta')
        ''')
    finally:
        await conn.close()


async def _teardown_schema() -> None:
    conn = await _with_connection()
    try:
        await conn.execute(f'DROP SCHEMA IF EXISTS {SCHEMA} CASCADE')
    finally:
        await conn.close()


def pg_data_yaml_executable() -> str:
    exe = Path(sys.executable).with_name('pg_data_yaml')
    if exe.exists():
        return str(exe)
    pytest.skip('pg_data_yaml CLI not found; run pip install -e . in the venv')


def connection_args() -> list[str]:
    return [
        '-d', DB_CONFIG['database'],
        '-h', DB_CONFIG['host'],
        '-p', str(DB_CONFIG['port']),
        '-U', DB_CONFIG['user'],
        '-W', DB_CONFIG['password'],
    ]


def run_pg_data_yaml(
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    cmd = [pg_data_yaml_executable(), *args, *connection_args()]
    result = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f'pg_data_yaml failed ({result.returncode}): '
            f'cmd={cmd!r}\nstdout={result.stdout}\nstderr={result.stderr}'
        )
    return result


def load_yaml(path: Path) -> Any:
    with open(path) as file:
        return yaml.safe_load(file)


def dump_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as file:
        yaml.dump(data, file, allow_unicode=True, sort_keys=False)


@dataclass
class IntegrationContext:
    work_dir: Path
    export_dir: Path = field(init=False)
    predicate_export_dir: Path = field(init=False)

    def __post_init__(self):
        self.export_dir = self.work_dir / 'export'
        self.predicate_export_dir = self.work_dir / 'export_predicate'

    def table_yaml(self, table: str, base_dir: Path | None = None) -> Path:
        root = base_dir or self.export_dir
        return root / SCHEMA / f'{table}.yaml'
