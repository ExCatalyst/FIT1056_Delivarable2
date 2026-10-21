"""Role-specific overview using permitted service results only."""
import streamlit as st

from app.models import Role
from ui.common import label, table


def show(app, user):
    """Summarise today's work without loading client details for volunteers."""
    st.title("Your daily overview")
    st.write("A clear view of food, people and the work ahead.")
    if user.role == Role.VOLUNTEER:
        tasks = app.tasks.my_tasks(user)
        st.metric("Your unfinished tasks", sum(task.status != "completed" for task in tasks))
        st.info("Open Volunteer tasks to see your packing instructions, update progress or report a problem.")
        table([{"Task": t.title, "Status": label(t.status)} for t in tasks], "You have no assigned tasks yet.")
        return
    stock = app.inventory.search(user)
    orders = app.orders.list_orders(user)
    offers = app.donations.list(user, status="offered")
    columns = st.columns(3)
    columns[0].metric("Available stock batches", len(stock))
    columns[1].metric("Donation offers to review", len(offers))
    columns[2].metric("Orders awaiting collection", sum(o.status in ("preparing", "ready") for o in orders))
    st.subheader("Low-stock reminders")
    st.caption("Items with fewer than 10 available units. Use Inventory to adjust the reminder threshold.")
    table([{"Item": r["name"], "Available quantity": r["total"]} for r in app.inventory.low_stock(user)],
          "No stocked item is below this reminder threshold.")
    st.subheader("Next steps")
    if user.role == Role.ADMIN:
        st.info("Use Accounts and audit to create staff and volunteer accounts, manage access, and review activity across sites.")
    else:
        st.info("Record incoming offers in Donations, prepare suitable hampers in Hampers and orders, and assign packing in Volunteer tasks.")
        issues = app.tasks.list_issues(user)
        if issues:
            st.warning(f"{len(issues)} issue report(s) need staff review in Volunteer tasks.")
