"""Functional / end-to-end tests: one scenario per use case (UC-01..UC-06) plus the full donation-to-report chain.
Each test drives the system only through the FoodShareApp facade, exactly as the Streamlit UI will."""
import json

import pytest

from app.errors import AuthenticationError, PermissionDenied, ValidationError
from helpers import item


@pytest.mark.req("UC-01", "NFR-04")
def test_e2e_uc01_login_lockout_and_unlock(app):
    admin = app.auth.bootstrap_admin("admin", "adminpass1")
    staff = app.auth.create_user(admin, "bob", "password1", "staff", "S1")
    # main flow
    assert app.auth.login("bob", "password1").role == "staff"
    # alternative flow: wrong credentials -> error, repeated failures -> lock -> contact admin
    for _ in range(5):
        with pytest.raises(AuthenticationError):
            app.auth.login("bob", "bad")
    with pytest.raises(AuthenticationError) as ei:
        app.auth.login("bob", "password1")
    assert "contact an administrator" in ei.value.message
    # existing session is refused too
    with pytest.raises(AuthenticationError):
        app.clients.search(staff)
    app.auth.unlock_user(admin, staff.id)
    assert app.auth.login("bob", "password1")
    assert app.clients.search(staff) == []


@pytest.mark.req("UC-02", "FR-FOM-01", "FR-FOM-02", "FR-FOM-03", "FR-FOM-04", "FR-FOM-05", "FR-FIS-02", "FR-FIS-06")
def test_e2e_uc02_build_hamper_for_allergic_client(w):
    app = w.app
    d = app.donations.record_offer(w.staff, "D-1", [
        item("Rice", 20, tags=["halal"]), item("Peanut Butter", 10, allergens=["nuts"]),
        item("Beans", 4, tags=["halal"]), item("Soup", 6)], "drop_off")
    app.donations.update_status(w.staff, d.id, "received")
    stock = {i.name: i for i in app.inventory.search(w.staff)}

    order = app.orders.create_order(w.staff, w.client.id)
    shown = [i.name for i in app.orders.selectable_items(w.staff, order.id)]
    assert "Peanut Butter" not in shown and shown == ["Beans", "Rice", "Soup"]          # allergen auto-excluded
    assert app.orders.get_order_view(w.staff, order.id)["client"]["allergies"] == ["nuts"]

    app.orders.add_item(w.staff, order.id, stock["Rice"].id, 5)
    _, warnings = app.orders.add_item(w.staff, order.id, stock["Soup"].id, 2)
    assert any("halal" in x for x in warnings)                                          # dietary warning
    with pytest.raises(ValidationError):
        app.orders.add_item(w.staff, order.id, stock["Peanut Butter"].id, 1)            # allergen blocked

    # alternative flow: beans run out -> substitute + respectful note
    app.inventory.mark_condition(w.staff, stock["Beans"].id, "missing")
    assert "Beans" not in [i.name for i in app.orders.selectable_items(w.staff, order.id)]
    app.orders.add_substitution_note(w.staff, order.id, "Beans unavailable - soup added instead.")

    app.orders.set_pickup_time(w.staff, order.id, "2026-09-16 09:30")
    assert app.orders.set_status(w.staff, order.id, "ready").status == "ready"
    done = app.orders.complete_order(w.staff, order.id)
    assert done.status == "completed" and len(done.substitution_notes) == 1
    assert {i.name: i.quantity for i in app.inventory.search(w.staff)} == {"Rice": 15, "Peanut Butter": 10, "Soup": 4}
    assert app.orders.my_orders(w.client_user)[0]["pickup_status"] == "Collected"


@pytest.mark.req("UC-03", "FR-VTM-02", "FR-VTM-03", "FR-VTM-04", "FR-FOM-02", "NFR-04")
def test_e2e_uc03_volunteer_progress_and_issue_reporting(w):
    app = w.app
    d = app.donations.record_offer(w.staff, "D", [item("Rice", 20), item("Soup", 6)], "pickup")
    app.donations.update_status(w.staff, d.id, "received")
    stock = {i.name: i for i in app.inventory.search(w.staff)}
    order = app.orders.create_order(w.staff, w.client.id)
    app.orders.add_item(w.staff, order.id, stock["Rice"].id, 4)
    task = app.tasks.create_task(w.staff, "Pack Lola's hamper", w.vol.id, order_id=order.id)

    assert [t.id for t in app.tasks.my_tasks(w.vol)] == [task.id]                       # sees own task
    view = app.orders.get_order_view(w.vol, order.id)                                   # minimum packing info
    assert view["safety_flag"] is True and "lola" not in json.dumps(view).lower()
    app.tasks.update_status(w.vol, task.id, "in_progress")
    assert app.tasks.list_tasks(w.staff)[0].status == "in_progress"                     # visible to staff

    issue = app.tasks.submit_issue(w.vol, "damaged_food", "tin dented", inventory_id=stock["Soup"].id)
    assert app.inventory.get(w.staff, stock["Soup"].id).flagged is True
    assert app.tasks.list_issues(w.staff)[0].id == issue.id

    # alternative flows: restricted details and final completion are denied
    with pytest.raises(PermissionDenied):
        app.clients.get_client(w.vol, w.client.id)
    with pytest.raises(PermissionDenied):
        app.orders.complete_order(w.vol, order.id)
    assert app.inventory.get(w.staff, stock["Rice"].id).quantity == 20                  # no stock change by volunteer

    app.tasks.update_status(w.vol, task.id, "completed")
    app.tasks.review_issue(w.staff, issue.id)                                           # staff review clears flag
    assert app.inventory.get(w.staff, stock["Soup"].id).flagged is False
    app.orders.complete_order(w.staff, order.id)                                        # only staff deduct stock
    assert app.inventory.get(w.staff, stock["Rice"].id).quantity == 16


