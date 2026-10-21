"""Small display helpers shared by the screens."""
import re

import streamlit as st

from app.errors import FoodShareError


def label(value):
    """Display stored status values using normal words."""
    return value.replace("_", " ").capitalize()


def split_list(text):
    """Convert comma-separated form input to a list for the services."""
    return [part.strip().lower() for part in text.split(",") if part.strip()]


def table(rows, empty_message="Nothing to show yet."):
    """Show a readable table or an explanation when it is empty."""
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    else:
        st.info(empty_message)


def show_error(error):
    """Keep the form on screen and explain how to correct a rejected action."""
    st.error(error.message)
    for field, message in error.fields.items():
        names = {"donor_ref": "Donor reference", "inventory_id": "Food item",
                 "assigned_to": "Volunteer", "client_id": "Client", "target": "Affected food or hamper"}
        item = re.fullmatch(r"items\[(\d+)\]\.(\w+)", field)
        if item:
            title = f"Item {int(item[1]) + 1} - {item[2].replace('_', ' ')}"
        else:
            title = names.get(field, field.replace("_", " ").capitalize())
        st.error(f"{title}: {message}")


def finish(message, warnings=None):
    """Refresh saved data while keeping confirmation visible after the rerun."""
    st.session_state["notice"] = message
    st.session_state["warnings"] = warnings or []
    st.rerun()


def save_action(message, action, *args, **kwargs):
    """Call a service and show its validation errors or a success message."""
    try:
        action(*args, **kwargs)
    except FoodShareError as error:
        show_error(error)
    else:
        finish(message)


def reset_form(prefix):
    """Clear this form's widgets when its Cancel button is pressed."""
    for key in list(st.session_state):
        if key.startswith(prefix):
            del st.session_state[key]


def cancel_button(prefix):
    """Provide a way to discard unsaved form input."""
    st.button("Cancel / clear form", key=f"cancel_{prefix}",
              on_click=reset_form, args=(prefix,))


def site_filter(user, key):
    """Admins may request a site; other users stay within their own site."""
    if user.role == "admin":
        return st.text_input("Site (leave blank for all sites)", key=key).strip() or None
    return user.site_id
