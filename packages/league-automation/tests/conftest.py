"""Shared fixtures for the database-backed tests.

One `conn` fixture for the whole suite. It wraps the test in an explicit
`force_rollback` transaction rather than relying on the connection never being
committed: code under test may open its own `conn.transaction()` (as
`sleeper.sync.sync_season` does), which would otherwise commit for real and leave
rows behind in the developer's local database. Inside a force-rollback
transaction those nest as savepoints and the outer transaction is always rolled
back on the way out.
"""

import os

import psycopg
import pytest


@pytest.fixture
def conn():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    with psycopg.connect(url) as connection, connection.transaction(force_rollback=True):
        yield connection
