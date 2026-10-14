"""Audit log (accountability). Details never contain client personal data - only ids and field names."""
from typing import Iterable, List, Optional

from .models import AuditEntry, User
from .security import require, resolve_site
from .validators import parse_date

AUDIT_GROUPS = {
    "role_change": ("user.role_changed",),
    "inventory_condition": ("inventory.condition_changed",),
    "order_completion": ("order.completed",),
}


class AuditService:
    def __init__(self, ctx):
        self.ctx = ctx

    def log(self, actor: Optional[User], action: str, entity: str, entity_id: str, details=None) -> None:
        store = self.ctx.store
        entry = AuditEntry(
            id=store.next_id("AUD"),
            timestamp=self.ctx.stamp(),
            user_id=actor.id if actor else "system",
            role=actor.role if actor else "system",
            site_id=actor.site_id if actor else "",
            action=action,
            entity=entity,
            entity_id=entity_id,
            details=details or {},
        )
        store.append("audit", entry)

    def search(self, actor: User, group: str = None, actions: Iterable[str] = None, user_id: str = None,
               start=None, end=None, site_id: str = None) -> List[AuditEntry]:
        """FR-REP-02: managers review audit records (role changes, inventory condition changes, order completion)."""
        actor = self.ctx.refresh(actor)
        require(actor, "audit.view")
        wanted = set(actions or [])
        if group:
            wanted |= set(AUDIT_GROUPS[group])
        start_d = parse_date(start, "start") if start else None
        end_d = parse_date(end, "end") if end else None
        site = resolve_site(actor, site_id)
        out = []
        for raw in self.ctx.store.data["audit"]:
            entry = AuditEntry.from_dict(raw)
            if wanted and entry.action not in wanted:
                continue
            if user_id and entry.user_id != user_id:
                continue
            if site and entry.site_id != site:
                continue
            day = parse_date(entry.timestamp[:10])
            if start_d and day < start_d:
                continue
            if end_d and day > end_d:
                continue
            out.append(entry)
        return out
