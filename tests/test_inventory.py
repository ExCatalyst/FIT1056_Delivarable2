"""Service tests: Food Inventory F-02 (FR-FIS-01..06, AC-06..11)."""
import pytest

from app.errors import PermissionDenied, ValidationError
from helpers import item, receive_stock


@pytest.mark.req("FR-FIS-06", "AC-09")
@pytest.mark.parametrize("condition", ["damaged", "expired", "missing"])
def test_unavailable_conditions_removed_from_available_stock(w, condition):
    rice = receive_stock(w.app, w.staff, [item("Rice", 10), item("Soup", 10)])["Rice"]
    w.app.inventory.mark_condition(w.staff, rice.id, condition)
    assert [i.name for i in w.app.inventory.search(w.staff)] == ["Soup"]
    assert {i.name for i in w.app.inventory.search(w.staff, only_available=False)} == {"Rice", "Soup"}


@pytest.mark.req("FR-FIS-04", "FR-FIS-05", "AC-08")
def test_condition_change_is_logged_with_previous_new_user_time(w):
    rice = receive_stock(w.app, w.staff, [item("Rice")])["Rice"]
    w.app.inventory.mark_condition(w.staff, rice.id, "damaged", note="crushed box")
    entries = w.app.audit.search(w.admin, group="inventory_condition")
    assert len(entries) == 1
    e = entries[0]
    assert (e.user_id, e.entity_id, e.timestamp) == (w.staff.id, rice.id, "2026-09-15T10:00:00")
    assert e.details == {"previous": "available", "new": "damaged", "note": "crushed box"}


@pytest.mark.req("FR-FIS-04")
def test_marking_same_condition_creates_no_log(w):
    rice = receive_stock(w.app, w.staff, [item("Rice")])["Rice"]
    w.app.inventory.mark_condition(w.staff, rice.id, "available")
    assert w.app.audit.search(w.admin, group="inventory_condition") == []


@pytest.mark.req("FR-FIS-04")
def test_volunteer_can_mark_condition_but_client_cannot(w):
    rice = receive_stock(w.app, w.staff, [item("Rice")])["Rice"]
    assert w.app.inventory.mark_condition(w.vol, rice.id, "missing").condition == "missing"
    with pytest.raises(PermissionDenied):
        w.app.inventory.mark_condition(w.client_user, rice.id, "missing")


@pytest.mark.req("FR-FIS-04")
def test_unknown_condition_rejected(w):
    rice = receive_stock(w.app, w.staff, [item("Rice")])["Rice"]
    with pytest.raises(ValidationError):
        w.app.inventory.mark_condition(w.staff, rice.id, "spoiled")


# ---------- expiry boundary: expiry date == today is still usable, day after is expired ----------
@pytest.mark.req("FR-FIS-06", "FR-DM-01")
def test_expiry_boundary_treated_as_expired_only_after_the_expiry_date(w):
    rice = receive_stock(w.app, w.staff, [item("Milk", 5, expiry="2026-09-16")])["Milk"]
    assert w.app.inventory.get(w.staff, rice.id).condition == "available"        # day before
    w.clock.advance(days=1)                                                  # 16th == expiry day
    assert w.app.inventory.get(w.staff, rice.id).condition == "available"
    w.clock.advance(days=1)                                                  # 17th
    assert w.app.inventory.get(w.staff, rice.id).condition == "expired"
    assert w.app.inventory.search(w.staff) == []


@pytest.mark.req("FR-FIS-05", "FR-FIS-06")
def test_sweep_expired_updates_records_logs_and_is_idempotent(w):
    stock = receive_stock(w.app, w.staff, [item("Milk", 5, expiry="2026-09-16"), item("Rice", 5)])
    w.clock.advance(days=2)
    assert w.app.inventory.sweep_expired(w.staff) == [stock["Milk"].id]
    assert w.app.inventory.sweep_expired(w.staff) == []
    log = w.app.audit.search(w.admin, group="inventory_condition")
    assert len(log) == 1 and log[0].details["new"] == "expired" and log[0].details["note"] == "expiry date passed"


# ---------- search ----------
@pytest.mark.req("FR-FIS-01", "NFR-05")
def test_search_by_name_and_category_case_insensitive_sorted(w):
    receive_stock(w.app, w.staff, [item("Basmati Rice", 5, category="Grains"), item("Apple", 3, category="Fruit"),
                                   item("Oats", 2, category="Grains")])
    assert [i.name for i in w.app.inventory.search(w.staff, "RICE")] == ["Basmati Rice"]
    assert [i.name for i in w.app.inventory.search(w.staff, "grain")] == ["Basmati Rice", "Oats"]
    assert [i.name for i in w.app.inventory.search(w.staff)] == ["Apple", "Basmati Rice", "Oats"]
    assert w.app.inventory.search(w.staff, "zzz") == []


@pytest.mark.req("NFR-04")
def test_site_isolation_in_inventory(w):
    stock = receive_stock(w.app, w.staff, [item("Rice")])
    receive_stock(w.app, w.staff2, [item("Beans")])
    assert [i.name for i in w.app.inventory.search(w.staff)] == ["Rice"]
    assert {i.name for i in w.app.inventory.search(w.admin)} == {"Rice", "Beans"}
    assert [i.name for i in w.app.inventory.search(w.admin, site_id="S2")] == ["Beans"]
    with pytest.raises(PermissionDenied):
        w.app.inventory.get(w.staff2, stock["Rice"].id)
    with pytest.raises(PermissionDenied):
        w.app.inventory.mark_condition(w.staff2, stock["Rice"].id, "damaged")
    with pytest.raises(PermissionDenied):
        w.app.inventory.search(w.client_user)


# ---------- low stock: BVA around threshold 10 ----------
@pytest.mark.req("FR-FIS-01", "UC-02")
@pytest.mark.parametrize("qty,flagged", [(9, True), (10, False), (11, False), (0 + 1, True)],
                         ids=["threshold-1", "threshold", "threshold+1", "minimum"])
def test_low_stock_threshold_boundary(w, qty, flagged):
    receive_stock(w.app, w.staff, [item("Beans", qty)])
    assert (w.app.inventory.low_stock(w.staff) != []) is flagged


@pytest.mark.req("FR-FIS-01")
def test_low_stock_aggregates_batches_and_ignores_unavailable(w):
    receive_stock(w.app, w.staff, [item("Beans", 6)])
    receive_stock(w.app, w.staff, [item("beans", 4)])
    assert w.app.inventory.low_stock(w.staff) == []                          # 6+4 = 10 -> not low
    damaged = receive_stock(w.app, w.staff, [item("Peas", 6)])["Peas"]
    receive_stock(w.app, w.staff, [item("Peas", 6)])
    w.app.inventory.mark_condition(w.staff, damaged.id, "damaged")
    assert w.app.inventory.low_stock(w.staff) == [{"name": "peas", "total": 6}]
    assert w.app.inventory.low_stock(w.staff, threshold=5) == []             # configurable threshold
