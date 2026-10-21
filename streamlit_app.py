"""Start the frontend with: python -m streamlit run streamlit_app.py."""
import os
from pathlib import Path

import streamlit as st

from app import FoodShareApp
from app.errors import AuthenticationError, FoodShareError
from app.models import Role, User
from ui import admin, clients, dashboard, donations, inventory, orders, reports, tasks
from ui.common import finish, show_error


@st.cache_resource
def load_app(data_file):
    """Share one service instance and its storage lock within this local app process."""
    return FoodShareApp(data_file=data_file)


def sign_out():
    """Clear all session widgets, including any previous user's personal information."""
    st.session_state.clear()


def show_login(app):
    """Create the first admin locally, or sign in with an existing internal account."""
    st.title("FoodShare Tracker")
    st.write("Helping your team organise food support with care.")
    first_run = not app.store.data["users"]
    if first_run:
        st.subheader("Welcome. Set up your administrator account")
        st.info("This first-run setup is for the person managing this local installation.")
    else:
        st.subheader("Sign in")
        st.caption("For staff, volunteers and administrators. Ask staff for help with client or donation details.")
    with st.form("login", enter_to_submit=False):
        username = st.text_input("Username", key="login_username")
        password = st.text_input("Password", type="password", key="login_password")
        if first_run:
            full_name = st.text_input("Your name", key="setup_name")
            site = st.text_input("Site", value="HQ", key="setup_site")
            confirm = st.text_input("Confirm password", type="password", key="setup_confirm")
            st.caption("Use at least 8 characters for your password.")
        submitted = st.form_submit_button("Create administrator" if first_run else "Sign in", type="primary")
    if submitted:
        if not username.strip() or not password:
            st.error("Enter your username and password.")
            return
        try:
            if first_run:
                if password != confirm or not site.strip():
                    st.error("Passwords must match and a site is required.")
                    return
                user = app.auth.bootstrap_admin(username, password, site.strip(), full_name)
            else:
                user = app.auth.login(username, password)
            if user.role not in Role.INTERNAL:
                st.error("This workspace is for staff, volunteers and administrators. Please contact staff for assistance.")
                return
        except FoodShareError as error:
            show_error(error)
        else:
            sign_out()
            st.session_state["user_id"] = user.id
            st.session_state["identity"] = (user.id, user.role, user.site_id)
            finish("You are signed in.")


def main():
    """Refresh the user before drawing only the screens their role can access."""
    st.set_page_config(page_title="FoodShare Tracker", page_icon="🌿", layout="wide")
    root = Path(__file__).resolve().parent
    data_file = os.environ.get("FOODSHARE_DATA_FILE", str(root / "data" / "foodshare-local.json"))
    try:
        app = load_app(str(Path(data_file).resolve()))
    except FoodShareError as error:
        show_error(error)
        st.info("Ask the administrator to check the local data file or restore a backup before continuing.")
        return
    if "user_id" not in st.session_state:
        show_login(app)
        return
    try:
        user = app.ctx.refresh(app.store.get("users", st.session_state["user_id"], User))
        if user.role not in Role.INTERNAL:
            raise AuthenticationError("This account cannot access the internal workspace.")
    except FoodShareError as error:
        sign_out()
        st.warning(error.message)
        show_login(app)
        return

    # Role changes clear old page selections and cached form values immediately.
    identity = (user.id, user.role, user.site_id)
    if st.session_state.get("identity") != identity:
        sign_out()
        st.session_state["user_id"] = user.id
        st.session_state["identity"] = identity
    screens = {
        "Dashboard": dashboard.show,
        "Inventory": inventory.show,
        "Volunteer tasks": tasks.show,
    }
    if user.role in (Role.STAFF, Role.ADMIN):
        screens.update({"Donations": donations.show, "Client profiles": clients.show,
                        "Hampers and orders": orders.show, "Reports": reports.show})
    if user.role == Role.ADMIN:
        screens["Accounts and audit"] = admin.show
    with st.sidebar:
        st.title("FoodShare")
        st.text(user.full_name or user.username)
        st.caption(f"{user.role.capitalize()} · Site: {user.site_id}")
        page = st.radio("Workspace", list(screens), key="page")
        st.button("Refresh data", width="stretch")
        st.button("Sign out", on_click=sign_out, width="stretch")
        st.caption("Client and donor details are entered by staff. Sign out when leaving a shared device.")
    if "notice" in st.session_state:
        st.success(st.session_state.pop("notice"))
    for warning in st.session_state.pop("warnings", []):
        st.warning(warning)
    try:
        screens[page](app, user)
    except FoodShareError as error:
        show_error(error)
    st.divider()
    st.caption("Need a larger view? Use your browser zoom. For help with a task, contact your food bank coordinator.")


if __name__ == "__main__":
    main()
