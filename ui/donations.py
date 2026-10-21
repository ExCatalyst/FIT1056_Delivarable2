"""Donation entry and decisions for staff; read-only review for admins."""
from datetime import date, timedelta

import streamlit as st

from app.models import Role
from ui.common import cancel_button, label, save_action, site_filter, split_list, table


def record_form(app, user):
    """Collect one or more item lines for a staff-recorded donation offer."""
    st.subheader("Record a donation offer")
    st.caption("Record the details supplied by the donor. Stock increases only after the offer is marked Received.")
    count = st.number_input("Number of different items", min_value=1, max_value=20, value=1, key="donation_count")
    with st.form("donation_form", enter_to_submit=False):
        donor = st.text_input("Donor reference *", key="donation_donor",
                              help="Use the organisation's donor reference. Do not collect unnecessary personal details.")
        method = st.selectbox("Collection method", ["drop_off", "pickup"], format_func=label, key="donation_method")
        items = []
        for i in range(count):
            st.markdown(f"**Item {i + 1}**")
            name = st.text_input("Item name *", key=f"donation_name_{i}")
            columns = st.columns(2)
            quantity = columns[0].number_input("Quantity *", min_value=0, value=1, step=1, key=f"donation_quantity_{i}")
            unit = columns[1].text_input("Unit", value="unit", key=f"donation_unit_{i}", help="For example: pack, can or bag.")
            expiry = st.date_input("Expiry date *", value=date.today() + timedelta(days=30), key=f"donation_expiry_{i}")
            category = st.text_input("Category", key=f"donation_category_{i}", help="For example: grains or canned food.")
            allergens = st.text_input("Allergens (comma-separated)", key=f"donation_allergens_{i}", help="Copy the food label accurately, for example: nuts, milk.")
            tags = st.text_input("Dietary / cultural suitability tags (comma-separated)", key=f"donation_tags_{i}", help="Only include verified tags, for example: halal, vegan.")
            items.append({"name": name, "quantity": quantity, "unit": unit, "expiry": expiry,
                          "category": category, "allergens": split_list(allergens), "dietary_tags": split_list(tags)})
        submitted = st.form_submit_button("Save donation offer", type="primary")
    if submitted:
        save_action("Donation offer saved. Review it below when the food arrives.",
                    app.donations.record_offer, user, donor, items, method)
    cancel_button("donation_")


def show(app, user):
    """List offers and let authorised staff receive or reject a selected one."""
    st.title("Donations")
    if user.role == Role.STAFF:
        with st.expander("New donation offer"):
            record_form(app, user)
    site = site_filter(user, "donations_site")
    status = st.selectbox("Show donation status", ["All", "offered", "received", "rejected"], format_func=label)
    offers = app.donations.list(user, status=None if status == "All" else status, site_id=site)
    table([{"Reference": d.id, "Donor": d.donor_ref, "Site": d.site_id,
            "Status": label(d.status), "Collection": label(d.collection_method)} for d in offers], "No donation offers match these filters.")
    if not offers:
        return
    selected = st.selectbox("View donation", offers, format_func=lambda d: f"{d.id} · {d.donor_ref}")
    table([{"Item": i["name"], "Quantity": i["quantity"], "Unit": i["unit"], "Expiry": i["expiry"],
            "Allergens": ", ".join(i["allergens"]), "Suitability": ", ".join(i["dietary_tags"])} for i in selected.items])
    if user.role == Role.STAFF and selected.status == "offered":
        with st.form(f"decide_{selected.id}", enter_to_submit=False):
            decision = st.selectbox("Decision", ["received", "rejected"], format_func=label)
            confirm = st.checkbox("I checked this offer. Receiving it will add its items to inventory.")
            submitted = st.form_submit_button("Save donation decision")
        if submitted:
            if not confirm:
                st.error("Check the confirmation box before saving this decision.")
            else:
                save_action("Donation decision saved and inventory refreshed.",
                            app.donations.update_status, user, selected.id, decision)
