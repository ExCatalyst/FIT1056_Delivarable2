"""Non-functional requirement tests: NFR-04 (privacy matrix), NFR-05 (performance), NFR-06 (backup & recovery)."""
import time
from pathlib import Path

import pytest

from app import FoodShareApp
from app.errors import PermissionDenied
from helpers import item, receive_stock

# ---------- NFR-04: every restricted operation is denied to volunteers and client logins ----------
RESTRICTED = {
    "view client": lambda w, a: w.app.clients.get_client(a, w.client.id),
    "search clients": lambda w, a: w.app.clients.search(a),
    "edit client": lambda w, a: w.app.clients.update_client(a, w.client.id, contact="x"),
    "record donation": lambda w, a: w.app.donations.record_offer(a, "D", [item("X")], "pickup"),
    "list donations": lambda w, a: w.app.donations.list(a),
    "create order": lambda w, a: w.app.orders.create_order(a, w.client.id),
    "list orders": lambda w, a: w.app.orders.list_orders(a),
    "stock report": lambda w, a: w.app.reports.stock_movement_report(a, "2026-09-15", "2026-09-15"),
    "audit view": lambda w, a: w.app.audit.search(a),
    "list users": lambda w, a: w.app.auth.list_users(a),
    "create task": lambda w, a: w.app.tasks.create_task(a, "T", w.vol.id),
    "review issues": lambda w, a: w.app.tasks.list_issues(a),
}


@pytest.mark.req("NFR-04", "AC-05", "AC-16")
@pytest.mark.parametrize("operation", sorted(RESTRICTED))
@pytest.mark.parametrize("actor", ["vol", "client_user"])
def test_restricted_operations_denied(w, operation, actor):
    with pytest.raises(PermissionDenied):
        RESTRICTED[operation](w, getattr(w, actor))


# ---------- NFR-05 / AC-10: inventory search within 2 s with >= 500 records ----------
@pytest.mark.req("NFR-05", "AC-10")
def test_inventory_search_under_two_seconds_with_500_records(w):
    receive_stock(w.app, w.staff, [item(f"Item {i:03d}", 5, category="bulk") for i in range(500)])
    assert len(w.app.inventory.search(w.staff, only_available=False)) == 500
    for query in ("item 499", "bulk", ""):
        start = time.perf_counter()
        result = w.app.inventory.search(w.staff, query)
        elapsed = time.perf_counter() - start
        assert result and elapsed < 2.0, f"search {query!r} took {elapsed:.3f}s"


# ---------- NFR-06 / AC-32: backup and recovery ----------
def _snapshot(app, staff):
    return {"stock": sorted((i.name, i.quantity) for i in app.inventory.search(staff)),
            "donations": len(app.donations.list(staff)), "orders": len(app.orders.list_orders(staff)),
            "tasks": len(app.tasks.list_tasks(staff)), "clients": len(app.clients.search(staff))}


@pytest.mark.req("NFR-06", "AC-32")
def test_restore_latest_backup_recovers_donation_inventory_order_task_data(w):
    stock = receive_stock(w.app, w.staff, [item("Rice", 20)])
    o = w.app.orders.create_order(w.staff, w.client.id)
    w.app.orders.add_item(w.staff, o.id, stock["Rice"].id, 5)
    w.app.tasks.create_task(w.staff, "Pack", w.vol.id, order_id=o.id)
    before = _snapshot(w.app, w.staff)
    w.app.backup_now()

    w.app.orders.complete_order(w.staff, o.id)                                      # "a day of work" after the backup
    w.app.clients.create_client(w.staff, "New", 1)
    assert _snapshot(w.app, w.staff) != before

    w.app.restore_latest_backup()
    assert _snapshot(w.app, w.staff) == before
    assert w.app.orders.list_orders(w.staff, status="completed") == []
    reopened = FoodShareApp(w.app.store.path, w.app.store.backup_dir, w.clock, 1000)   # restore was persisted
    assert _snapshot(reopened, w.staff) == before


@pytest.mark.req("NFR-06", "AC-32")
def test_a_backup_exists_on_startup_and_one_per_day(tmp_path, clock):
    def backups():
        return sorted(p.name for p in (tmp_path / "bk").glob("*.json"))

    FoodShareApp(tmp_path / "db.json", tmp_path / "bk", clock, 1000)
    first = backups()
    assert len(first) == 1 and first[0].startswith("db-20260915")
    FoodShareApp(tmp_path / "db.json", tmp_path / "bk", clock, 1000)                # same day: no new backup
    assert backups() == first
    clock.advance(days=1)
    FoodShareApp(tmp_path / "db.json", tmp_path / "bk", clock, 1000)                # next day: new backup
    assert len(backups()) == 2 and backups()[-1].startswith("db-20260916")
