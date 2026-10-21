"""Service tests: Food Order / Hamper Management F-04 (FR-FOM-01..07, FR-FIS-02/03/06, UC-02, AC-07, AC-11, AC-17..21)."""
import json

import pytest

from app.errors import ConflictError, NotFound, PermissionDenied, ValidationError
from helpers import item, receive_stock


@pytest.fixture
def shop(w):
    """Stock for S1 plus a draft order for the nut-allergic, halal client."""
    stock = receive_stock(w.app, w.staff, [
        item("Rice", 20, tags=["halal"]), item("Peanut Butter", 10, allergens=["nuts"]), item("Soup", 5)])
    order = w.app.orders.create_order(w.staff, w.client.id)
    return w, stock, order


# ---------- FR-FOM-01 create ----------
@pytest.mark.req("FR-FOM-01", "AC-17", "UC-02")
def test_create_order_linked_to_client_with_distinct_pickup_refs(w):
    o1 = w.app.orders.create_order(w.staff, w.client.id)
    o2 = w.app.orders.create_order(w.staff, w.client.id)
    assert o1.client_id == w.client.id and o1.status == "preparing" and o1.site_id == "S1"
    assert o1.id != o2.id and o1.pickup_ref != o2.pickup_ref and o1.pickup_ref.startswith("P-")


@pytest.mark.req("FR-FOM-01", "NFR-04")
def test_create_order_permissions_and_site(w):
    for actor in (w.vol, w.client_user, w.admin):
        with pytest.raises(PermissionDenied):
            w.app.orders.create_order(actor, w.client.id)
    with pytest.raises(PermissionDenied):
        w.app.orders.create_order(w.staff2, w.client.id)                        # client belongs to S1
    with pytest.raises(NotFound):
        w.app.orders.create_order(w.staff, "CLI-9999")


# ---------- FR-FOM-03 / FR-FIS-06 selectable list ----------
@pytest.mark.req("FR-FOM-03", "FR-FIS-06", "AC-20", "AC-09")
def test_selectable_items_exclude_allergens_and_unavailable(shop):
    w, stock, order = shop
    assert [i.name for i in w.app.orders.selectable_items(w.staff, order.id)] == ["Rice", "Soup"]
    w.app.inventory.mark_condition(w.staff, stock["Soup"].id, "damaged")
    assert [i.name for i in w.app.orders.selectable_items(w.staff, order.id)] == ["Rice"]


@pytest.mark.req("FR-FOM-03", "AC-20")
def test_client_without_allergies_sees_allergen_items(w):
    receive_stock(w.app, w.staff, [item("Peanut Butter", 10, allergens=["nuts"])])
    free = w.app.clients.create_client(w.staff, "Max", 1)
    o = w.app.orders.create_order(w.staff, free.id)
    assert [i.name for i in w.app.orders.selectable_items(w.staff, o.id)] == ["Peanut Butter"]


# ---------- add_item: allergen block, dietary warning, quantity boundary ----------
@pytest.mark.req("FR-FOM-03", "FR-FOM-04", "AC-19", "UC-02")
def test_allergen_item_is_blocked(shop):
    w, stock, order = shop
    with pytest.raises(ValidationError) as ei:
        w.app.orders.add_item(w.staff, order.id, stock["Peanut Butter"].id, 1)
    assert "inventory_id" in ei.value.fields
    assert w.app.store.get("orders", order.id, type(order)).items == []


@pytest.mark.req("FR-FOM-04", "AC-19")
def test_dietary_mismatch_warns_but_allows(shop):
    w, stock, order = shop
    _, warn = w.app.orders.add_item(w.staff, order.id, stock["Soup"].id, 1)        # not tagged halal
    assert len(warn) == 1 and "halal" in warn[0] and "Soup" in warn[0]
    _, warn = w.app.orders.add_item(w.staff, order.id, stock["Rice"].id, 1)        # tagged halal
    assert warn == []


@pytest.mark.req("FR-FOM-04", "FR-FIS-03", "AC-11")
@pytest.mark.parametrize("qty,ok", [(1, True), (4, True), (5, True), (6, False)],
                         ids=["min", "stock-1", "stock-boundary", "stock+1"])
