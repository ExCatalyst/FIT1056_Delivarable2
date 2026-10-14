"""Food inventory (F-02): search, availability, condition changes, stock movements."""
from datetime import date
from typing import Dict, List

from .errors import ValidationError
from .models import Condition, Donation, InventoryItem, StockMovement, User
from .security import check_site, require, resolve_site


def effective_condition(item: InventoryItem, today: date) -> str:
    """An item past its expiry date is treated as expired even if nobody has marked it yet."""
    if item.condition == Condition.AVAILABLE and item.expiry and item.expiry < today.isoformat():
        return Condition.EXPIRED
    return item.condition


def is_available(item: InventoryItem, today: date) -> bool:
    """FR-FIS-06: damaged, expired and missing items are never available."""
    return effective_condition(item, today) == Condition.AVAILABLE and item.quantity > 0


def record_movement(ctx, site_id: str, item: InventoryItem, delta: int, reason: str, ref_id: str = "") -> None:
    store = ctx.store
    store.append("movements", StockMovement(
        id=store.next_id("MOV"), timestamp=ctx.stamp(), site_id=site_id, inventory_id=item.id,
        item_name=item.name, delta=delta, reason=reason, ref_id=ref_id))


def receive_donation(ctx, actor: User, donation: Donation) -> List[InventoryItem]:
    """FR-FIS-01: accepted donation items are added to inventory (call inside a transaction)."""
    store = ctx.store
    created = []
    for raw in donation.items:
        item = InventoryItem(
            id=store.next_id("INV"), site_id=donation.site_id, name=raw["name"], quantity=raw["quantity"],
            unit=raw["unit"], expiry=raw["expiry"], allergens=raw["allergens"], dietary_tags=raw["dietary_tags"],
            category=raw["category"], donation_id=donation.id, created_at=ctx.stamp())
        if effective_condition(item, ctx.today()) == Condition.EXPIRED:
            item.condition = Condition.EXPIRED
        store.put("inventory", item)
        record_movement(ctx, donation.site_id, item, item.quantity, "donation_received", donation.id)
        created.append(item)
    return created


class InventoryService:
    def __init__(self, ctx):
        self.ctx = ctx

    def get(self, actor: User, item_id: str) -> InventoryItem:
        actor = self.ctx.refresh(actor)
        require(actor, "inventory.view")
        item = self.ctx.store.get("inventory", item_id, InventoryItem)
        check_site(actor, item.site_id)
        item.condition = effective_condition(item, self.ctx.today())
        return item

    def search(self, actor: User, query: str = "", only_available: bool = True, site_id: str = None) -> List[InventoryItem]:
        """Name/category search (NFR-05). By default only returns items that can be given out."""
        actor = self.ctx.refresh(actor)
        require(actor, "inventory.view")
        site = resolve_site(actor, site_id)
        today = self.ctx.today()
        q = (query or "").strip().lower()
        out = []
        for item in self.ctx.store.find("inventory", InventoryItem):
            if site and item.site_id != site:
                continue
            if q and q not in item.name.lower() and q not in item.category.lower():
                continue
            if only_available and not is_available(item, today):
                continue
            item.condition = effective_condition(item, today)
            out.append(item)
        return sorted(out, key=lambda i: (i.name.lower(), i.expiry))

    def mark_condition(self, actor: User, item_id: str, condition: str, note: str = "") -> InventoryItem:
        """FR-FIS-04/05: staff and volunteers set the condition; every change is logged."""
        actor = self.ctx.refresh(actor)
        require(actor, "inventory.mark_condition")
        if condition not in Condition.ALL:
            raise ValidationError("Unknown condition.", {"condition": "Choose available, damaged, expired or missing."})
        store = self.ctx.store
        with store.transaction():
            item = store.get("inventory", item_id, InventoryItem)
            check_site(actor, item.site_id)
            previous = item.condition
            if previous != condition:
                item.condition = condition
                store.put("inventory", item)
                self.ctx.audit.log(actor, "inventory.condition_changed", "inventory", item.id,
                                   {"previous": previous, "new": condition, "note": note})
        return item

    def sweep_expired(self, actor: User) -> List[str]:
        """Marks items past their expiry date as expired (logged) so records match reality."""
        actor = self.ctx.refresh(actor)
        require(actor, "inventory.mark_condition")
        store = self.ctx.store
        changed = []
        with store.transaction():
            for item in store.find("inventory", InventoryItem):
                if actor.role != "admin" and item.site_id != actor.site_id:
                    continue
                if effective_condition(item, self.ctx.today()) == Condition.EXPIRED and item.condition == Condition.AVAILABLE:
                    item.condition = Condition.EXPIRED
                    store.put("inventory", item)
                    self.ctx.audit.log(actor, "inventory.condition_changed", "inventory", item.id,
                                       {"previous": Condition.AVAILABLE, "new": Condition.EXPIRED, "note": "expiry date passed"})
                    changed.append(item.id)
        return changed

    def low_stock(self, actor: User, threshold: int = 10, site_id: str = None) -> List[Dict]:
        """Low-stock warnings (Bob's scenario): total available quantity per item name below the threshold."""
        totals: Dict[str, int] = {}
        for item in self.search(actor, site_id=site_id):
            totals[item.name.lower()] = totals.get(item.name.lower(), 0) + item.quantity
        return sorted(({"name": n, "total": t} for n, t in totals.items() if t < threshold), key=lambda r: r["total"])
