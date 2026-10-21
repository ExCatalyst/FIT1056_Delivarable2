"""Administrator accounts, audit filters and local backup controls."""
from datetime import date, timedelta

import streamlit as st

from app.audit import AUDIT_GROUPS
from app.models import Role
from ui.common import cancel_button, label, save_action, site_filter, table


def account_form(app, user):
    """Create internal accounts; clients and donors do not need MVP logins."""
    st.subheader("Create an account")
    with st.form("new_account", enter_to_submit=False):
        name = st.text_input("Full name", key="account_name")
        username = st.text_input("Username *", key="account_username")
        password = st.text_input("Initial password *", type="password", key="account_password")
        st.caption("Use at least 8 characters. Share credentials privately with the account holder.")
        role = st.selectbox("Role", list(Role.INTERNAL), format_func=label, key="account_role")
        site = st.text_input("Site *", value=user.site_id, key="account_site")
        st.caption("Staff and volunteers must use the same site name to work together.")
        submitted = st.form_submit_button("Create account", type="primary")
    if submitted:
        save_action("Account created.", app.auth.create_user, user, username, password,
                    role, site.strip(), full_name=name)
    cancel_button("account_")


def manage_accounts(app, user):
    """Display only public account fields and protect changes with confirmation."""
    users = [u for u in app.auth.list_users(user) if u.role in Role.INTERNAL]
    table([{"Name": u.full_name or u.username, "Username": u.username, "Site": u.site_id,
            "Role": label(u.role), "Active": u.active, "Locked": u.locked} for u in users])
    choices = [u for u in users if u.id != user.id]
    if not choices:
        st.info("Create another account to manage its access. You cannot change your own role or deactivate your own account.")
        return
    target = st.selectbox("Account to manage", choices, format_func=lambda u: f"{u.full_name or u.username} · {u.username}")
    with st.form(f"manage_{target.id}", enter_to_submit=False):
        action = st.selectbox("Action", ["Change role", "Deactivate account" if target.active else "Activate account", "Unlock account"])
        new_role = st.selectbox("New role (used for Change role)", list(Role.INTERNAL),
                                index=list(Role.INTERNAL).index(target.role), format_func=label)
        confirmed = st.checkbox("I checked this account and the access change.")
        submitted = st.form_submit_button("Save account change")
    if submitted:
        if not confirmed:
            st.error("Confirm the account change before saving.")
        elif action == "Change role":
            save_action("Role updated. The new role applies on the user's next interaction.",
                        app.auth.change_role, user, target.id, new_role)
        elif action == "Unlock account":
            save_action("Account unlocked.", app.auth.unlock_user, user, target.id)
        else:
            save_action("Account access updated.", app.auth.set_active, user, target.id, not target.active)


def audit_view(app, user):
    """Filter relevant audit events without rendering stored credentials or profile data."""
    st.subheader("Activity audit")
    site = site_filter(user, "audit_site")
    group = st.selectbox("Activity group", ["All", *AUDIT_GROUPS], format_func=label)
    columns = st.columns(2)
    start = columns[0].date_input("Audit start date", value=date.today() - timedelta(days=30))
    end = columns[1].date_input("Audit end date", value=date.today())
    if end < start:
        st.error("Audit end date must be on or after the start date.")
        return
    users = app.auth.list_users(user)
    selected = st.selectbox("Performed by", [None, *users], format_func=lambda u: u.username if u else "All accounts")
    entries = app.audit.search(user, group=None if group == "All" else group, user_id=selected.id if selected else None,
                               start=start, end=end, site_id=site)
    names = {u.id: u.username for u in users}
    table([{"Time": e.timestamp, "Account": names.get(e.user_id, e.user_id), "Site": e.site_id,
            "Action": label(e.action.replace(".", " ")), "Reference": e.entity_id} for e in entries],
          "No activity matches these filters.")


def backups(app, user):
    """Let an administrator make a local backup or confirm a local restore."""
    st.subheader("Backup and recovery")
    latest = app.store.latest_backup()
    st.caption(f"Latest local backup: {latest.name if latest else 'None available'}")
    if st.button("Create backup now"):
        save_action("Local backup created.", app.backup_now)
    st.warning("Restoring replaces current records with the latest backup. Work saved after that backup will be lost.")
    with st.form("restore", enter_to_submit=False):
        confirmed = st.checkbox("I understand the current records will be replaced with the latest backup.")
        submitted = st.form_submit_button("Restore latest backup", disabled=latest is None)
    if submitted:
        if not confirmed:
            st.error("Confirm the restore before continuing.")
        else:
            save_action("Backup restored. Refresh your account if its permissions changed.", app.restore_latest_backup)


def show(app, user):
    """Group account administration, audit review and backup controls."""
    st.title("Accounts and audit")
    st.caption("Manage access with care. Staff and volunteer screens follow the permissions assigned here.")
    with st.expander("Create a staff, volunteer or admin account"):
        account_form(app, user)
    manage_accounts(app, user)
    st.divider()
    audit_view(app, user)
    with st.expander("Local backup and recovery"):
        backups(app, user)
