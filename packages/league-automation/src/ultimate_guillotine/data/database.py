"""Connection helper for the automation state database."""

import psycopg

from ultimate_guillotine.config import Settings


def connect(settings: Settings) -> psycopg.Connection:
    """Open a new connection to the automation database.

    Autocommit is off: callers are responsible for committing (or rolling
    back) their own transactions.
    """
    return psycopg.connect(settings.database_url.get_secret_value(), autocommit=False)
