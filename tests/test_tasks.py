"""Service tests: Volunteer Task Management F-05 (FR-VTM-01..04, UC-03, AC-22..27)."""
import pytest

from app.errors import ConflictError, PermissionDenied, ValidationError
from app.models import InventoryItem
from helpers import item, receive_stock


@pytest.mark.req("FR-VTM-01", "AC-22")
def test_staff_creates_and_assigns_task(w):
    t = w.app.tasks.create_task(w.staff, " Pack hampers ", w.vol.id, "3 hampers")
    assert t.title == "Pack hampers" and t.assigned_to == w.vol.id and t.status == "not_started" and t.site_id == "S1"


@pytest.mark.req("FR-VTM-01")
def test_create_task_validation(w):
    with pytest.raises(ValidationError):
        w.app.tasks.create_task(w.staff, "  ", w.vol.id)
    with pytest.raises(ValidationError):
        w.app.tasks.create_task(w.staff, "T", w.staff.id)                       # not a volunteer
    with pytest.raises(ValidationError):
        w.app.tasks.create_task(w.staff2, "T", w.vol.id)                        # volunteer from another site
    w.app.auth.set_active(w.admin, w.vol.id, False)
    with pytest.raises(ValidationError):
        w.app.tasks.create_task(w.staff, "T", w.vol.id)                         # inactive volunteer


@pytest.mark.req("FR-VTM-01", "NFR-04")
@pytest.mark.parametrize("actor", ["vol", "client_user", "admin"])
def test_only_staff_create_tasks(w, actor):
    with pytest.raises(PermissionDenied):
        w.app.tasks.create_task(getattr(w, actor), "T", w.vol.id)


@pytest.mark.req("FR-VTM-02", "AC-23")
def test_volunteer_sees_only_own_tasks(w):
    mine = w.app.tasks.create_task(w.staff, "Mine", w.vol.id)
    w.app.tasks.create_task(w.staff, "Theirs", w.vol2.id)
    assert [t.id for t in w.app.tasks.my_tasks(w.vol)] == [mine.id]
    with pytest.raises(PermissionDenied):
        w.app.tasks.my_tasks(w.staff)                                           # staff use list_tasks instead


@pytest.mark.req("FR-VTM-02", "NFR-04")
def test_task_overview_for_staff_and_admin_only(w):
    w.app.tasks.create_task(w.staff, "A", w.vol.id)
    assert len(w.app.tasks.list_tasks(w.staff)) == 1 and len(w.app.tasks.list_tasks(w.admin)) == 1
    assert w.app.tasks.list_tasks(w.staff2) == []
    assert w.app.tasks.list_tasks(w.staff, status="completed") == []
    with pytest.raises(PermissionDenied):
        w.app.tasks.list_tasks(w.vol)


# ---------- status transitions (FR-VTM-03) ----------
@pytest.mark.req("FR-VTM-03", "AC-26")
def test_valid_status_progression_visible_to_staff(w):
    t = w.app.tasks.create_task(w.staff, "T", w.vol.id)
    assert w.app.tasks.update_status(w.vol, t.id, "in_progress").status == "in_progress"
    assert [x.status for x in w.app.tasks.list_tasks(w.staff)] == ["in_progress"]
    assert w.app.tasks.update_status(w.vol, t.id, "completed").status == "completed"
    assert [x.id for x in w.app.tasks.list_tasks(w.staff, status="completed")] == [t.id]


@pytest.mark.req("FR-VTM-03", "AC-26")
def test_not_started_can_jump_straight_to_completed(w):
    t = w.app.tasks.create_task(w.staff, "T", w.vol.id)
    assert w.app.tasks.update_status(w.vol, t.id, "completed").status == "completed"


@pytest.mark.req("FR-VTM-03")
def test_invalid_transitions(w):
    t = w.app.tasks.create_task(w.staff, "T", w.vol.id)
    for bad in ("not_started", "done", ""):
        with pytest.raises(ValidationError):
            w.app.tasks.update_status(w.vol, t.id, bad)
    w.app.tasks.update_status(w.vol, t.id, "completed")
    with pytest.raises(ConflictError):
        w.app.tasks.update_status(w.vol, t.id, "in_progress")                   # completed is final
    t2 = w.app.tasks.create_task(w.staff, "T2", w.vol.id)
    w.app.tasks.update_status(w.vol, t2.id, "in_progress")
    with pytest.raises(ConflictError):
        w.app.tasks.update_status(w.vol, t2.id, "in_progress")                  # no self transition


