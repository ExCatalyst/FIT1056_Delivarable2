"""Searchable inventory and explicit condition changes."""
from datetime import date

import streamlit as st

from app.models import Condition
from app.security import has_permission
from ui.common import label, save_action, site_filter, table


def show(app, user):
    """Filter visible stock and let permitted users update a batch condition."""
    st.title("Inventory")
    st.caption("Damaged, expired and missing food is excluded from hamper selection.")
    site = site_filter(user, "inventory_site")
    query = st.text_input("Search item name or category", key="inventory_query")
    condition = st.selectbox("Condition", ["All", *Condition.ALL], format_func=label)
    threshold = st.number_input("Low-stock reminder threshold", min_value=1, value=10)
    low_only = st.checkbox("Show low-stock items only")
    expiring = st.checkbox("Show food expiring in the next 7 days")
    items = app.inventory.search(user, query=query, only_available=False, site_id=site)
    low = app.inventory.low_stock(user, threshold=threshold, site_id=site)
    low_names = {row["name"] for row in low}
    filtered = []
    today = app.ctx.today()
    for item in items:
        if condition != "All" and item.condition != condition:
            continue
        if low_only and item.name.lower() not in low_names:
            continue
        if expiring:
            days = (date.fromisoformat(item.expiry) - today).days
            if item.condition != "available" or not 0 <= days <= 7:
                continue
        filtered.append(item)
    table([{"Batch": i.id, "Item": i.name, "Quantity": i.quantity, "Unit": i.unit, "Site": i.site_id,
            "Expiry": i.expiry, "Condition": label(i.condition), "Needs review": "Yes" if i.flagged else "No",
            "Allergens": ", ".join(i.allergens), "Suitability": ", ".join(i.dietary_tags)} for i in filtered],
          "No stock matches these filters. Received donations appear here.")
    if filtered and has_permission(user, "inventory.mark_condition"):
        st.subheader("Update an item's condition")
        selected = st.selectbox("Stock batch", filtered, format_func=lambda i: f"{i.name} · {i.id}")
        with st.form(f"condition_{selected.id}", enter_to_submit=False):
            new_condition = st.selectbox("New condition", list(Condition.ALL), format_func=label)
            note = st.text_input("Reason / note")
            confirmed = st.checkbox("I checked the item. This changes its availability for food support.")
            submitted = st.form_submit_button("Save condition", type="primary")
        if submitted:
            if not confirmed:
                st.error("Confirm you checked the item before changing its condition.")
            else:
                save_action("Item condition saved.", app.inventory.mark_condition,
                            user, selected.id, new_condition, note)
