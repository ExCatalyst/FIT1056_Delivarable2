"""Hamper building, collection scheduling and staff-only completion."""
from datetime import datetime, timedelta

import streamlit as st

from app.errors import FoodShareError
from app.models import OrderStatus, Role
from app.orders import dietary_warnings
from ui.common import cancel_button, finish, label, save_action, show_error, table


def create_form(app, user):
    """Create an order for a client at the staff member's site."""
    clients = app.clients.search(user)
    if not clients:
        st.info("Create a client profile before preparing a hamper.")
        return
    with st.form("new_order", enter_to_submit=False):
        client = st.selectbox("Client", clients, format_func=lambda c: f"{c.name} · {c.id}")
        submitted = st.form_submit_button("Create hamper order", type="primary")
    if submitted:
        save_action("Hamper order created. Select it below to add suitable food.", app.orders.create_order, user, client.id)


def item_forms(app, user, order, client):
    """Use the backend's allergen-filtered list and allow draft quantity corrections."""
    choices = app.orders.selectable_items(user, order.id)
    st.subheader("Add suitable food")
    st.caption("Recorded allergens and unavailable food are automatically excluded. Verify food labels before packing.")
    if choices:
        selected = st.selectbox("Available item", choices, format_func=lambda i: f"{i.name} · {i.quantity} {i.unit} available · {i.id}")
        warnings = dietary_warnings(client, selected)
        for warning in warnings:
            st.warning(warning)
        with st.form(f"add_item_{order.id}_{selected.id}", enter_to_submit=False):
            quantity = st.number_input("Quantity to add", min_value=1, step=1, value=1)
            reviewed = st.checkbox("I checked this food's suitability with the client's needs.")
            submitted = st.form_submit_button("Add item", type="primary")
        if submitted:
            if not reviewed:
                st.error("Check this food's suitability before adding it.")
            else:
                try:
                    _, warnings = app.orders.add_item(user, order.id, selected.id, quantity)
                except FoodShareError as error:
                    show_error(error)
                else:
                    finish("Item added. Inventory changes only when staff complete the order.", warnings)
    else:
        st.info("No suitable food is currently available for this client. Review inventory or wait for a suitable donation.")
    if order.items:
        st.subheader("Adjust selected food")
        line = st.selectbox("Order item", order.items, format_func=lambda row: f"{row['name']} · {row['inventory_id']}")
        with st.form(f"adjust_{order.id}_{line['inventory_id']}", enter_to_submit=False):
            quantity = st.number_input("New quantity", min_value=1, value=line["quantity"], step=1)
            update = st.form_submit_button("Save quantity")
            remove = st.form_submit_button("Remove item")
        if update:
            save_action("Order quantity updated.", app.orders.update_item_quantity,
                        user, order.id, line["inventory_id"], quantity)
        if remove:
            save_action("Item removed from this order.", app.orders.remove_item,
                        user, order.id, line["inventory_id"])


def pickup_and_status(app, user, order):
    """Record pickup details and require confirmation for final inventory changes."""
    st.subheader("Pickup arrangements")
    default = datetime.fromisoformat(order.pickup_time) if order.pickup_time else datetime.now() + timedelta(days=1)
    with st.form(f"pickup_{order.id}", enter_to_submit=False):
        day = st.date_input("Pickup date", value=default.date())
        time = st.time_input("Pickup time", value=default.time().replace(second=0, microsecond=0))
        submitted = st.form_submit_button("Save pickup time")
    if submitted:
        save_action("Pickup time saved.", app.orders.set_pickup_time, user, order.id, datetime.combine(day, time))
    with st.form(f"status_{order.id}", enter_to_submit=False):
        options = [OrderStatus.READY, OrderStatus.CANCELLED] if order.status == OrderStatus.PREPARING else [OrderStatus.PREPARING, OrderStatus.CANCELLED]
        status = st.selectbox("Change order status", options, format_func=label)
        checked = st.checkbox("I checked this status change, including any cancellation.")
        submitted = st.form_submit_button("Save order status")
    if submitted:
        if not checked:
            st.error("Confirm the status change before saving.")
        else:
            save_action("Order status updated.", app.orders.set_status, user, order.id, status)
    st.subheader("Complete collection")
    st.warning("Completing this order deducts the listed quantities from stock. This cannot be undone from this screen.")
    with st.form(f"complete_{order.id}", enter_to_submit=False):
        confirmed = st.checkbox("The food has been distributed and I confirm the listed quantities.")
        submitted = st.form_submit_button("Complete order and update stock")
    if submitted:
        if not confirmed:
            st.error("Confirm the food was distributed before completing the order.")
        else:
            save_action("Order completed. Stock quantities are now updated.", app.orders.complete_order, user, order.id)


def show(app, user):
    """Show full needs to staff/admins, keeping volunteer packing in its own screen."""
    st.title("Hampers and orders")
    if user.role == Role.STAFF:
        with st.expander("New hamper order"):
            create_form(app, user)
    status = st.selectbox("Order status filter", ["All", "preparing", "ready", "completed", "cancelled"], format_func=label)
    orders = app.orders.list_orders(user, status=None if status == "All" else status)
    if user.role == Role.ADMIN:
        site = st.text_input("Filter orders by site (blank for all)")
        orders = [o for o in orders if not site.strip() or o.site_id == site.strip()]
    table([{"Pickup reference": o.pickup_ref, "Order": o.id, "Site": o.site_id,
            "Status": label(o.status), "Pickup time": o.pickup_time or "Not arranged",
            "Needs review": "Yes" if o.flagged else "No"} for o in orders], "No orders match this filter.")
    if not orders:
        return
    order = st.selectbox("Open order", orders, format_func=lambda o: f"{o.pickup_ref} · {label(o.status)}")
    view = app.orders.get_order_view(user, order.id)
    client = view["client"]
    st.subheader("Household food needs")
    st.text(f"Client: {client['name']} · Household size: {client['household_size']}")
    for field in ["allergies", "dietary", "cultural", "accessibility"]:
        st.text(f"{field.capitalize()}: {', '.join(client[field]) or 'None recorded'}")
    if client["allergies"]:
        st.warning("An allergy is recorded. Check the suitable food list and verify food labels before packing.")
    table([{"Item": line["name"], "Quantity": line["quantity"]} for line in order.items], "No food has been added to this order yet.")
    st.caption(f"Pickup: {order.pickup_time or 'Not arranged'} · {view['pickup_status']}")
    for note in order.substitution_notes:
        st.text(f"Substitution note: {note['note']}")
    active = order.status in (OrderStatus.PREPARING, OrderStatus.READY)
    if user.role == Role.STAFF and active:
        if order.status == OrderStatus.PREPARING:
            item_forms(app, user, order, app.clients.get_client(user, order.client_id))
        with st.expander("Record a substitution note"):
            with st.form(f"note_{order.id}", enter_to_submit=False):
                note = st.text_area("Explain the substitution respectfully", key=f"note_{order.id}_text", max_chars=500)
                st.caption("For example: 'Rice was unavailable; pasta was offered after checking dietary needs.'")
                submitted = st.form_submit_button("Save note")
            if submitted:
                save_action("Substitution note saved.", app.orders.add_substitution_note, user, order.id, note)
            cancel_button(f"note_{order.id}_")
        pickup_and_status(app, user, order)
