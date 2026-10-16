"""Client profile management (F-03). Staff own the profile; clients submit change requests."""
from typing import List

from .errors import NotFound, PermissionDenied, ValidationError, ConflictError
from .models import ChangeRequest, Client, Role, User
from .security import check_site, require
from .validators import clean_list

EDITABLE_FIELDS = {"name", "contact", "household_size", "allergies", "dietary", "cultural", "accessibility"}
LIST_FIELDS = {"allergies", "dietary", "cultural", "accessibility"}


def _normalise_changes(changes: dict) -> dict:
    if not changes:
        raise ValidationError("No changes supplied.", {"changes": "Provide at least one field to change."})
    unknown = set(changes) - EDITABLE_FIELDS
    if unknown:
        raise ValidationError("Unsupported fields.", {f: "This field cannot be stored." for f in unknown})
    out = {}
    errors = {}
    for key, value in changes.items():
        if key in LIST_FIELDS:
            out[key] = clean_list(value)
        elif key == "household_size":
            if not (isinstance(value, int) and not isinstance(value, bool) and value > 0):
                errors[key] = "Household size must be a whole number greater than zero."
            else:
                out[key] = value
        else:
            text = str(value).strip()
            if key == "name" and not text:
                errors[key] = "Name is required."
            out[key] = text
    if errors:
        raise ValidationError("Please correct the highlighted fields.", errors)
    return out


class ClientService:
    def __init__(self, ctx):
        self.ctx = ctx

    def create_client(self, actor: User, name: str, household_size: int, contact: str = "", allergies=None,
                      dietary=None, cultural=None, accessibility=None) -> Client:
        """FR-CPM-01/02: only information needed to provide food support is collected."""
        actor = self.ctx.refresh(actor)
        require(actor, "client.manage")
        values = _normalise_changes({
            "name": name, "household_size": household_size, "contact": contact,
            "allergies": allergies, "dietary": dietary, "cultural": cultural, "accessibility": accessibility})
        store = self.ctx.store
        with store.transaction():
            now = self.ctx.stamp()
            client = Client(id=store.next_id("CLI"), site_id=actor.site_id, created_at=now, updated_at=now, **values)
            store.put("clients", client)
            self.ctx.audit.log(actor, "client.created", "client", client.id)
        return client

    def update_client(self, actor: User, client_id: str, **changes) -> Client:
        """FR-CPM-03: authorised staff update a profile when circumstances change."""
        actor = self.ctx.refresh(actor)
        require(actor, "client.manage")
        values = _normalise_changes(changes)
        store = self.ctx.store
        with store.transaction():
            client = store.get("clients", client_id, Client)
            check_site(actor, client.site_id)
            self._apply(client, values)
            store.put("clients", client)
            # audit keeps field names only - never the sensitive values
            self.ctx.audit.log(actor, "client.updated", "client", client.id, {"fields": sorted(values)})
        return client

    def _apply(self, client: Client, values: dict) -> None:
        for k, v in values.items():
            setattr(client, k, v)
        client.updated_at = self.ctx.stamp()

    def get_client(self, actor: User, client_id: str) -> Client:
        actor = self.ctx.refresh(actor)
        require(actor, "client.view_full")  # volunteers, donors and clients are denied (NFR-04)
        client = self.ctx.store.get("clients", client_id, Client)
        check_site(actor, client.site_id)
        return client

    def search(self, actor: User, query: str = "") -> List[Client]:
        actor = self.ctx.refresh(actor)
        require(actor, "client.view_full")
        q = (query or "").strip().lower()
        return sorted(
            self.ctx.store.find("clients", Client,
                                lambda c: (actor.role == Role.ADMIN or c.site_id == actor.site_id)
                                and (not q or q in c.name.lower())),
            key=lambda c: c.id)

    # ---------- client change requests (UC-05) ----------
    def submit_change_request(self, actor: User, changes: dict) -> ChangeRequest:
        actor = self.ctx.refresh(actor)
        require(actor, "request.submit")
        if not actor.client_id:
            raise PermissionDenied("This account is not linked to a client profile.")
        values = _normalise_changes(changes)
        store = self.ctx.store
        with store.transaction():
            client = store.get("clients", actor.client_id, Client)
            req = ChangeRequest(id=store.next_id("REQ"), site_id=client.site_id, client_id=client.id,
                                requested_by=actor.id, changes=values, created_at=self.ctx.stamp())
            store.put("change_requests", req)
            self.ctx.audit.log(actor, "client.change_requested", "client", client.id, {"fields": sorted(values)})
        return req

    def list_change_requests(self, actor: User, status: str = "pending") -> List[ChangeRequest]:
        actor = self.ctx.refresh(actor)
        require(actor, "client.review_requests")
        return sorted(
            self.ctx.store.find("change_requests", ChangeRequest,
                                lambda r: r.site_id == actor.site_id and (not status or r.status == status)),
            key=lambda r: r.id)

    def apply_change_request(self, actor: User, request_id: str) -> Client:
        actor = self.ctx.refresh(actor)
        require(actor, "client.review_requests")
        store = self.ctx.store
        with store.transaction():
            req = store.get("change_requests", request_id, ChangeRequest)
            check_site(actor, req.site_id)
            if req.status != "pending":
                raise ConflictError(f"This request is already {req.status}.")
            client = store.get("clients", req.client_id, Client)
            self._apply(client, _normalise_changes(req.changes))
            req.status, req.decided_by, req.decided_at = "applied", actor.id, self.ctx.stamp()
            store.put("clients", client)
            store.put("change_requests", req)
            self.ctx.audit.log(actor, "client.change_applied", "client", client.id, {"fields": sorted(req.changes)})
        return client

    def reject_change_request(self, actor: User, request_id: str) -> ChangeRequest:
        actor = self.ctx.refresh(actor)
        require(actor, "client.review_requests")
        store = self.ctx.store
        with store.transaction():
            req = store.get("change_requests", request_id, ChangeRequest)
            check_site(actor, req.site_id)
            if req.status != "pending":
                raise ConflictError(f"This request is already {req.status}.")
            req.status, req.decided_by, req.decided_at = "rejected", actor.id, self.ctx.stamp()
            store.put("change_requests", req)
            self.ctx.audit.log(actor, "client.change_rejected", "client", req.client_id)
        return req