def test_add_quantity_boundary_against_stock_of_5(shop, qty, ok):
    w, stock, order = shop
    if ok:
        assert w.app.orders.add_item(w.staff, order.id, stock["Soup"].id, qty)[0].items[0]["quantity"] == qty
    else:
        with pytest.raises(ConflictError):
            w.app.orders.add_item(w.staff, order.id, stock["Soup"].id, qty)


@pytest.mark.req("FR-FIS-03")
@pytest.mark.parametrize("qty", [0, -1, "2", 1.5, None])
def test_add_invalid_quantity_rejected(shop, qty):
    w, stock, order = shop
    with pytest.raises(ValidationError):
        w.app.orders.add_item(w.staff, order.id, stock["Soup"].id, qty)


@pytest.mark.req("FR-FIS-03")
def test_adding_same_item_accumulates_and_respects_stock(shop):
    w, stock, order = shop
    w.app.orders.add_item(w.staff, order.id, stock["Soup"].id, 3)
    o, _ = w.app.orders.add_item(w.staff, order.id, stock["Soup"].id, 2)
    assert o.items == [{"inventory_id": stock["Soup"].id, "name": "Soup", "quantity": 5}]
    with pytest.raises(ConflictError):
        w.app.orders.add_item(w.staff, order.id, stock["Soup"].id, 1)


@pytest.mark.req("FR-FIS-06")
def test_unavailable_or_foreign_site_items_cannot_be_added(shop):
    w, stock, order = shop
    w.app.inventory.mark_condition(w.staff, stock["Rice"].id, "expired")
    with pytest.raises(ConflictError):
        w.app.orders.add_item(w.staff, order.id, stock["Rice"].id, 1)
    other = receive_stock(w.app, w.staff2, [item("Beans")])["Beans"]
    with pytest.raises(ConflictError):
        w.app.orders.add_item(w.staff, order.id, other.id, 1)


def test_order_locked_once_ready_and_remove_item(shop):
    w, stock, order = shop
    w.app.orders.add_item(w.staff, order.id, stock["Rice"].id, 2)
    with pytest.raises(NotFound):
        w.app.orders.remove_item(w.staff, order.id, stock["Soup"].id)
    assert w.app.orders.remove_item(w.staff, order.id, stock["Rice"].id).items == []
    w.app.orders.add_item(w.staff, order.id, stock["Rice"].id, 2)
    w.app.orders.set_status(w.staff, order.id, "ready")
    with pytest.raises(ConflictError):
        w.app.orders.add_item(w.staff, order.id, stock["Soup"].id, 1)
    with pytest.raises(ConflictError):
        w.app.orders.remove_item(w.staff, order.id, stock["Rice"].id)


# ---------- FR-FOM-05 substitution note: BVA on length 500 ----------
@pytest.mark.req("FR-FOM-05", "NFR-03", "AC-21", "UC-02")
@pytest.mark.parametrize("length,ok", [(0, False), (1, True), (500, True), (501, False)],
                         ids=["empty", "min", "max", "max+1"])
def test_substitution_note_length_boundary(shop, length, ok):
    w, _, order = shop
    note = "a" * length
    if ok:
        assert w.app.orders.add_substitution_note(w.staff, order.id, note).substitution_notes[0]["by"] == w.staff.id
    else:
        with pytest.raises(ValidationError):
            w.app.orders.add_substitution_note(w.staff, order.id, note)


@pytest.mark.req("FR-FOM-05", "NFR-03", "AC-15")
def test_substitution_note_must_be_respectful_and_not_blank(shop):
    w, _, order = shop
    with pytest.raises(ValidationError):
        w.app.orders.add_substitution_note(w.staff, order.id, "   ")
    with pytest.raises(ValidationError):
        w.app.orders.add_substitution_note(w.staff, order.id, "she is a freeloader")
    ok = w.app.orders.add_substitution_note(w.staff, order.id, "Beans swapped for lentils - out of stock.")
    assert ok.substitution_notes[0]["note"].startswith("Beans")


@pytest.mark.req("FR-FOM-05")
def test_note_not_allowed_on_cancelled_order_or_for_volunteers(shop):
    w, _, order = shop
    with pytest.raises(PermissionDenied):
        w.app.orders.add_substitution_note(w.vol, order.id, "swap")
    w.app.orders.set_status(w.staff, order.id, "cancelled")
    with pytest.raises(ConflictError):
        w.app.orders.add_substitution_note(w.staff, order.id, "swap")


