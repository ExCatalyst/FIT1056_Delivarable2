"""Donation management (F-01). Staff record donation offers; donors do not log in (UC-06)."""
from typing import List

from .errors import ConflictError, ValidationError
from .inventory import receive_donation
from .models import Donation, DonationStatus, User
from .security import check_site, require, resolve_site
from .validators import normalise_donation_items

COLLECTION_METHODS = ("pickup", "drop_off")


class DonationService:
    def __init__(self, ctx):
        self.ctx = ctx

    def record_offer(self, actor: User, donor_ref: str, items: list, collection_method: str) -> Donation:
        """FR-DM-01..03: record a donation offer; rejects missing fields and zero/negative quantities."""
        actor = self.ctx.refresh(actor)
        require(actor, "donation.record")
        errors = {}
        if not (donor_ref or "").strip():
            errors["donor_ref"] = "Donor reference is required."
        if collection_method not in COLLECTION_METHODS:
            errors["collection_method"] = "Choose pickup or drop_off."
        try:
            cleaned = normalise_donation_items(items, self.ctx.today())
        except ValidationError as exc:
            errors.update(exc.fields)
            cleaned = None
        if errors:
            raise ValidationError("Please correct the highlighted fields.", errors)
        store = self.ctx.store
        with store.transaction():
            donation = Donation(id=store.next_id("DON"), site_id=actor.site_id, donor_ref=donor_ref.strip(),
                                items=cleaned, collection_method=collection_method,
                                status=DonationStatus.OFFERED, created_by=actor.id, created_at=self.ctx.stamp())
            store.put("donations", donation)
            self.ctx.audit.log(actor, "donation.offer_recorded", "donation", donation.id, {"items": len(cleaned)})
        return donation

    def update_status(self, actor: User, donation_id: str, new_status: str) -> Donation:
        """FR-DM-04 + FR-FIS-01: offered -> received (adds stock) or rejected."""
        actor = self.ctx.refresh(actor)
        require(actor, "donation.decide")
        if new_status not in (DonationStatus.RECEIVED, DonationStatus.REJECTED):
            raise ValidationError("Invalid status.", {"status": "Choose received or rejected."})
        store = self.ctx.store
        with store.transaction():
            donation = store.get("donations", donation_id, Donation)
            check_site(actor, donation.site_id)
            if donation.status != DonationStatus.OFFERED:
                raise ConflictError(f"This donation is already {donation.status}.")
            donation.status = new_status
            donation.decided_by = actor.id
            donation.updated_at = self.ctx.stamp()
            store.put("donations", donation)
            if new_status == DonationStatus.RECEIVED:
                receive_donation(self.ctx, actor, donation)
            self.ctx.audit.log(actor, f"donation.{new_status}", "donation", donation.id)
        return donation

    def get(self, actor: User, donation_id: str) -> Donation:
        actor = self.ctx.refresh(actor)
        require(actor, "donation.view") if actor.role == "admin" else require(actor, "donation.record")
        donation = self.ctx.store.get("donations", donation_id, Donation)
        check_site(actor, donation.site_id)
        return donation

    def list(self, actor: User, status: str = None, site_id: str = None) -> List[Donation]:
        actor = self.ctx.refresh(actor)
        require(actor, "donation.view") if actor.role == "admin" else require(actor, "donation.record")
        site = resolve_site(actor, site_id)
        return sorted(
            self.ctx.store.find("donations", Donation,
                                lambda d: (not site or d.site_id == site) and (not status or d.status == status)),
            key=lambda d: d.id)
