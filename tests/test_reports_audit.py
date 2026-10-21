"""Service tests: Reporting and Audit Export F-06 (FR-REP-01..03, AC-28, AC-29)."""
import json
from datetime import date

import pytest

from app.errors import PermissionDenied, ValidationError
from app.reports import ReportService
from helpers import item, receive_stock

DAY = "2026-09-15"


@pytest.fixture
def traded(w):
    """S1: Rice 20 + Soup 5 received, 8 Rice + 2 Soup distributed. S2: Beans 7 received."""
    stock = receive_stock(w.app, w.staff, [item("Rice", 20), item("Soup", 5)])
    receive_stock(w.app, w.staff2, [item("Beans", 7)])
    free = w.app.clients.create_client(w.staff, "Max", 1)
    o = w.app.orders.create_order(w.staff, free.id)
    w.app.orders.add_item(w.staff, o.id, stock["Rice"].id, 8)
    w.app.orders.add_item(w.staff, o.id, stock["Soup"].id, 2)
    w.app.orders.complete_order(w.staff, o.id)
    return w


@pytest.mark.req("FR-REP-01", "AC-28")
def test_stock_movement_report_values(traded):
    r = traded.app.reports.stock_movement_report(traded.staff, DAY, DAY)
    assert r["site_id"] == "S1"
    assert r["rows"] == [{"item": "Rice", "received": 20, "distributed": 8, "net": 12},
                         {"item": "Soup", "received": 5, "distributed": 2, "net": 3}]
    assert r["totals"] == {"received": 25, "distributed": 10}


@pytest.mark.req("FR-REP-01", "AC-28")
@pytest.mark.parametrize("start,end,has_rows", [
    ("2026-09-15", "2026-09-15", True),      # start == end == the day itself (inclusive boundaries)
    ("2026-09-14", "2026-09-15", True),
    ("2026-09-15", "2026-09-16", True),
    ("2026-09-16", "2026-09-20", False),     # day after
    ("2026-09-01", "2026-09-14", False),     # day before
])
def test_report_date_range_boundaries(traded, start, end, has_rows):
    assert bool(traded.app.reports.stock_movement_report(traded.staff, start, end)["rows"]) is has_rows


@pytest.mark.req("FR-REP-01")
@pytest.mark.parametrize("start,end", [("2026-09-16", "2026-09-15"), ("bad", DAY), (DAY, "15/09/2026"), (None, DAY)])
def test_report_invalid_ranges_rejected(traded, start, end):
    with pytest.raises(ValidationError):
        traded.app.reports.stock_movement_report(traded.staff, start, end)


@pytest.mark.req("FR-REP-01", "NFR-04")
def test_report_site_filter_and_admin_all_sites(traded):
    r = traded.app.reports
    assert r.stock_movement_report(traded.admin, DAY, DAY)["site_id"] == "ALL"
    assert {x["item"] for x in r.stock_movement_report(traded.admin, DAY, DAY)["rows"]} == {"Rice", "Soup", "Beans"}
    assert [x["item"] for x in r.stock_movement_report(traded.admin, DAY, DAY, site_id="S2")["rows"]] == ["Beans"]
    with pytest.raises(PermissionDenied):
        r.stock_movement_report(traded.staff, DAY, DAY, site_id="S2")


@pytest.mark.req("FR-REP-03", "NFR-04", "AC-28")
@pytest.mark.parametrize("actor", ["vol", "client_user"])
def test_report_denied_to_volunteers_and_clients(traded, actor):
    with pytest.raises(PermissionDenied):
        traded.app.reports.stock_movement_report(getattr(traded, actor), DAY, DAY)
    with pytest.raises(PermissionDenied):
        traded.app.reports.demand_trend_report(getattr(traded, actor), DAY, DAY)


@pytest.mark.req("FR-REP-03", "AC-28")
def test_reports_contain_no_client_data(traded):
    report = traded.app.reports.stock_movement_report(traded.staff, DAY, DAY)
    trend = traded.app.reports.demand_trend_report(traded.staff, DAY, DAY)
    assert all(set(r) == {"item", "received", "distributed", "net"} for r in report["rows"])
    dump = (json.dumps(report) + json.dumps(trend)).lower()
    for secret in ("lola", "max", "allerg", "client", "0123"):
        assert secret not in dump


