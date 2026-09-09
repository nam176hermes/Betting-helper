import os
import sqlite3
from uuid import uuid4

import pytest

from moj_discovery.providers.quota import Denied, QuotaLedger


def test_second_process_cannot_own_poller(tmp_path, fake_clock):
    path = tmp_path / "quota.sqlite3"
    with QuotaLedger(path, scope_id=str(uuid4())):
        pid = os.fork()
        if pid == 0:
            try:
                QuotaLedger(path, scope_id=str(uuid4()))
            except ValueError as error:
                os._exit(0 if str(error) == "E_QUOTA_POLLER_LOCK" else 2)
            os._exit(3)
        _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == 0


def test_reservation_committed_before_io_and_no_crash_refund(tmp_path, fake_clock):
    path, scope = tmp_path / "quota.sqlite3", str(uuid4())
    pid = os.fork()
    if pid == 0:
        q = QuotaLedger(path, scope_id=scope, session_cap=1, allow_status_bootstrap=True)
        attempt = q.reserve_attempt(scope, "STATUS", fake_clock.utc, fake_clock.mono)
        os._exit(2 if isinstance(attempt, Denied) else 0)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0
    with sqlite3.connect(path) as actual:
        assert actual.execute("SELECT count(*) FROM quota_reservations").fetchone()[0] == 1
        assert actual.execute("SELECT count(*) FROM quota_outcomes").fetchone()[0] == 0
    with QuotaLedger(path, scope_id=scope, session_cap=1, allow_status_bootstrap=True) as q:
        fake_clock.advance(60)
        assert (
            q.reserve_attempt(scope, "STATUS", fake_clock.utc, fake_clock.mono).code
            == "SESSION_BUDGET"
        )
        assert q.count_attempts() == 1


def test_shared_day_budget_survives_sequential_owners(tmp_path, fake_clock):
    path = tmp_path / "quota.sqlite3"
    for index in range(2):
        scope = str(uuid4())
        with QuotaLedger(path, scope_id=scope, daily_cap=1, allow_status_bootstrap=True) as q:
            a = q.reserve_attempt(scope, "STATUS", fake_clock.utc, fake_clock.mono)
            if index == 0:
                assert not isinstance(a, Denied)
                q.finalize_attempt(a.attempt_id, "TIMEOUT", {})
            else:
                assert a.code == "DAILY_BUDGET"
        fake_clock.advance(60)


def test_private_files_immutability_and_symlink_rejection(tmp_path, fake_clock):
    scope = str(uuid4())
    path = tmp_path / "quota.sqlite3"
    with QuotaLedger(path, scope_id=scope, allow_status_bootstrap=True) as q:
        q.reserve_attempt(scope, "STATUS", fake_clock.utc, fake_clock.mono)
        assert path.stat().st_mode & 0o777 == 0o600
        with pytest.raises(sqlite3.DatabaseError):
            q.db.execute("DELETE FROM quota_reservations")
    link = tmp_path / "link.sqlite3"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="E_QUOTA_PATH"):
        QuotaLedger(link, scope_id=scope)
