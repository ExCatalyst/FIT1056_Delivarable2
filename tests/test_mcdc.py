"""MC/DC (modified condition / decision coverage) on two multi-condition decisions.

Decision 1  inventory.is_available():   D = A and B and C
    A = stored condition is 'available'    B = expiry date has NOT passed    C = quantity > 0
    n = 3 conditions  ->  n + 1 = 4 tests; each condition is flipped alone and flips the outcome.

        test | A B C | D | independence pair
        T1   | T T T | T | -
        T2   | F T T | F | (T1,T2) shows A
        T3   | T F T | F | (T1,T3) shows B
        T4   | T T F | F | (T1,T4) shows C

Decision 2  orders.update_item_quantity() authorisation:   D = M or (E and T)
    M = role has order.manage (staff)   E = role has order.edit_quantity (volunteer)   T = user has a task on the order
    Achievable role/task combinations give 5 vectors; every condition has an independence pair.

        test | M E T | D | independence pair
        V1   | T F F | T | -
        V2   | F F F | F | (V1,V2) shows M   (E,T fixed at F,F)
        V3   | F T T | T | -
        V4   | F T F | F | (V3,V4) shows T
        V5   | F F T | F | (V3,V5) shows E   (admin who still holds an old volunteer task)
"""
from datetime import date

import pytest

from app.errors import PermissionDenied
from app.inventory import is_available
from app.models import InventoryItem
from helpers import item, receive_stock

TODAY = date(2026, 9, 15)


def make_item(condition, expiry, qty):
    return InventoryItem(id="INV-1", site_id="S1", name="x", quantity=qty, unit="u", expiry=expiry, condition=condition)


@pytest.mark.req("FR-FIS-06", "AC-09")
@pytest.mark.parametrize("condition,expiry,qty,expected", [
    ("available", "2026-09-15", 5, True),     # T1: A=T B=T C=T
    ("damaged",   "2026-09-15", 5, False),    # T2: A=F
    ("available", "2026-09-14", 5, False),    # T3: B=F
    ("available", "2026-09-15", 0, False),    # T4: C=F
], ids=["T1-all-true", "T2-A-false", "T3-B-false", "T4-C-false"])
def test_mcdc_is_available(condition, expiry, qty, expected):
    assert is_available(make_item(condition, expiry, qty), TODAY) is expected


@pytest.fixture
def draft(w):
    stock = receive_stock(w.app, w.staff, [item("Rice", 20)])
    free = w.app.clients.create_client(w.staff, "Max", 1)
    order = w.app.orders.create_order(w.staff, free.id)
    w.app.orders.add_item(w.staff, order.id, stock["Rice"].id, 5)
    w.app.tasks.create_task(w.staff, "Pack", w.vol.id, order_id=order.id)         # vol is assigned, vol2 is not
    return w, order, stock["Rice"].id


def attempt(w, actor, order, inv):
    try:
        w.app.orders.update_item_quantity(actor, order.id, inv, 6)
        return True
    except PermissionDenied:
        return False


@pytest.mark.req("FR-FOM-05", "NFR-04", "UC-03")
def test_mcdc_update_quantity_authorisation(draft):
    w, order, inv = draft
    assert attempt(w, w.staff, order, inv) is True                 # V1  M=T E=F T=F
    assert attempt(w, w.admin, order, inv) is False                # V2  M=F E=F T=F
    assert attempt(w, w.vol, order, inv) is True                   # V3  M=F E=T T=T
    assert attempt(w, w.vol2, order, inv) is False                 # V4  M=F E=T T=F
    # V5: vol3 is given a task, then promoted to admin -> keeps the task (T) but loses edit_quantity (E=F)
    vol3 = w.app.auth.create_user(w.admin, "lee", "password1", "volunteer", "S1")
    w.app.tasks.create_task(w.staff, "Pack too", vol3.id, order_id=order.id)
    assert attempt(w, vol3, order, inv) is True                    # sanity: still V3 before promotion
    w.app.auth.change_role(w.admin, vol3.id, "admin")
    assert attempt(w, vol3, order, inv) is False                   # V5  M=F E=F T=T
