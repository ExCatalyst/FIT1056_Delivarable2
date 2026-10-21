"""Known defects found during code review, written as the behaviour the SRS EXPECTS.
They are marked xfail(strict=True): the suite stays green today, and the moment a defect is fixed the test
XPASSes, strict mode turns that into a failure and tells you to delete the xfail marker."""
import json

import pytest

from app import FoodShareApp
from app.errors import FoodShareError, PermissionDenied, ValidationError
from helpers import item, receive_stock


@pytest.mark.xfail(strict=True, reason="DEF-01 allergen matching is exact-string: client 'nuts' vs item 'peanut'")
@pytest.mark.req("FR-FOM-03", "AC-20")
def test_def01_related_allergen_terms_are_excluded(w):
    receive_stock(w.app, w.staff, [item("Satay Sauce", 5, allergens=["peanut"])])
    order = w.app.orders.create_order(w.staff, w.client.id)                      # client allergy = 'nuts'
    assert w.app.orders.selectable_items(w.staff, order.id) == []


@pytest.mark.xfail(strict=True, reason="DEF-02 volunteer can set a damaged item back to 'available'")
@pytest.mark.req("FR-FIS-04", "FR-FIS-06")
def test_def02_volunteer_cannot_restore_item_marked_damaged_by_staff(w):
    rice = receive_stock(w.app, w.staff, [item("Rice")])["Rice"]
    w.app.inventory.mark_condition(w.staff, rice.id, "damaged")
    with pytest.raises(PermissionDenied):
        w.app.inventory.mark_condition(w.vol, rice.id, "available")


@pytest.mark.xfail(strict=True, reason="DEF-03 bootstrap_admin accepts a blank username")
@pytest.mark.req("UC-01", "UC-04")
def test_def03_bootstrap_admin_requires_username(app):
    with pytest.raises(ValidationError):
        app.auth.bootstrap_admin("   ", "adminpass1")


@pytest.mark.xfail(strict=True, reason="DEF-04 audit.search raises raw KeyError for an unknown group")
@pytest.mark.req("FR-REP-02")
def test_def04_audit_unknown_group_is_a_validation_error(w):
    with pytest.raises(ValidationError):
        w.app.audit.search(w.admin, group="nonsense")


@pytest.mark.xfail(strict=True, reason="DEF-05 a corrupt data file stops FoodShareApp from starting, so restore is unreachable")
@pytest.mark.req("NFR-06", "AC-32")
def test_def05_app_can_recover_from_corrupt_data_file(tmp_path, clock):
    path, backups = tmp_path / "db.json", tmp_path / "bk"
    first = FoodShareApp(path, backups, clock, 1000)
    first.auth.bootstrap_admin("admin", "adminpass1")
    first.backup_now()
    path.write_text("{corrupted")
    try:
        second = FoodShareApp(path, backups, clock, 1000)
        second.restore_latest_backup()
    except FoodShareError as exc:                                               # StorageError today
        pytest.fail(f"could not start/recover: {exc.message}")
    assert second.store.data["users"]


@pytest.mark.xfail(strict=True, reason="DEF-06 update_client(contact=None) stores the text 'None'")
@pytest.mark.req("FR-CPM-03")
def test_def06_none_contact_is_stored_as_empty(w):
    assert w.app.clients.update_client(w.staff, w.client.id, contact=None).contact == ""