@pytest.mark.req("UC-04", "NFR-04", "FR-REP-02")
def test_e2e_uc04_manage_roles_and_permissions(w):
    app = w.app
    new = app.auth.create_user(w.admin, "newbie", "password1", "volunteer", "S1")
    with pytest.raises(PermissionDenied):
        app.donations.record_offer(new, "D", [item("Rice")], "pickup")                  # volunteer: no donation access
    app.auth.change_role(w.admin, new.id, "staff")
    assert app.donations.record_offer(new, "D", [item("Rice")], "pickup").status == "offered"   # applied immediately
    with pytest.raises(PermissionDenied):
        app.auth.change_role(w.staff, new.id, "volunteer")                              # staff cannot manage roles
    trail = app.audit.search(w.admin, group="role_change")
    assert [(e.user_id, e.details["new"]) for e in trail] == [(w.admin.id, "staff")]
    app.auth.set_active(w.admin, new.id, False)
    with pytest.raises(AuthenticationError):
        app.donations.list(new)


@pytest.mark.req("UC-05", "FR-CPM-01", "FR-CPM-02", "FR-CPM-03", "NFR-04")
def test_e2e_uc05_client_updates_preferences(w):
    app = w.app
    req = app.clients.submit_change_request(w.client_user, {"allergies": ["nuts", "sesame"], "dietary": ["vegetarian"]})
    with pytest.raises(PermissionDenied):
        app.clients.get_client(w.client_user, w.client.id)                              # client cannot browse profiles
    assert [r.id for r in app.clients.list_change_requests(w.staff)] == [req.id]        # staff flagged
    with pytest.raises(ValidationError):
        app.clients.submit_change_request(w.client_user, {"household_size": 0})         # alternative: invalid input
    app.clients.apply_change_request(w.staff, req.id)
    profile = app.clients.get_client(w.staff, w.client.id)
    assert profile.allergies == ["nuts", "sesame"] and profile.dietary == ["vegetarian"]
    # the new allergy takes effect for the next hamper
    app.donations.update_status(w.staff, app.donations.record_offer(
        w.staff, "D", [item("Tahini", 5, allergens=["sesame"]), item("Rice", 5)], "pickup").id, "received")
    order = app.orders.create_order(w.staff, w.client.id)
    assert [i.name for i in app.orders.selectable_items(w.staff, order.id)] == ["Rice"]


@pytest.mark.req("UC-06", "FR-DM-01", "FR-DM-02", "FR-DM-03", "FR-DM-04", "FR-FIS-01")
def test_e2e_uc06_record_donation_offer(w):
    app = w.app
    with pytest.raises(ValidationError):                                                # invalid entries returned for correction
        app.donations.record_offer(w.staff, "D-1", [item("Rice", 0)], "pickup")
    assert app.donations.list(w.staff) == []
    good = app.donations.record_offer(w.staff, "D-1", [item("Rice", 12)], "pickup")
    assert app.donations.get(w.staff, good.id).status == "offered"
    # alternative flow: donation type not accepted -> rejected, nothing enters stock
    bad = app.donations.record_offer(w.staff, "D-2", [item("Alcohol", 3)], "drop_off")
    app.donations.update_status(w.staff, bad.id, "rejected")
    app.donations.update_status(w.staff, good.id, "received")
    assert [(i.name, i.quantity) for i in app.inventory.search(w.staff, only_available=False)] == [("Rice", 12)]
    assert [d.status for d in app.donations.list(w.staff)] == ["received", "rejected"]


@pytest.mark.req("F-01", "F-02", "F-03", "F-04", "F-05", "F-06", "UC-02", "UC-06", "FR-REP-01", "FR-REP-02")
def test_e2e_donation_to_distribution_to_report_chain(w):
    """Donor offer -> stock -> low-stock alert -> hamper -> pickup -> completion -> report + audit for the manager."""
    app = w.app
    d = app.donations.record_offer(w.staff, "D-9", [item("Rice", 12), item("Soup", 30)], "pickup")
    app.donations.update_status(w.staff, d.id, "received")
    order = app.orders.create_order(w.staff, w.client.id)
    stock = {i.name: i for i in app.inventory.search(w.staff)}
    app.orders.add_item(w.staff, order.id, stock["Rice"].id, 5)
    assert app.inventory.low_stock(w.staff) == []                                       # 12 Rice, 30 Soup: nothing low yet
    app.orders.complete_order(w.staff, order.id)
    assert app.inventory.low_stock(w.staff) == [{"name": "rice", "total": 7}]           # 12 - 5 = 7 < 10

    report = app.reports.stock_movement_report(w.admin, "2026-09-15", "2026-09-15")
    assert {r["item"]: (r["received"], r["distributed"]) for r in report["rows"]} == {"Rice": (12, 5), "Soup": (30, 0)}
    assert report["totals"] == {"received": 42, "distributed": 5}
    assert len(app.audit.search(w.admin, group="order_completion")) == 1
