"""Wrap a repository so every call commits on success and rolls back on failure."""

import contextlib


class CommittingRepo:
    """Wrap a repository so every call commits; the listener runs one operation per request.

    On success the underlying method's result is returned and the connection is committed.
    On failure the connection is rolled back and the original exception is re-raised, so a
    single failed statement never leaves the connection in an aborted transaction state.
    """

    def __init__(self, repo, conn):
        self._repo, self._conn = repo, conn

    def __getattr__(self, name):
        method = getattr(self._repo, name)

        def call(*args, **kwargs):
            try:
                result = method(*args, **kwargs)
            except Exception:
                with contextlib.suppress(Exception):
                    self._conn.rollback()
                raise
            self._conn.commit()
            return result

        return call
