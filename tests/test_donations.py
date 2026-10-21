"""Service tests: Donation Management F-01 (FR-DM-01..04, UC-06, AC-01..05)."""
import pytest

from app.errors import ConflictError, NotFound, PermissionDenied, ValidationError
from helpers import item, receive_stock


@pytest.mark.req("FR-DM-01", "AC-01", "UC-06")
def test_record_offer_saved_as_offered(w):
    d = w.app.donations.record_offer(w.staff, "  DONOR-7 ", [item("Rice", 20)], "pickup")
    assert d.status == "offered" and d.donor_ref == "DONOR-7" and d.site_id == "S1"
    assert d.items[0]["quantity"] == 20 and d.items[0]["expiry"] == "2027-01-01"
    assert w.app.inventory.search(w.staff, "rice") == []      # stock only changes once received


@pytest.mark.req("FR-DM-03", "AC-04")
@pytest.mark.parametrize("donor,method,field", [("", "pickup", "donor_ref"), ("  ", "pickup", "donor_ref"),
                                                ("D1", "courier", "collection_method"), ("D1", None, "collection_method")])
def test_mandatory_header_fields(w, donor, method, field):
    with pytest.raises(ValidationError) as ei:
        w.app.donations.record_offer(w.staff, donor, [item("Rice")], method)
    assert field in ei.value.fields
    assert w.app.donations.list(w.staff) == []                # nothing saved


@pytest.mark.req("FR-DM-02", "AC-02")
@pytest.mark.parametrize("qty", [0, -1])
def test_zero_or_negative_quantity_blocked_and_nothing_saved(w, qty):
    with pytest.raises(ValidationError) as ei:
        w.app.donations.record_offer(w.staff, "D1", [item("Rice", qty)], "pickup")
    assert "items[0].quantity" in ei.value.fields
    assert w.app.donations.list(w.staff) == []


@pytest.mark.req("FR-DM-03", "AC-04")
def test_all_missing_fields_reported_together(w):
    with pytest.raises(ValidationError) as ei:
        w.app.donations.record_offer(w.staff, "", [{"name": "", "quantity": 0, "expiry": ""}], "x")
    assert {"donor_ref", "collection_method", "items[0].name", "items[0].quantity", "items[0].expiry"} <= set(ei.value.fields)


@pytest.mark.req("FR-DM-01", "FR-DM-03")
def test_already_expired_donation_rejected_but_expiring_today_accepted(w):
    with pytest.raises(ValidationError):
        w.app.donations.record_offer(w.staff, "D1", [item("Milk", expiry="2026-09-14")], "pickup")
    assert w.app.donations.record_offer(w.staff, "D1", [item("Milk", expiry="2026-09-15")], "pickup")


@pytest.mark.req("FR-DM-04", "FR-FIS-01", "AC-03", "AC-06")
def test_received_adds_exact_items_and_quantities_to_inventory(w):
    d = w.app.donations.record_offer(w.staff, "D1", [item("Rice", 20, category="grain"), item("Soup", 4)], "pickup")
    w.app.donations.update_status(w.staff, d.id, "received")
    stock = {i.name: i for i in w.app.inventory.search(w.staff)}
    assert stock["Rice"].quantity == 20 and stock["Soup"].quantity == 4 and stock["Rice"].donation_id == d.id
    assert w.app.donations.get(w.staff, d.id).status == "received"
    movements = w.app.store.data["movements"]
    assert [(m["item_name"], m["delta"], m["reason"]) for m in movements] == [
        ("Rice", 20, "donation_received"), ("Soup", 4, "donation_received")]


@pytest.mark.req("FR-DM-04", "UC-06", "AC-03")
def test_rejected_adds_nothing(w):
    d = w.app.donations.record_offer(w.staff, "D1", [item("Rice", 20)], "pickup")
    w.app.donations.update_status(w.staff, d.id, "rejected")
    assert w.app.donations.get(w.staff, d.id).status == "rejected"
    assert w.app.inventory.search(w.staff, only_available=False) == []
    assert w.app.store.data["movements"] == []


