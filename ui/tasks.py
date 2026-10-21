"""Staff task assignment, minimum-information volunteer views and issue reporting."""
import streamlit as st

from app.models import IssueType, Role
from app.tasks import ALLOWED_TRANSITIONS
from ui.common import cancel_button, label, save_action, table


def create_form(app, user):
    """Use the safe volunteer directory to assign work at the staff member's site."""
    volunteers = app.tasks.assignable_volunteers(user)
    if not volunteers:
        st.info("Ask an administrator to create an active volunteer account at your site before assigning tasks.")
        return
    orders = [o for o in app.orders.list_orders(user) if o.status in ("preparing", "ready")]
    with st.form("create_task", enter_to_submit=False):
        title = st.text_input("Task title *", key="task_new_title")
        description = st.text_area("Packing / sorting instructions", key="task_new_description",
                                   help="Do not include client names, contact details or private household information.")
        volunteer = st.selectbox("Assign to volunteer", volunteers, format_func=lambda v: v["name"], key="task_new_volunteer")
        order = st.selectbox("Related hamper (optional)", [None, *orders], format_func=lambda o: o.pickup_ref if o else "No related hamper", key="task_new_order")
        submitted = st.form_submit_button("Assign task", type="primary")
    if submitted:
        save_action("Task assigned to the volunteer.", app.tasks.create_task, user, title,
                    volunteer["id"], description, order.id if order else None)
    cancel_button("task_new_")


def report_form(app, user, tasks):
    """Report an affected stock batch or a hamper assigned to this volunteer."""
    inventory = app.inventory.search(user, only_available=False)
    order_ids = list(dict.fromkeys(t.order_id for t in tasks if t.order_id))
    views = [app.orders.get_order_view(user, order_id) for order_id in order_ids]
    st.subheader("Report a problem")
    target = st.radio("What is affected?", ["Stock item", "Assigned hamper"], horizontal=True)
    if target == "Stock item" and not inventory:
        st.info("There are no stock items to report. Tell your coordinator if food is missing from the records.")
        return
    if target == "Assigned hamper" and not views:
        st.info("You have no assigned hampers to report. Contact staff if you need a task assignment.")
        return
    with st.form("report_issue", enter_to_submit=False):
        issue_type = st.selectbox("Problem type", list(IssueType.ALL), format_func=label, key="issue_type")
        if target == "Stock item":
            item = st.selectbox("Affected stock", inventory, format_func=lambda i: f"{i.name} · {i.id}", key="issue_stock")
            order_id, inventory_id = None, item.id
        else:
            view = st.selectbox("Affected hamper", views, format_func=lambda v: v["pickup_ref"], key="issue_order")
            order_id, inventory_id = view["order_id"], None
        note = st.text_area("Describe the problem *", key="issue_note",
                            help="Explain what happened and what help is needed. Avoid personal client details.")
        submitted = st.form_submit_button("Send issue to staff", type="primary")
    if submitted:
        save_action("Issue sent to staff for review. This report does not itself change stock quantities.",
                    app.tasks.submit_issue, user, issue_type, note, inventory_id=inventory_id, order_id=order_id)
    cancel_button("issue_")


def volunteer_view(app, user):
    """Show only assigned tasks and the backend's redacted packing view."""
    tasks = app.tasks.my_tasks(user)
    table([{"Task": t.title, "Status": label(t.status)} for t in tasks], "You have no assigned tasks yet. Ask your coordinator for help.")
    if tasks:
        task = st.selectbox("Open your task", tasks, format_func=lambda t: t.title)
        st.text(task.description or "Ask your coordinator if you need more instructions.")
        if task.order_id:
            view = app.orders.get_order_view(user, task.order_id)
            st.text(f"Pickup reference: {view['pickup_ref']}")
            st.text(f"Order status: {label(view['status'])}")
            if view["safety_flag"]:
                st.warning(view["safety_message"])
            table([{"Food": line["name"], "Quantity": line["quantity"]} for line in view["items"]], "Staff have not added food to this hamper yet.")
        options = [status for status in ["in_progress", "completed"] if status in ALLOWED_TRANSITIONS[task.status]]
        if options:
            with st.form(f"progress_{task.id}", enter_to_submit=False):
                status = st.selectbox("New task status", options, format_func=label)
                submitted = st.form_submit_button("Save task progress", type="primary")
            if submitted:
                save_action("Task progress updated. Staff can now see this status.", app.tasks.update_status, user, task.id, status)
        else:
            st.success("This task is completed.")
    st.caption("Only staff complete food orders and deduct stock. Report missing or unsuitable food instead of changing the final distribution.")
    report_form(app, user, tasks)


def show(app, user):
    """Give volunteers their tasks; give staff assignment and issue review tools."""
    st.title("Volunteer tasks")
    if user.role == Role.VOLUNTEER:
        volunteer_view(app, user)
        return
    if user.role == Role.STAFF:
        with st.expander("Assign a new task"):
            create_form(app, user)
    tasks = app.tasks.list_tasks(user)
    status = st.selectbox("Task status filter", ["All", "not_started", "in_progress", "completed"], format_func=label)
    table([{"Task": t.title, "Site": t.site_id, "Assigned volunteer": t.assigned_to,
            "Status": label(t.status), "Related order": t.order_id or "Not linked"}
           for t in tasks if status == "All" or t.status == status], "No tasks match this filter.")
    if user.role == Role.STAFF:
        st.subheader("Issue reports for review")
        issues = app.tasks.list_issues(user)
        table([{"Reference": i.id, "Problem": label(i.issue_type), "Stock": i.inventory_id or "",
                "Order": i.order_id or "", "Note": i.note} for i in issues], "There are no open issue reports.")
        if issues:
            issue = st.selectbox("Issue to review", issues, format_func=lambda i: f"{i.id} · {label(i.issue_type)}")
            st.text(issue.note)
            st.caption("Review the affected food or order separately. Closing a report does not change its condition or quantities.")
            with st.form(f"review_{issue.id}", enter_to_submit=False):
                confirmed = st.checkbox("I reviewed this problem and arranged the necessary follow-up.")
                submitted = st.form_submit_button("Mark issue reviewed")
            if submitted:
                if not confirmed:
                    st.error("Confirm you reviewed the problem before closing the report.")
                else:
                    save_action("Issue marked reviewed.", app.tasks.review_issue, user, issue.id)
