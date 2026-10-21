"""Food order / hamper management (F-04).

Stock rule: inventory is reduced ONLY when staff complete an order (FR-FIS-02). While an order is being
packed, quantity changes only edit the draft order and never change inventory directly.
"""
from typing import Any, Dict, List, Tuple

from .errors import ConflictError, NotFound, PermissionDenied, ValidationError
from .inventory import is_available, record_movement
from .models import Client, InventoryItem, Order, OrderStatus, Role, Task, User
from .respectful import check_respectful
from .security import check_site, has_permission, require
from .validators import parse_datetime, require_positive_int

PICKUP_LABELS = {
    OrderStatus.PREPARING: "Preparing",
    OrderStatus.READY: "Ready for pickup",
    OrderStatus.COMPLETED: "Collected",
    OrderStatus.CANCELLED: "Cancelled",
}


def allergen_conflicts(client: Client, item: InventoryItem) -> List[str]:
    return sorted(set(client.allergies) & set(item.allergens))


def dietary_warnings(client: Client, item: InventoryItem) -> List[str]:
    """FR-FOM-04: warn when an item is not tagged as meeting a recorded dietary/cultural requirement."""
    needs = set(client.dietary) | set(client.cultural)
    return [f"{item.name} is not tagged as meeting '{need}'. Please check before packing."
            for need in sorted(needs - set(item.dietary_tags))]