# ---------- status transitions ----------
@pytest.mark.req("FR-FOM-05", "UC-02")
def test_status_transitions(shop):
    w, stock, order = shop
    with pytest.raises(ConflictError):
        w.app.orders.set_status(w.staff, order.id, "ready")                      # empty order
    w.app.orders.add_item(w.staff, order.id, stock["Rice"].id, 2)
    assert w.app.orders.set_status(w.staff, order.id, "ready").status == "ready"
    assert w.app.orders.set_status(w.staff, order.id, "preparing").status == "preparing"
    with pytest.raises(ValidationError):
        w.app.orders.set_status(w.staff, order.id, "completed")                   # must use complete_order
    assert w.app.orders.set_status(w.staff, order.id, "cancelled").status == "cancelled"
    with pytest.raises(ConflictError):
        w.app.orders.set_status(w.staff, order.id, "ready")                       # cancelled is final


@pytest.mark.req("FR-FOM-05", "NFR-04")
def test_volunteers_cannot_change_order_status(shop):
    w, _, order = shop
    with pytest.raises(PermissionDenied):
        w.app.orders.set_status(w.vol, order.id, "cancelled")


# ---------- FR-FIS-02/03 completion ----------
@pytest.mark.req("FR-FIS-02", "AC-07", "UC-02")
def test_completion_reduces_stock_by_exact_quantity_and_logs(shop):
    w, stock, order = shop
    w.app.orders.add_item(w.staff, order.id, stock["Rice"].id, 8)
    w.app.orders.add_item(w.staff, order.id, stock["Soup"].id, 2)
    assert w.app.inventory.get(w.staff, stock["Rice"].id).quantity == 20            # drafting never touches stock
    done = w.app.orders.complete_order(w.staff, order.id)
    assert done.status == "completed" and done.completed_by == w.staff.id and done.completed_at
    assert w.app.inventory.get(w.staff, stock["Rice"].id).quantity == 12
    assert w.app.inventory.get(w.staff, stock["Soup"].id).quantity == 3
    out = [m for m in w.app.store.data["movements"] if m["delta"] < 0]
    assert sorted((m["item_name"], m["delta"]) for m in out) == [("Rice", -8), ("Soup", -2)]
    e = w.app.audit.search(w.admin, group="order_completion")[0]
    assert e.details == {"lines": 2, "total_quantity": 10}


@pytest.mark.req("FR-FIS-02", "AC-07")
def test_cannot_complete_twice_or_when_empty_or_cancelled(shop):
    w, stock, order = shop
    with pytest.raises(ConflictError):
        w.app.orders.complete_order(w.staff, order.id)                              # empty
    w.app.orders.add_item(w.staff, order.id, stock["Rice"].id, 5)
    w.app.orders.complete_order(w.staff, order.id)
    with pytest.raises(ConflictError):
        w.app.orders.complete_order(w.staff, order.id)
    assert w.app.inventory.get(w.staff, stock["Rice"].id).quantity == 15            # reduced once only


@pytest.mark.req("FR-FIS-02", "NFR-04", "UC-03")
@pytest.mark.parametrize("actor", ["vol", "client_user", "admin"])
def test_only_staff_can_complete_orders(shop, actor):
    w, stock, order = shop
    w.app.orders.add_item(w.staff, order.id, stock["Rice"].id, 1)
    with pytest.raises(PermissionDenied):
        w.app.orders.complete_order(getattr(w, actor), order.id)


@pytest.mark.req("FR-FIS-03", "AC-11")
def test_completion_is_all_or_nothing_when_one_line_fails(shop):
    w, stock, order = shop
    w.app.orders.add_item(w.staff, order.id, stock["Rice"].id, 5)
    w.app.orders.add_item(w.staff, order.id, stock["Soup"].id, 3)
    w.app.inventory.mark_condition(w.staff, stock["Soup"].id, "damaged")           # soup becomes unusable
    with pytest.raises(ConflictError):
        w.app.orders.complete_order(w.staff, order.id)
    assert w.app.inventory.get(w.staff, stock["Rice"].id).quantity == 20            # rice untouched
    assert w.app.store.get("orders", order.id, type(order)).status == "preparing"
    assert not [m for m in w.app.store.data["movements"] if m["delta"] < 0]


