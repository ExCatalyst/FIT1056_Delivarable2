"""Staff-assisted client profiles with limited, relevant information."""
import streamlit as st

from app.models import Role
from ui.common import cancel_button, save_action, split_list, table


def profile_form(app, user, client=None):
    """Create or update only the client details supported by the model."""
    prefix = f"profile_{client.id if client else 'new'}_"
    with st.form(prefix + "form", enter_to_submit=False):
        name = st.text_input("Name *", value=client.name if client else "", key=prefix + "name")
        household = st.number_input("Household size *", min_value=1, value=client.household_size if client else 1, key=prefix + "household")
        contact = st.text_input("Contact details (optional)", value=client.contact if client else "", key=prefix + "contact")
        needs = {}
        for field, title in [("allergies", "Allergies"), ("dietary", "Dietary needs"),
                             ("cultural", "Cultural / religious food preferences"), ("accessibility", "Accessibility needs")]:
            value = ", ".join(getattr(client, field)) if client else ""
            needs[field] = split_list(st.text_input(title, value=value, key=prefix + field,
                                                    help="Separate multiple needs with commas. Only record information needed for food support."))
        submitted = st.form_submit_button("Save profile", type="primary")
    if submitted:
        values = dict(name=name, household_size=household, contact=contact, **needs)
        if client:
            save_action("Client profile updated.", app.clients.update_client, user, client.id, **values)
        else:
            save_action("Client profile saved.", app.clients.create_client, user, **values)
    cancel_button(prefix)


def show(app, user):
    """Search profiles and provide staff-assisted creation or editing."""
    st.title("Client profiles")
    st.caption("Ask what support would suit the household. Do not record financial circumstances or unrelated personal history.")
    if user.role == Role.STAFF:
        with st.expander("New client profile"):
            profile_form(app, user)
    query = st.text_input("Search client name")
    profiles = app.clients.search(user, query)
    table([{"Reference": c.id, "Name": c.name, "Site": c.site_id, "Household size": c.household_size} for c in profiles], "No client profiles match this search.")
    if not profiles:
        return
    client = st.selectbox("View client profile", profiles, format_func=lambda c: f"{c.name} · {c.id}")
    if user.role == Role.STAFF:
        st.subheader("Update support details")
        profile_form(app, user, client)
    else:
        st.text(f"Contact: {client.contact or 'Not provided'}")
        for field in ["allergies", "dietary", "cultural", "accessibility"]:
            st.text(f"{field.capitalize()}: {', '.join(getattr(client, field)) or 'None recorded'}")
        st.caption("Administrators can review profiles; staff manage profile changes.")
