"""Small builders shared by the test modules."""


def item(name, qty=10, expiry="2027-01-01", allergens=None, tags=None, category="", unit="unit"):
    return {"name": name, "quantity": qty, "expiry": expiry, "allergens": allergens or [],
            "dietary_tags": tags or [], "category": category, "unit": unit}


def receive_stock(app, staff, items, donor="DONOR-1"):
    """Records a donation and marks it received. Returns {item name: InventoryItem}."""
    donation = app.donations.record_offer(staff, donor, items, "drop_off")
    app.donations.update_status(staff, donation.id, "received")
    return {i.name: i for i in app.inventory.search(staff, only_available=False)
            if i.donation_id == donation.id}