@pytest.mark.req("FR-REP-01")
def test_demand_trend_weekly_and_monthly(traded):
    iso = date(2026, 9, 15).isocalendar()
    weekly = traded.app.reports.demand_trend_report(traded.staff, DAY, DAY)
    assert weekly["rows"] == [{"period": f"{iso[0]}-W{iso[1]:02d}", "item": "Rice", "distributed": 8},
                              {"period": f"{iso[0]}-W{iso[1]:02d}", "item": "Soup", "distributed": 2}]
    monthly = traded.app.reports.demand_trend_report(traded.staff, DAY, DAY, bucket="month")
    assert {r["period"] for r in monthly["rows"]} == {"2026-09"}


@pytest.mark.req("FR-REP-01", "AC-28")
def test_csv_export(traded):
    rows = traded.app.reports.stock_movement_report(traded.staff, DAY, DAY)["rows"]
    lines = ReportService.to_csv(rows, ["item", "received", "distributed", "net"]).strip().splitlines()
    assert lines[0] == "item,received,distributed,net"
    assert lines[1] == "Rice,20,8,12" and len(lines) == 3
    assert ReportService.to_csv([{"item": "x", "extra": 1}], ["item"]).strip().splitlines() == ["item", "x"]


# ---------- audit (FR-REP-02, AC-29) ----------
@pytest.fixture
def audited(traded):
    w = traded
    w.app.auth.change_role(w.admin, w.vol2.id, "staff")
    stock = w.app.inventory.search(w.staff, "rice")[0]
    w.app.inventory.mark_condition(w.staff, stock.id, "damaged")
    return w


@pytest.mark.req("FR-REP-02", "AC-29")
@pytest.mark.parametrize("group,action", [("role_change", "user.role_changed"),
                                          ("inventory_condition", "inventory.condition_changed"),
                                          ("order_completion", "order.completed")])
def test_audit_filters_by_group(audited, group, action):
    entries = audited.app.audit.search(audited.admin, group=group)
    assert entries and {e.action for e in entries} == {action}
    assert all(e.user_id and e.timestamp and e.action for e in entries)            # user, time, action present


@pytest.mark.req("FR-REP-02", "AC-29")
def test_audit_filters_by_user_action_and_site(audited):
    w = audited
    assert {e.user_id for e in w.app.audit.search(w.admin, user_id=w.admin.id)} == {w.admin.id}
    only = w.app.audit.search(w.admin, actions=["order.completed", "user.role_changed"])
    assert {e.action for e in only} == {"order.completed", "user.role_changed"}
    assert {e.site_id for e in w.app.audit.search(w.admin, site_id="S2")} <= {"S2"}


@pytest.mark.req("FR-REP-02", "AC-29")
@pytest.mark.parametrize("start,end,found", [(DAY, DAY, True), ("2026-09-16", None, False), (None, "2026-09-14", False),
                                             ("2026-09-14", "2026-09-16", True)])
def test_audit_date_range_boundaries(audited, start, end, found):
    assert bool(audited.app.audit.search(audited.admin, start=start, end=end)) is found


@pytest.mark.req("FR-REP-02", "NFR-04")
@pytest.mark.parametrize("actor", ["staff", "vol", "client_user"])
def test_audit_is_admin_only(audited, actor):
    with pytest.raises(PermissionDenied):
        audited.app.audit.search(getattr(audited, actor))


@pytest.mark.req("FR-REP-02", "NFR-04")
def test_audit_never_contains_client_personal_data(audited):
    w = audited
    w.app.clients.update_client(w.staff, w.client.id, allergies=["shellfish"], contact="PRIVATE-9")
    dump = json.dumps([e.to_dict() for e in w.app.audit.search(w.admin)])
    for secret in ("Lola", "shellfish", "PRIVATE-9", "password1"):
        assert secret not in dump


@pytest.mark.req("FR-REP-02")
def test_system_actor_entries_supported(w):
    w.app.store.data["audit"].clear()
    with w.app.store.transaction():
        w.app.audit.log(None, "system.job", "system", "-")
    assert w.app.audit.search(w.admin)[0].user_id == "system"