class OrderService:
    def __init__(self, ctx):
        self.ctx = ctx

    # ---------- helpers ----------
    def _task_for_volunteer(self, actor: User, order_id: str) -> bool:
        return any(t.order_id == order_id and t.assigned_to == actor.id
                   for t in self.ctx.store.find("tasks", Task))

    def _editable_order(self, order: Order) -> None:
        if order.status != OrderStatus.PREPARING:
            raise ConflictError(f"The order is {order.status} and can no longer be changed.")

    def _find_line(self, order: Order, inventory_id: str):
        for line in order.items:
            if line["inventory_id"] == inventory_id:
                return line
        return None

    # ---------- create / build ----------
    def create_order(self, actor: User, client_id: str) -> Order:
        """FR-FOM-01: create a hamper/pickup order for a registered client."""
        actor = self.ctx.refresh(actor)
        require(actor, "order.manage")
        store = self.ctx.store
        with store.transaction():
            client = store.get("clients", client_id, Client)
            check_site(actor, client.site_id)
            order = Order(id=store.next_id("ORD"), site_id=client.site_id, client_id=client.id,
                          pickup_ref=f"P-{store.next_number('PICKUP'):04d}", status=OrderStatus.PREPARING,
                          created_by=actor.id, created_at=self.ctx.stamp(), updated_at=self.ctx.stamp())
            store.put("orders", order)
            self.ctx.audit.log(actor, "order.created", "order", order.id)
        return order

    def selectable_items(self, actor: User, order_id: str) -> List[InventoryItem]:
        """FR-FOM-03 / FR-FIS-06: available items only, with the client's allergens excluded automatically."""
        actor = self.ctx.refresh(actor)
        require(actor, "order.manage")
        order = self.ctx.store.get("orders", order_id, Order)
        check_site(actor, order.site_id)
        client = self.ctx.store.get("clients", order.client_id, Client)
        today = self.ctx.today()
        items = self.ctx.store.find(
            "inventory", InventoryItem,
            lambda i: i.site_id == order.site_id and is_available(i, today) and not allergen_conflicts(client, i))
        return sorted(items, key=lambda i: (i.name.lower(), i.expiry))

    def add_item(self, actor: User, order_id: str, inventory_id: str, quantity: int) -> Tuple[Order, List[str]]:
        """Adds an item; returns (order, warnings). Allergen conflicts are blocked, dietary mismatches warn."""
        actor = self.ctx.refresh(actor)
        require(actor, "order.manage")
        require_positive_int(quantity)
        store = self.ctx.store
        with store.transaction():
            order = store.get("orders", order_id, Order)
            check_site(actor, order.site_id)
            self._editable_order(order)
            client = store.get("clients", order.client_id, Client)
            item = store.get("inventory", inventory_id, InventoryItem)
            if item.site_id != order.site_id:
                raise ConflictError("That item belongs to another site.")
            if not is_available(item, self.ctx.today()):
                raise ConflictError(f"{item.name} is not available (damaged, expired, missing or out of stock).")
            conflicts = allergen_conflicts(client, item)
            if conflicts:
                raise ValidationError(f"{item.name} cannot be added for this client.",
                                      {"inventory_id": "Contains a recorded allergen."})
            line = self._find_line(order, item.id)
            new_total = (line["quantity"] if line else 0) + quantity
            if new_total > item.quantity:
                raise ConflictError(f"Only {item.quantity} {item.name} available.")
            if line:
                line["quantity"] = new_total
            else:
                order.items.append({"inventory_id": item.id, "name": item.name, "quantity": quantity})
            order.updated_at = self.ctx.stamp()
            store.put("orders", order)
            self.ctx.audit.log(actor, "order.item_added", "order", order.id, {"inventory_id": item.id, "quantity": quantity})
            warnings = dietary_warnings(client, item)
        return order, warnings

    def remove_item(self, actor: User, order_id: str, inventory_id: str) -> Order:
        actor = self.ctx.refresh(actor)
        require(actor, "order.manage")
        store = self.ctx.store
        with store.transaction():
            order = store.get("orders", order_id, Order)
            check_site(actor, order.site_id)
            self._editable_order(order)
            line = self._find_line(order, inventory_id)
            if line is None:
                raise NotFound("That item is not on the order.")
            order.items.remove(line)
            order.updated_at = self.ctx.stamp()
            store.put("orders", order)
            self.ctx.audit.log(actor, "order.item_removed", "order", order.id, {"inventory_id": inventory_id})
        return order

    def update_item_quantity(self, actor: User, order_id: str, inventory_id: str, quantity: int) -> Order:
        """Staff, or a volunteer assigned to the order, can correct a draft quantity. Does NOT change inventory."""
        actor = self.ctx.refresh(actor)
        require_positive_int(quantity)
        store = self.ctx.store
        with store.transaction():
            order = store.get("orders", order_id, Order)
            check_site(actor, order.site_id)
            if has_permission(actor, "order.manage"):
                pass
            elif has_permission(actor, "order.edit_quantity") and self._task_for_volunteer(actor, order.id):
                pass
            else:
                raise PermissionDenied("You are not assigned to this order.")
            self._editable_order(order)
            line = self._find_line(order, inventory_id)
            if line is None:
                raise NotFound("That item is not on the order.")
            item = store.get("inventory", inventory_id, InventoryItem)
            if quantity > item.quantity:
                raise ConflictError(f"Only {item.quantity} {item.name} available.")
            previous = line["quantity"]
            line["quantity"] = quantity
            order.updated_at = self.ctx.stamp()
            store.put("orders", order)
            self.ctx.audit.log(actor, "order.quantity_updated", "order", order.id,
                               {"inventory_id": inventory_id, "previous": previous, "new": quantity})
        return order

    def add_substitution_note(self, actor: User, order_id: str, note: str) -> Order:
        """FR-FOM-05 / NFR-03: respectful substitution note."""
        actor = self.ctx.refresh(actor)
        require(actor, "order.manage")
        note = (note or "").strip()
        if not note or len(note) > 500:
            raise ValidationError("Invalid note.", {"note": "Enter a note of up to 500 characters."})
        check_respectful(note)
        store = self.ctx.store
        with store.transaction():
            order = store.get("orders", order_id, Order)
            check_site(actor, order.site_id)
            if order.status == OrderStatus.CANCELLED:
                raise ConflictError("The order is cancelled.")
            order.substitution_notes.append({"note": note, "by": actor.id, "at": self.ctx.stamp()})
            order.updated_at = self.ctx.stamp()
            store.put("orders", order)
            self.ctx.audit.log(actor, "order.substitution_noted", "order", order.id)
        return order

    # ---------- status ----------
    def set_status(self, actor: User, order_id: str, new_status: str) -> Order:
        """preparing <-> ready, or cancel. Completion has its own method because it changes stock."""
        actor = self.ctx.refresh(actor)
        require(actor, "order.manage")
        allowed = {
            OrderStatus.PREPARING: {OrderStatus.READY, OrderStatus.CANCELLED},
            OrderStatus.READY: {OrderStatus.PREPARING, OrderStatus.CANCELLED},
        }
        store = self.ctx.store
        with store.transaction():
            order = store.get("orders", order_id, Order)
            check_site(actor, order.site_id)
            if new_status == OrderStatus.COMPLETED:
                raise ValidationError("Use complete_order to complete an order.", {"status": "Orders are completed separately."})
            if new_status not in allowed.get(order.status, set()):
                raise ConflictError(f"An order that is {order.status} cannot become {new_status}.")
            if new_status == OrderStatus.READY and not order.items:
                raise ConflictError("An empty order cannot be marked ready.")
            order.status = new_status
            order.updated_at = self.ctx.stamp()
            store.put("orders", order)
            self.ctx.audit.log(actor, f"order.{new_status}", "order", order.id)
        return order

    def complete_order(self, actor: User, order_id: str) -> Order:
        """FR-FIS-02/03: the single point where stock is reduced. All-or-nothing; never below zero."""
        actor = self.ctx.refresh(actor)
        require(actor, "order.complete")  # volunteers cannot finalise an order
        store = self.ctx.store
        with store.transaction():
            order = store.get("orders", order_id, Order)
            check_site(actor, order.site_id)
            if order.status not in (OrderStatus.PREPARING, OrderStatus.READY):
                raise ConflictError(f"The order is already {order.status}.")
            if not order.items:
                raise ConflictError("An empty order cannot be completed.")
            loaded = []
            for line in order.items:  # validate everything first
                item = store.get("inventory", line["inventory_id"], InventoryItem)
                if not is_available(item, self.ctx.today()):
                    raise ConflictError(f"{item.name} is no longer available. Remove or substitute it first.")
                if line["quantity"] > item.quantity:
                    raise ConflictError(f"Not enough {item.name} in stock (available {item.quantity}).")
                loaded.append((line, item))
            total = 0
            for line, item in loaded:  # then apply
                item.quantity -= line["quantity"]
                total += line["quantity"]
                store.put("inventory", item)
                record_movement(self.ctx, order.site_id, item, -line["quantity"], "order_completed", order.id)
            order.status = OrderStatus.COMPLETED
            order.completed_by, order.completed_at = actor.id, self.ctx.stamp()
            order.updated_at = order.completed_at
            store.put("orders", order)
            self.ctx.audit.log(actor, "order.completed", "order", order.id, {"lines": len(loaded), "total_quantity": total})
        return order

    def set_pickup_time(self, actor: User, order_id: str, when) -> Order:
        """FR-FOM-06: record the pickup time chosen by the client."""
        actor = self.ctx.refresh(actor)
        require(actor, "order.manage")
        moment = parse_datetime(when, "pickup_time")
        if moment < self.ctx.now():
            raise ValidationError("Pickup time is in the past.", {"pickup_time": "Choose a future time."})
        store = self.ctx.store
        with store.transaction():
            order = store.get("orders", order_id, Order)
            check_site(actor, order.site_id)
            if order.status in (OrderStatus.COMPLETED, OrderStatus.CANCELLED):
                raise ConflictError(f"The order is {order.status}.")
            order.pickup_time = moment.isoformat(timespec="minutes")
            order.updated_at = self.ctx.stamp()
            store.put("orders", order)
            self.ctx.audit.log(actor, "order.pickup_set", "order", order.id)
        return order

    # ---------- role-specific views ----------
    def get_order_view(self, actor: User, order_id: str) -> Dict[str, Any]:
        """FR-FOM-02 / NFR-04: what each role may see for one order."""
        actor = self.ctx.refresh(actor)
        order = self.ctx.store.get("orders", order_id, Order)
        client = self.ctx.store.get("clients", order.client_id, Client)
        if actor.role == Role.CLIENT:
            if actor.client_id != order.client_id:
                raise PermissionDenied("This is not your order.")
            return self._client_view(order)
        check_site(actor, order.site_id)
        if has_permission(actor, "order.view_full"):
            return {
                "order": order.to_dict(),
                "client": {"id": client.id, "name": client.name, "allergies": client.allergies,
                           "dietary": client.dietary, "cultural": client.cultural,
                           "accessibility": client.accessibility, "household_size": client.household_size},
                "pickup_status": PICKUP_LABELS[order.status],
            }
        if has_permission(actor, "order.view_task") and self._task_for_volunteer(actor, order.id):
            # minimum packing information only: items, quantities, pickup reference, one safety flag
            flag = bool(client.allergies or client.dietary or client.cultural)
            return {
                "order_id": order.id,
                "pickup_ref": order.pickup_ref,
                "status": order.status,
                "items": [{"name": l["name"], "quantity": l["quantity"]} for l in order.items],
                "safety_flag": flag,
                "safety_message": "Allergy/dietary requirement applies - check with staff if unsure." if flag else "",
            }
        raise PermissionDenied("You do not have access to this order.")

    def _client_view(self, order: Order) -> Dict[str, Any]:
        return {"order_id": order.id, "pickup_ref": order.pickup_ref, "pickup_time": order.pickup_time,
                "pickup_status": PICKUP_LABELS[order.status]}

    def my_orders(self, actor: User) -> List[Dict[str, Any]]:
        """FR-FOM-07: a client sees the pickup status of their own orders only."""
        actor = self.ctx.refresh(actor)
        require(actor, "order.view_own")
        return [self._client_view(o) for o in sorted(
            self.ctx.store.find("orders", Order, lambda o: o.client_id == actor.client_id), key=lambda o: o.id)]

    def list_orders(self, actor: User, status: str = None) -> List[Order]:
        actor = self.ctx.refresh(actor)
        require(actor, "order.view_full")
        return sorted(self.ctx.store.find(
            "orders", Order,
            lambda o: (actor.role == Role.ADMIN or o.site_id == actor.site_id) and (not status or o.status == status)),
            key=lambda o: o.id)
