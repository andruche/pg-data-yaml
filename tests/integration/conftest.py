import asyncio

import pytest

from tests.integration.helpers import (
    IntegrationContext,
    _setup_schema,
    _teardown_schema,
    _with_connection,
)


@pytest.fixture(scope='session')
def db_available():
    try:
        asyncio.run(_with_connection())
    except Exception as exc:
        pytest.skip(f'PostgreSQL not available: {exc}')


@pytest.fixture(scope='session')
def integration_schema(db_available):
    asyncio.run(_setup_schema())
    yield
    asyncio.run(_teardown_schema())


@pytest.fixture(scope='module')
def ctx(integration_schema, tmp_path_factory):
    return IntegrationContext(work_dir=tmp_path_factory.mktemp('dd_integration'))