@pytest.mark.req("FR-DM-04", "FR-FIS-01")
def test_donation_can_only_be_decided_once(w):
    d = w.app.donations.record_offer(w.staff, "D1", [item("Rice", 20)], "pickup")
    w.app.donations.update_status(w.staff, d.id, "received")
    for status in ("received", "rejected"):
        with pytest.raises(ConflictError):
            w.app.donations.update_status(w.staff, d.id, status)
    assert w.app.inventory.search(w.staff, "rice")[0].quantity == 20      # not doubled


@pytest.mark.req("FR-DM-04")
@pytest.mark.parametrize("status", ["offered", "pending", ""])
def test_invalid_target_status(w, status):
    d = w.app.donations.record_offer(w.staff, "D1", [item("Rice")], "pickup")
    with pytest.raises(ValidationError):
        w.app.donations.update_status(w.staff, d.id, status)


def test_unknown_donation_not_found(w):
    with pytest.raises(NotFound):
        w.app.donations.update_status(w.staff, "DON-9999", "received")


@pytest.mark.req("AC-05", "NFR-04")
@pytest.mark.parametrize("actor", ["vol", "client_user", "admin"])
def test_only_staff_can_record_or_decide(w, actor):
    d = w.app.donations.record_offer(w.staff, "D1", [item("Rice")], "pickup")
    with pytest.raises(PermissionDenied):
        w.app.donations.record_offer(getattr(w, actor), "D2", [item("Rice")], "pickup")
    with pytest.raises(PermissionDenied):
        w.app.donations.update_status(getattr(w, actor), d.id, "received")


@pytest.mark.req("AC-05", "NFR-04")
@pytest.mark.parametrize("actor", ["vol", "client_user"])
def test_volunteers_and_clients_cannot_view_donations(w, actor):
    d = w.app.donations.record_offer(w.staff, "D1", [item("Rice")], "pickup")
    with pytest.raises(PermissionDenied):
        w.app.donations.list(getattr(w, actor))
    with pytest.raises(PermissionDenied):
        w.app.donations.get(getattr(w, actor), d.id)


@pytest.mark.req("NFR-04", "FR-REP-01")
def test_site_isolation_and_admin_visibility(w):
    d1 = w.app.donations.record_offer(w.staff, "D1", [item("Rice")], "pickup")
    d2 = w.app.donations.record_offer(w.staff2, "D2", [item("Beans")], "pickup")
    assert [d.id for d in w.app.donations.list(w.staff)] == [d1.id]
    assert {d.id for d in w.app.donations.list(w.admin)} == {d1.id, d2.id}
    assert [d.id for d in w.app.donations.list(w.admin, site_id="S2")] == [d2.id]
    with pytest.raises(PermissionDenied):
        w.app.donations.list(w.staff, site_id="S2")
    with pytest.raises(PermissionDenied):
        w.app.donations.update_status(w.staff2, d1.id, "received")       # other site's donation
    assert w.app.donations.get(w.admin, d1.id).id == d1.id


@pytest.mark.req("FR-DM-01")
def test_list_filtered_by_status(w):
    a = w.app.donations.record_offer(w.staff, "D1", [item("Rice")], "pickup")
    b = w.app.donations.record_offer(w.staff, "D2", [item("Soup")], "pickup")
    w.app.donations.update_status(w.staff, b.id, "received")
    assert [d.id for d in w.app.donations.list(w.staff, status="offered")] == [a.id]
    assert [d.id for d in w.app.donations.list(w.staff, status="received")] == [b.id]


def test_receive_stock_helper_returns_items(w):
    assert set(receive_stock(w.app, w.staff, [item("Rice"), item("Soup")])) == {"Rice", "Soup"}
