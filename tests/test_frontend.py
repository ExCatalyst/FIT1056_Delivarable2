"""User-facing Streamlit checks using temporary data, never the working data file."""
from datetime import date, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app import FoodShareApp
from app.models import Role

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "ExamplePass123"


def click(screen, text):
    """Press a button by its visible label and wait for the resulting screen."""
    matches = [button for button in screen.button if button.label == text]
    assert len(matches) == 1, text
    matches[0].click().run()
    assert not screen.exception


def choose(screen, text, value):
    """Change a selection by its visible label."""
    matches = [widget for widget in screen.selectbox if widget.label == text]
    assert len(matches) == 1, text
    matches[0].set_value(value).run()
    assert not screen.exception


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Prepare accounts, suitable/unsuitable stock and an assigned hamper."""
    path = tmp_path / "test-data.json"
    monkeypatch.setenv("FOODSHARE_DATA_FILE", str(path))
    app = FoodShareApp(path)
    admin = app.auth.bootstrap_admin("manager", PASSWORD, "Site A")
    staff = app.auth.create_user(admin, "staff", PASSWORD, Role.STAFF, "Site A")
    volunteer = app.auth.create_user(admin, "volunteer", PASSWORD, Role.VOLUNTEER, "Site A")
    app.auth.create_user(admin, "other-volunteer", PASSWORD, Role.VOLUNTEER, "Site B")
    client = app.clients.create_client(staff, "Private Client Name", 3, "private@example.test", allergies=["nuts"])
    expiry = (date.today() + timedelta(days=60)).isoformat()
    offer = app.donations.record_offer(staff, "Donor reference", [
        {"name": "Rice", "quantity": 20, "expiry": expiry},
        {"name": "Nut snack", "quantity": 5, "expiry": expiry, "allergens": ["nuts"]},
    ], "drop_off")
    app.donations.update_status(staff, offer.id, "received")
    order = app.orders.create_order(staff, client.id)
    rice = app.inventory.search(staff, "Rice")[0]
    app.orders.add_item(staff, order.id, rice.id, 2)
    task = app.tasks.create_task(staff, "Pack hamper", volunteer.id, "Check the food labels.", order.id)
    return path, app, admin, staff, volunteer, order, task


def signed_in(username):
    """Sign in through the actual form rather than injecting a session identity."""
    screen = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=15).run()
    assert not screen.exception
    screen.text_input(key="login_username").input(username)
    screen.text_input(key="login_password").input(PASSWORD)
    click(screen, "Sign in")
    return screen


def open_page(screen, page):
    """Navigate using the same workspace control as a user."""
    screen.radio(key="page").set_value(page).run()
    assert not screen.exception


@pytest.mark.parametrize("username", ["manager", "staff", "volunteer"])
def test_each_role_can_open_every_available_screen(workspace, username):
    """Each role's navigation renders without exceptions or secret account fields."""
    screen = signed_in(username)
    options = list(screen.radio(key="page").options)
    for page in options:
        open_page(screen, page)
        assert not screen.exception
        for frame in screen.dataframe:
            assert "password_hash" not in str(frame.value.columns)
            assert "salt" not in str(frame.value.columns)
    if username == "volunteer":
        assert "Client profiles" not in options
        assert "Accounts and audit" not in options


def test_setup_and_invalid_login(tmp_path, monkeypatch):
    """The first account is explicit, and invalid sign-in shows a recoverable error."""
    path = tmp_path / "first-run.json"
    monkeypatch.setenv("FOODSHARE_DATA_FILE", str(path))
    screen = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=15).run()
    screen.text_input(key="login_username").input("manager")
    screen.text_input(key="login_password").input(PASSWORD)
    screen.text_input(key="setup_confirm").input("DifferentPassword")
    click(screen, "Create administrator")
    assert screen.error
    assert not FoodShareApp(path).store.data["users"]
    screen.text_input(key="setup_confirm").input(PASSWORD)
    click(screen, "Create administrator")
    assert screen.radio(key="page")
    click(screen, "Sign out")
    screen.text_input(key="login_username").input("manager")
    screen.text_input(key="login_password").input("incorrect")
    click(screen, "Sign in")
    assert any("Invalid username or password" in e.value for e in screen.error)
    assert not screen.radio