@pytest.mark.req("FR-VTM-03", "NFR-04", "UC-03")
def test_only_assigned_volunteer_updates_status(w):
    t = w.app.tasks.create_task(w.staff, "T", w.vol.id)
    with pytest.raises(PermissionDenied):
        w.app.tasks.update_status(w.vol2, t.id, "in_progress")
    with pytest.raises(PermissionDenied):
        w.app.tasks.update_status(w.staff, t.id, "in_progress")


# ---------- issue reports (FR-VTM-04) ----------
@pytest.mark.req("FR-VTM-04", "AC-25", "UC-03")
def test_issue_on_inventory_flags_item_for_staff_review(w):
    rice = receive_stock(w.app, w.staff, [item("Rice")])["Rice"]
    issue = w.app.tasks.submit_issue(w.vol, "damaged_food", "bags split", inventory_id=rice.id)
    assert issue.status == "open" and issue.reporter_id == w.vol.id
    assert w.app.inventory.get(w.staff, rice.id).flagged is True
    assert [i.id for i in w.app.tasks.list_issues(w.staff)] == [issue.id]
    assert w.app.inventory.get(w.staff, rice.id).condition == "available"       # volunteer report does not change stock


@pytest.mark.req("FR-VTM-04", "AC-25")
def test_issue_on_order_requires_assignment(w):
    o = w.app.orders.create_order(w.staff, w.client.id)
    with pytest.raises(PermissionDenied):
        w.app.tasks.submit_issue(w.vol, "incomplete_order", "missing tins", order_id=o.id)
    w.app.tasks.create_task(w.staff, "Pack", w.vol.id, order_id=o.id)
    w.app.tasks.submit_issue(w.vol, "incomplete_order", "missing tins", order_id=o.id)
    assert w.app.store.get("orders", o.id, type(o)).flagged is True


@pytest.mark.req("FR-VTM-04", "AC-25")
def test_issue_validation_reports_all_problems(w):
    with pytest.raises(ValidationError) as ei:
        w.app.tasks.submit_issue(w.vol, "weird", "   ")
    assert {"issue_type", "note", "target"} <= set(ei.value.fields)


@pytest.mark.req("FR-VTM-04", "NFR-04")
def test_issue_permissions_and_site(w):
    rice = receive_stock(w.app, w.staff, [item("Rice")])["Rice"]
    for actor in (w.staff, w.client_user, w.admin):
        with pytest.raises(PermissionDenied):
            w.app.tasks.submit_issue(actor, "damaged_food", "x", inventory_id=rice.id)
    far = receive_stock(w.app, w.staff2, [item("Beans")])["Beans"]
    with pytest.raises(PermissionDenied):
        w.app.tasks.submit_issue(w.vol, "damaged_food", "x", inventory_id=far.id)
    with pytest.raises(PermissionDenied):
        w.app.tasks.list_issues(w.vol)
    with pytest.raises(PermissionDenied):
        w.app.tasks.review_issue(w.vol, "ISS-0001")


@pytest.mark.req("FR-VTM-04", "UC-03")
def test_review_clears_flag_only_when_no_other_open_issue(w):
    rice = receive_stock(w.app, w.staff, [item("Rice")])["Rice"]
    a = w.app.tasks.submit_issue(w.vol, "damaged_food", "a", inventory_id=rice.id)
    b = w.app.tasks.submit_issue(w.vol2, "missing_stock", "b", inventory_id=rice.id)
    w.app.tasks.review_issue(w.staff, a.id)
    assert w.app.inventory.get(w.staff, rice.id).flagged is True                # b still open
    w.app.tasks.review_issue(w.staff, b.id)
    assert w.app.inventory.get(w.staff, rice.id).flagged is False
    with pytest.raises(ConflictError):
        w.app.tasks.review_issue(w.staff, a.id)
    assert w.app.tasks.list_issues(w.staff) == []
    assert len(w.app.tasks.list_issues(w.staff, status="reviewed")) == 2