@pytest.mark.req("FR-FIS-03", "AC-11")
def test_stock_never_goes_below_zero_when_two_orders_share_stock(shop):
    w, stock, first = shop
    second = w.app.orders.create_order(w.staff, w.client.id)
    w.app.orders.add_item(w.staff, first.id, stock["Soup"].id, 5)
    w.app.orders.add_item(w.staff, second.id, stock["Soup"].id, 5)                  # both drafts fit individually
    w.app.orders.complete_order(w.staff, first.id)
    with pytest.raises(ConflictError):
        w.app.orders.complete_order(w.staff, second.id)
    assert w.app.inventory.get(w.staff, stock["Soup"].id).quantity == 0


@pytest.mark.req("FR-FIS-06")
def test_item_that_expires_before_completion_blocks_completion(w):
    s = receive_stock(w.app, w.staff, [item("Milk", 5, expiry="2026-09-16")])["Milk"]
    free = w.app.clients.create_client(w.staff, "Max", 1)
    o = w.app.orders.create_order(w.staff, free.id)
    w.app.orders.add_item(w.staff, o.id, s.id, 1)
    w.clock.advance(days=2)
    with pytest.raises(ConflictError):
        w.app.orders.complete_order(w.staff, o.id)


# ---------- pickup time: BVA around "now" ----------
@pytest.mark.req("FR-FOM-06")
@pytest.mark.parametrize("when,ok", [("2026-09-15 09:59", False), ("2026-09-15 10:00", True), ("2026-09-15 10:01", True)],
                         ids=["now-1min", "now", "now+1min"])
def test_pickup_time_boundary(shop, when, ok):
    w, _, order = shop
    if ok:
        assert w.app.orders.set_pickup_time(w.staff, order.id, when).pickup_time == when.replace(" ", "T")
    else:
        with pytest.raises(ValidationError):
            w.app.orders.set_pickup_time(w.staff, order.id, when)


@pytest.mark.req("FR-FOM-06")
def test_pickup_time_invalid_format_and_finished_orders(shop):
    w, stock, order = shop
    with pytest.raises(ValidationError):
        w.app.orders.set_pickup_time(w.staff, order.id, "soon")
    w.app.orders.add_item(w.staff, order.id, stock["Rice"].id, 1)
    w.app.orders.complete_order(w.staff, order.id)
    with pytest.raises(ConflictError):
        w.app.orders.set_pickup_time(w.staff, order.id, "2026-09-16 10:00")


# ---------- FR-FOM-02 / NFR-04: role-specific views ----------
@pytest.mark.req("FR-FOM-02", "AC-18", "NFR-04")
def test_staff_sees_full_requirements(shop):
    w, stock, order = shop
    view = w.app.orders.get_order_view(w.staff, order.id)
    assert view["client"]["allergies"] == ["nuts"] and view["client"]["dietary"] == ["halal"]
    assert view["pickup_status"] == "Preparing"
    assert w.app.orders.get_order_view(w.admin, order.id)["client"]["name"] == "Lola"


@pytest.mark.req("FR-FOM-02", "AC-18", "AC-24", "AC-27", "NFR-04")
def test_assigned_volunteer_sees_minimum_information_only(shop):
    w, stock, order = shop
    w.app.orders.add_item(w.staff, order.id, stock["Rice"].id, 2)
    w.app.tasks.create_task(w.staff, "Pack", w.vol.id, order_id=order.id)
    view = w.app.orders.get_order_view(w.vol, order.id)
    assert set(view) == {"order_id", "pickup_ref", "status", "items", "safety_flag", "safety_message"}
    assert view["items"] == [{"name": "Rice", "quantity": 2}] and view["safety_flag"] is True
    dump = json.dumps(view).lower()
    for secret in ("lola", "nuts", "halal", "0123", "household"):
        assert secret not in dump