def test_donation_validation_and_cancel(workspace):
    """Zero quantities are rejected; correcting the same form saves exactly once."""
    path = workspace[0]
    screen = signed_in("staff")
    open_page(screen, "Donations")
    screen.text_input(key="donation_donor").input("Second donor")
    screen.text_input(key="donation_name_0").input("Beans")
    screen.number_input(key="donation_quantity_0").set_value(0)
    click(screen, "Save donation offer")
    assert screen.error
    assert len(FoodShareApp(path).store.data["donations"]) == 1
    screen.number_input(key="donation_quantity_0").set_value(3)
    click(screen, "Save donation offer")
    assert len(FoodShareApp(path).store.data["donations"]) == 2
    screen.button(key="cancel_donation_").click().run()
    assert screen.text_input(key="donation_donor").value == ""
    assert len(FoodShareApp(path).store.data["donations"]) == 2


def test_allergen_filter_and_confirmed_completion(workspace):
    """Unsafe stock is absent; completion requires confirmation and deducts once."""
    path, _, _, staff, _, order, _ = workspace
    screen = signed_in("staff")
    open_page(screen, "Hampers and orders")
    selector = next(w for w in screen.selectbox if w.label == "Available item")
    assert all("Nut snack" not in option for option in selector.options)
    click(screen, "Complete order and update stock")
    assert screen.error
    assert FoodShareApp(path).orders.list_orders(staff)[0].status == "preparing"
    confirm = next(w for w in screen.checkbox if "food has been distributed" in w.label)
    confirm.check()
    click(screen, "Complete order and update stock")
    refreshed = FoodShareApp(path)
    assert refreshed.orders.list_orders(staff)[0].status == "completed"
    assert refreshed.inventory.search(staff, "Rice")[0].quantity == 18
    assert not any(b.label == "Complete order and update stock" for b in screen.button)


def test_volunteer_privacy_progress_and_issue(workspace):
    """Assigned packing is redacted and task completion does not deduct stock."""
    path, _, _, staff, volunteer, _, task = workspace
    screen = signed_in("volunteer")
    open_page(screen, "Volunteer tasks")
    rendered = " ".join(x.value for x in screen.text)
    rendered += " ".join(str(x.value) for x in screen.dataframe)
    assert "Private Client Name" not in rendered
    assert "private@example.test" not in rendered
    assert any("Allergy/dietary" in w.value for w in screen.warning)
    assert not any(b.label == "Complete order and update stock" for b in screen.button)
    status = next(w for w in screen.selectbox if w.label == "New task status")
    status.set_value("in_progress")
    click(screen, "Save task progress")
    assert FoodShareApp(path).tasks.my_tasks(volunteer)[0].status == "in_progress"
    assert FoodShareApp(path).inventory.search(staff, "Rice")[0].quantity == 20
    screen.text_area(key="issue_note").input("One package is damaged. Please check before packing.")
    click(screen, "Send issue to staff")
    assert len(FoodShareApp(path).tasks.list_issues(staff)) == 1


def test_role_change_applies_to_open_session(workspace):
    """An admin role change removes restricted navigation on the next rerun."""
    screen = signed_in("staff")
    open_page(screen, "Client profiles")
    manager = signed_in("manager")
    open_page(manager, "Accounts and audit")
    picker = next(w for w in manager.selectbox if w.label == "Account to manage")
    staff_account = next(u for u in picker.options if "staff" in u and "other" not in u)
    # Select the account through the administrator's visible account picker.
    picker.select(staff_account).run()
    role = next(w for w in manager.selectbox if w.label == "New role (used for Change role)")
    role.set_value(Role.VOLUNTEER)
    confirm = next(w for w in manager.checkbox if "checked this account" in w.label)
    confirm.check()
    click(manager, "Save account change")
    screen.run()
    assert not screen.exception
    assert "Client profiles" not in screen.radio(key="page").options


