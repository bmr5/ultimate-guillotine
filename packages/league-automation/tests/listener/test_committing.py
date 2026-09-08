import pytest

from ultimate_guillotine.listener.committing import CommittingRepo


class FakeConn:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeRepo:
    def __init__(self, exc=None, value="ok"):
        self._exc = exc
        self._value = value
        self.calls = []

    def upsert(self, row):
        self.calls.append(row)
        if self._exc:
            raise self._exc
        return self._value


def test_success_commits_once_and_returns_value() -> None:
    conn = FakeConn()
    repo = CommittingRepo(FakeRepo(value="ok"), conn)
    assert repo.upsert("row") == "ok"
    assert conn.commits == 1
    assert conn.rollbacks == 0


def test_failure_rolls_back_and_reraises_without_committing() -> None:
    conn = FakeConn()
    repo = CommittingRepo(FakeRepo(exc=ValueError("boom")), conn)
    with pytest.raises(ValueError, match="boom"):
        repo.upsert("row")
    assert conn.rollbacks == 1
    assert conn.commits == 0


def test_missing_attribute_raises_attribute_error() -> None:
    conn = FakeConn()
    repo = CommittingRepo(FakeRepo(), conn)
    with pytest.raises(AttributeError):
        _ = repo.nonexistent_method