@pytest.mark.req("FR-FOM-02", "AC-18")
def test_safety_flag_false_when_client_has_no_requirements(w):
    plain = w.app.clients.create_client(w.staff, "Max", 1)
    o = w.app.orders.create_order(w.staff, plain.id)
    w.app.tasks.create_task(w.staff, "Pack", w.vol.id, order_id=o.id)
    view = w.app.orders.get_order_view(w.vol, o.id)
    assert view["safety_flag"] is False and view["safety_message"] == ""


@pytest.mark.req("FR-FOM-02", "NFR-04", "UC-03")
def test_unassigned_volunteer_and_other_site_staff_denied(shop):
    w, _, order = shop
    w.app.tasks.create_task(w.staff, "Pack", w.vol.id, order_id=order.id)
    with pytest.raises(PermissionDenied):
        w.app.orders.get_order_view(w.vol2, order.id)
    with pytest.raises(PermissionDenied):
        w.app.orders.get_order_view(w.staff2, order.id)


@pytest.mark.req("FR-FOM-07", "NFR-04")
def test_client_sees_only_own_pickup_status(shop):
    w, _, order = shop
    w.app.orders.set_pickup_time(w.staff, order.id, "2026-09-16 09:00")
    view = w.app.orders.get_order_view(w.client_user, order.id)
    assert view == {"order_id": order.id, "pickup_ref": order.pickup_ref, "pickup_time": "2026-09-16T09:00",
                    "pickup_status": "Preparing"}
    other = w.app.clients.create_client(w.staff, "Max", 1)
    w.app.auth.create_user(w.admin, "max", "password1", "client", "S1", client_id=other.id)
    max_user = w.app.auth.login("max", "password1")
    with pytest.raises(PermissionDenied):
        w.app.orders.get_order_view(max_user, order.id)
    assert w.app.orders.my_orders(max_user) == []
    assert len(w.app.orders.my_orders(w.client_user)) == 1
    with pytest.raises(PermissionDenied):
        w.app.orders.my_orders(w.staff)


@pytest.mark.req("FR-FOM-05")
def test_list_orders_filters_and_permissions(shop):
    w, stock, order = shop
    o2 = w.app.orders.create_order(w.staff, w.client.id)
    w.app.orders.add_item(w.staff, o2.id, stock["Rice"].id, 1)
    w.app.orders.complete_order(w.staff, o2.id)
    assert [o.id for o in w.app.orders.list_orders(w.staff, status="completed")] == [o2.id]
    assert len(w.app.orders.list_orders(w.staff)) == 2 and len(w.app.orders.list_orders(w.admin)) == 2
    assert w.app.orders.list_orders(w.staff2) == []
    with pytest.raises(PermissionDenied):
        w.app.orders.list_orders(w.vol)


# ---------- volunteers may correct draft quantities, but never stock ----------
@pytest.mark.req("FR-FOM-05", "UC-03")
def test_update_quantity_by_staff_and_assigned_volunteer(shop):
    w, stock, order = shop
    w.app.orders.add_item(w.staff, order.id, stock["Rice"].id, 5)
    w.app.tasks.create_task(w.staff, "Pack", w.vol.id, order_id=order.id)
    assert w.app.orders.update_item_quantity(w.staff, order.id, stock["Rice"].id, 7).items[0]["quantity"] == 7
    assert w.app.orders.update_item_quantity(w.vol, order.id, stock["Rice"].id, 6).items[0]["quantity"] == 6
    assert w.app.inventory.get(w.staff, stock["Rice"].id).quantity == 20            # inventory untouched


@pytest.mark.req("FR-FOM-05", "FR-FIS-03")
def test_update_quantity_validation(shop):
    w, stock, order = shop
    w.app.orders.add_item(w.staff, order.id, stock["Rice"].id, 5)
    with pytest.raises(ConflictError):
        w.app.orders.update_item_quantity(w.staff, order.id, stock["Rice"].id, 21)
    with pytest.raises(ValidationError):
        w.app.orders.update_item_quantity(w.staff, order.id, stock["Rice"].id, 0)
    with pytest.raises(NotFound):
        w.app.orders.update_item_quantity(w.staff, order.id, stock["Soup"].id, 1)
    w.app.orders.complete_order(w.staff, order.id)
    with pytest.raises(ConflictError):
        w.app.orders.update_item_quantity(w.staff, order.id, stock["Rice"].id, 1)
