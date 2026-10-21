"""Service tests: Client Profile Management F-03 (FR-CPM-01..03, UC-05, AC-12..16)."""
import json

import pytest

from app.errors import ConflictError, PermissionDenied, ValidationError


@pytest.mark.req("FR-CPM-01", "FR-CPM-02", "AC-12", "AC-13")
def test_create_profile_with_needs_normalised(w):
    c = w.app.clients.create_client(w.staff, " Ana ", 4, allergies=[" Nuts", "NUTS", "Milk"],
                                    dietary=["Halal"], cultural=["No pork"], accessibility=["Large print"])
    assert c.name == "Ana" and c.site_id == "S1" and c.household_size == 4
    assert c.allergies == ["nuts", "milk"] and c.dietary == ["halal"] and c.cultural == ["no pork"]
    assert w.app.clients.get_client(w.staff, c.id).accessibility == ["large print"]


@pytest.mark.req("FR-CPM-01", "AC-12")
def test_profile_has_no_financial_fields(w):
    keys = set(w.client.to_dict())
    assert keys == {"id", "site_id", "name", "household_size", "contact", "allergies", "dietary", "cultural",
                    "accessibility", "created_at", "updated_at"}


@pytest.mark.req("FR-CPM-01")
@pytest.mark.parametrize("size,ok", [(0, False), (-1, False), (1, True), (2, True), (20, True),
                                     ("3", False), (2.5, False), (True, False), (None, False)])
def test_household_size_partitions_and_boundary(w, size, ok):
    if ok:
        assert w.app.clients.create_client(w.staff, "X", size).household_size == size
    else:
        with pytest.raises(ValidationError) as ei:
            w.app.clients.create_client(w.staff, "X", size)
        assert "household_size" in ei.value.fields


@pytest.mark.req("FR-CPM-01")
@pytest.mark.parametrize("name", ["", "   "])
def test_name_required(w, name):
    with pytest.raises(ValidationError) as ei:
        w.app.clients.create_client(w.staff, name, 2)
    assert "name" in ei.value.fields


@pytest.mark.req("FR-CPM-03", "AC-14")
def test_update_profile(w):
    c = w.app.clients.update_client(w.staff, w.client.id, household_size=5, dietary=["vegan"], contact="0999")
    assert (c.household_size, c.dietary, c.contact) == (5, ["vegan"], "0999")
    assert c.updated_at and w.app.clients.get_client(w.staff, w.client.id).household_size == 5


@pytest.mark.req("FR-CPM-03")
def test_update_rejects_unknown_empty_or_invalid(w):
    with pytest.raises(ValidationError):
        w.app.clients.update_client(w.staff, w.client.id, salary=100)
    with pytest.raises(ValidationError):
        w.app.clients.update_client(w.staff, w.client.id)
    with pytest.raises(ValidationError):
        w.app.clients.update_client(w.staff, w.client.id, household_size=0)
    assert w.app.clients.get_client(w.staff, w.client.id).household_size == 3      # unchanged


@pytest.mark.req("NFR-04", "FR-REP-03")
def test_audit_log_holds_field_names_only_never_values(w):
    w.app.clients.update_client(w.staff, w.client.id, allergies=["shellfish"], contact="SECRET-PHONE")
    raw = [e for e in w.app.store.data["audit"] if e["action"] == "client.updated"]
    assert raw[0]["details"] == {"fields": ["allergies", "contact"]}
    dump = json.dumps(w.app.store.data["audit"])
    assert "shellfish" not in dump and "SECRET-PHONE" not in dump and "Lola" not in dump


@pytest.mark.req("AC-16", "NFR-04")
@pytest.mark.parametrize("actor", ["vol", "client_user"])
def test_volunteers_and_clients_cannot_view_profiles(w, actor):
    with pytest.raises(PermissionDenied):
        w.app.clients.get_client(getattr(w, actor), w.client.id)
    with pytest.raises(PermissionDenied):
        w.app.clients.search(getattr(w, actor))
    with pytest.raises(PermissionDenied):
        w.app.clients.update_client(getattr(w, actor), w.client.id, contact="x")
    with pytest.raises(PermissionDenied):
        w.app.clients.create_client(getattr(w, actor), "X", 1)


@pytest.mark.req("NFR-04")
def test_site_isolation_and_admin_view(w):
    other = w.app.clients.create_client(w.staff2, "Zed", 1)
    with pytest.raises(PermissionDenied):
        w.app.clients.get_client(w.staff2, w.client.id)
    with pytest.raises(PermissionDenied):
        w.app.clients.update_client(w.staff2, w.client.id, contact="x")
    assert [c.name for c in w.app.clients.search(w.staff)] == ["Lola"]
    assert {c.name for c in w.app.clients.search(w.admin)} == {"Lola", "Zed"}
    assert w.app.clients.get_client(w.admin, other.id).name == "Zed"


def test_search_by_partial_name_case_insensitive(w):
    w.app.clients.create_client(w.staff, "Lolita", 1)
    assert [c.name for c in w.app.clients.search(w.staff, "LOL")] == ["Lola", "Lolita"]
    assert w.app.clients.search(w.staff, "zzz") == []


# ---------- UC-05: client change requests ----------
@pytest.mark.req("UC-05", "FR-CPM-02", "FR-CPM-03")
def test_change_request_flow_apply(w):
    req = w.app.clients.submit_change_request(w.client_user, {"allergies": ["Milk"], "household_size": 4})
    assert req.status == "pending" and req.client_id == w.client.id
    assert w.app.clients.get_client(w.staff, w.client.id).allergies == ["nuts"]     # not applied yet
    assert [r.id for r in w.app.clients.list_change_requests(w.staff)] == [req.id]
    updated = w.app.clients.apply_change_request(w.staff, req.id)
    assert updated.allergies == ["milk"] and updated.household_size == 4
    assert w.app.clients.list_change_requests(w.staff) == []
    assert w.app.clients.list_change_requests(w.staff, status="applied")[0].decided_by == w.staff.id


@pytest.mark.req("UC-05")
def test_change_request_reject_and_double_decision(w):
    req = w.app.clients.submit_change_request(w.client_user, {"contact": "0555"})
    assert w.app.clients.reject_change_request(w.staff, req.id).status == "rejected"
    assert w.app.clients.get_client(w.staff, w.client.id).contact == "0123"
    for call in (w.app.clients.apply_change_request, w.app.clients.reject_change_request):
        with pytest.raises(ConflictError):
            call(w.staff, req.id)


@pytest.mark.req("UC-05", "NFR-04")
def test_change_request_permissions_and_validation(w):
    req = w.app.clients.submit_change_request(w.client_user, {"contact": "0555"})
    for actor in (w.client_user, w.vol, w.staff2):
        with pytest.raises(PermissionDenied):
            w.app.clients.apply_change_request(actor, req.id)
    with pytest.raises(PermissionDenied):
        w.app.clients.submit_change_request(w.staff, {"contact": "x"})              # only client role submits
    for bad in ({}, {"household_size": 0}, {"salary": 5}):
        with pytest.raises(ValidationError):
            w.app.clients.submit_change_request(w.client_user, bad)