def test_reports_reject_reversed_dates(workspace):
    """A bad report range displays a field-level explanation without crashing."""
    screen = signed_in("manager")
    open_page(screen, "Reports")
    start = next(w for w in screen.date_input if w.label == "Start date")
    start.set_value(date.today() + timedelta(days=1)).run()
    assert not screen.exception
    assert any("end date" in e.value.lower() for e in screen.error)


def test_safe_volunteer_picker_obeys_site_and_permissions(workspace):
    """The small backend integration adds no access to full account records."""
    _, app, _, staff, volunteer, _, _ = workspace
    from app.errors import PermissionDenied
    choices = app.tasks.assignable_volunteers(staff)
    assert choices == [{"id": volunteer.id, "name": volunteer.username}]
    with pytest.raises(PermissionDenied):
        app.tasks.assignable_volunteers(volunteer)


def test_staff_create_client_and_task(workspace):
    """Staff can record household needs and assign an existing volunteer a task."""
    path, _, _, staff, volunteer, _, _ = workspace
    screen = signed_in("staff")
    open_page(screen, "Client profiles")
    screen.text_input(key="profile_new_name").input("New household")
    screen.number_input(key="profile_new_household").set_value(4)
    screen.text_input(key="profile_new_allergies").input("milk, nuts")
    screen.text_input(key="profile_new_cultural").input("halal")
    # There is also an edit form for the existing client, so select by form key.
    screen.button(key="FormSubmitter:profile_new_form-Save profile").click().run()
    assert not screen.exception
    saved = FoodShareApp(path).clients.search(staff, "New household")[0]
    assert saved.household_size == 4 and saved.allergies == ["milk", "nuts"]
    open_page(screen, "Volunteer tasks")
    screen.text_input(key="task_new_title").input("Sort incoming food")
    screen.text_area(key="task_new_description").input("Check expiry dates before sorting.")
    click(screen, "Assign task")
    saved_tasks = FoodShareApp(path).tasks.my_tasks(volunteer)
    assert any(t.title == "Sort incoming food" for t in saved_tasks)


def test_admin_create_account_and_role_confirmation(workspace):
    """Admin account creation persists; access changes require explicit confirmation."""
    path = workspace[0]
    screen = signed_in("manager")
    open_page(screen, "Accounts and audit")
    screen.text_input(key="account_name").input("New volunteer")
    screen.text_input(key="account_username").input("new-volunteer")
    screen.text_input(key="account_password").input(PASSWORD)
    screen.selectbox(key="account_role").set_value(Role.VOLUNTEER)
    click(screen, "Create account")
    app = FoodShareApp(path)
    new = app.auth.login("new-volunteer", PASSWORD)
    assert new.role == Role.VOLUNTEER
    click(screen, "Save account change")
    assert any("Confirm the account change" in e.value for e in screen.error)


def test_stock_condition_confirmation_and_reports(workspace):
    """A confirmed condition change hides food from packing; report totals stay accurate."""
    path, _, _, staff, _, _, _ = workspace
    screen = signed_in("staff")
    open_page(screen, "Inventory")
    condition = next(w for w in screen.selectbox if w.label == "New condition")
    condition.set_value("damaged")
    click(screen, "Save condition")
    assert screen.error
    confirm = next(w for w in screen.checkbox if "checked the item" in w.label)
    confirm.check()
    click(screen, "Save condition")
    refreshed = FoodShareApp(path)
    assert len(refreshed.inventory.search(staff)) == 1
    open_page(screen, "Reports")
    assert any(m.label == "Received units" and m.value == "25" for m in screen.metric)
