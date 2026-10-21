"""Shared fixtures + automatic requirement->test traceability report (test_reports/traceability.csv)."""
import csv
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import FoodShareApp   # <- change 'foodshare' if your package folder has another name


class Clock:
    """Controllable clock so expiry / pickup-time / report-date behaviour is deterministic."""
    def __init__(self, start):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, **kwargs):
        self.t += timedelta(**kwargs)


@pytest.fixture
def clock():
    return Clock(datetime(2026, 9, 15, 10, 0, 0))


@pytest.fixture
def app(tmp_path, clock):
    return FoodShareApp(tmp_path / "data" / "foodshare.json", backup_dir=tmp_path / "backups",
                        clock=clock, hash_iterations=1000)  # low iterations = fast tests


@pytest.fixture
def w(app, clock):
    """A small world: 1 admin, staff in S1 and S2, two S1 volunteers, one client (nut allergy, halal) with a login."""
    admin = app.auth.bootstrap_admin("admin", "adminpass1", site_id="HQ")

    def make(username, role, site):
        return app.auth.create_user(admin, username, "password1", role, site, full_name=username)

    staff, staff2 = make("bob", "staff", "S1"), make("sam", "staff", "S2")
    vol, vol2 = make("jay", "volunteer", "S1"), make("kim", "volunteer", "S1")
    client = app.clients.create_client(staff, "Lola", 3, contact="0123", allergies=["nuts"], dietary=["halal"])
    client_user = app.auth.create_user(admin, "lola", "password1", "client", "S1", client_id=client.id)
    return SimpleNamespace(app=app, clock=clock, admin=admin, staff=staff, staff2=staff2, vol=vol, vol2=vol2,
                           client=client, client_user=client_user)


# ---------------- requirement traceability ----------------
_TRACE = defaultdict(list)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call" or (rep.when == "setup" and rep.skipped):
        label = "xfail (known defect)" if hasattr(rep, "wasxfail") else rep.outcome
        for marker in item.iter_markers("req"):
            for rid in marker.args:
                _TRACE[rid].append((item.nodeid, label))


def pytest_sessionfinish(session, exitstatus):
    out = Path(session.config.rootpath) / "test_reports"
    out.mkdir(exist_ok=True)
    with open(out / "traceability.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["requirement", "test", "result"])
        for rid in sorted(_TRACE):
            for nodeid, result in _TRACE[rid]:
                writer.writerow([rid, nodeid, result])
