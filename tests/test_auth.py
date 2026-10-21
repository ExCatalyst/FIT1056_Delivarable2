"""Unit/service tests: login, lockout, user & role management (UC-01, UC-04, NFR-04)."""
import pytest

from app.errors import AuthenticationError, ConflictError, PermissionDenied, ValidationError
from helpers import item


def fails(app, username, n, pw="wrong-password"):
    for _ in range(n):
        with pytest.raises(AuthenticationError):
            app.auth.login(username, pw)


# ---------- bootstrap + password length (BVA: 7 / 8 / 9) ----------
def test_bootstrap_only_once(app):
    app.auth.bootstrap_admin("admin", "adminpass1")
    with pytest.raises(ConflictError):
        app.auth.bootstrap_admin("other", "adminpass1")


@pytest.mark.req("UC-04", "NFR-04")
@pytest.mark.parametrize("pw,ok", [("1234567", False), ("12345678", True), ("123456789", True), ("", False)],
                         ids=["7-chars", "8-chars-boundary", "9-chars", "empty"])
def test_password_length_boundary(app, pw, ok):
    if ok:
        assert app.auth.bootstrap_admin("admin", pw).role == "admin"
    else:
        with pytest.raises(ValidationError) as ei:
            app.auth.bootstrap_admin("admin", pw)
        assert "password" in ei.value.fields


# ---------- login ----------
@pytest.mark.req("UC-01", "NFR-04")
def test_login_success_and_case_insensitive_username(w):
    assert w.app.auth.login("bob", "password1").id == w.staff.id
    assert w.app.auth.login("  BOB ", "password1").id == w.staff.id


@pytest.mark.req("UC-01")
def test_wrong_password_and_unknown_user_same_message(w):
    with pytest.raises(AuthenticationError) as e1:
        w.app.auth.login("bob", "nope")
    with pytest.raises(AuthenticationError) as e2:
        w.app.auth.login("nobody", "nope")
    assert e1.value.message == e2.value.message               # no user enumeration


@pytest.mark.req("UC-01")
def test_passwords_stored_hashed(w):
    stored = w.app.store.data["users"][w.staff.id]
    assert stored["password_hash"] != "password1" and "password1" not in str(stored)
    assert "password_hash" not in w.staff.public_dict() and "salt" not in w.staff.public_dict()


@pytest.mark.req("UC-01")
def test_inactive_user_cannot_login(w):
    w.app.auth.set_active(w.admin, w.vol.id, False)
    with pytest.raises(AuthenticationError):
        w.app.auth.login("jay", "password1")


# ---------- lockout: BVA on MAX_FAILED_ATTEMPTS = 5 ----------
@pytest.mark.req("UC-01", "NFR-04")
def test_four_failures_do_not_lock_and_success_resets_counter(w):
    fails(w.app, "bob", 4)
    assert w.app.auth.login("bob", "password1").failed_attempts == 0
    fails(w.app, "bob", 4)                                    # counter restarted, still not locked
    assert w.app.auth.login("bob", "password1")


@pytest.mark.req("UC-01", "NFR-04")
def test_fifth_failure_locks_account_even_for_correct_password(w):
    fails(w.app, "bob", 5)
    with pytest.raises(AuthenticationError) as ei:
        w.app.auth.login("bob", "password1")
    assert "locked" in ei.value.message.lower()


@pytest.mark.req("UC-01", "UC-04")
def test_admin_unlock_restores_access(w):
    fails(w.app, "bob", 5)
    w.app.auth.unlock_user(w.admin, w.staff.id)
    assert w.app.auth.login("bob", "password1")


@pytest.mark.req("UC-01", "FR-REP-02")
def test_login_events_are_audited(w):
    w.app.auth.login("bob", "password1")
    fails(w.app, "bob", 1)
    actions = [e["action"] for e in w.app.store.data["audit"]]
    assert "auth.login" in actions and "auth.login_failed" in actions


# ---------- user management (UC-04) ----------
@pytest.mark.req("UC-04", "NFR-04")
@pytest.mark.parametrize("actor", ["staff", "vol", "client_user"])
def test_only_admin_manages_users(w, actor):
    with pytest.raises(PermissionDenied):
        w.app.auth.create_user(getattr(w, actor), "x", "password1", "volunteer", "S1")
    with pytest.raises(PermissionDenied):
        w.app.auth.change_role(getattr(w, actor), w.vol.id, "staff")
    with pytest.raises(PermissionDenied):
        w.app.auth.list_users(getattr(w, actor))


@pytest.mark.req("UC-04")
@pytest.mark.parametrize("kwargs,field", [
    (dict(username="bob", role="staff", site_id="S1"), "username"),         # duplicate
    (dict(username="  ", role="staff", site_id="S1"), "username"),          # blank
    (dict(username="new", role="superuser", site_id="S1"), "role"),         # unknown role
    (dict(username="new", role="staff", site_id=""), "site_id"),            # missing site
])
def test_create_user_validation(w, kwargs, field):
    with pytest.raises(ValidationError) as ei:
        w.app.auth.create_user(w.admin, password="password1", **kwargs)
    assert field in ei.value.fields


@pytest.mark.req("UC-04", "UC-05")
def test_client_login_must_link_client_in_same_site(w):
    with pytest.raises(ValidationError):
        w.app.auth.create_user(w.admin, "c2", "password1", "client", "S1")                       # no client id
    with pytest.raises(ValidationError):
        w.app.auth.create_user(w.admin, "c3", "password1", "client", "S2", client_id=w.client.id)  # wrong site


@pytest.mark.req("UC-04", "FR-REP-02")
def test_change_role_applies_immediately_and_is_audited(w):
    w.app.auth.change_role(w.admin, w.vol.id, "staff")
    # the old Volunteer object still works as an actor but now has Staff powers (refresh-on-every-call)
    d = w.app.donations.record_offer(w.vol, "D1", [item("Rice")], "pickup")
    assert d.status == "offered"
    entries = w.app.audit.search(w.admin, group="role_change")
    assert len(entries) == 1 and entries[0].details == {"previous": "volunteer", "new": "staff"}


@pytest.mark.req("UC-04")
def test_demoted_staff_loses_access_immediately(w):
    w.app.auth.change_role(w.admin, w.staff.id, "volunteer")
    with pytest.raises(PermissionDenied):
        w.app.clients.get_client(w.staff, w.client.id)


@pytest.mark.req("UC-04")
def test_role_change_guards(w):
    with pytest.raises(ConflictError):
        w.app.auth.change_role(w.admin, w.admin.id, "staff")                 # own role
    with pytest.raises(ValidationError):
        w.app.auth.change_role(w.admin, w.client_user.id, "staff")           # client accounts are fixed
    with pytest.raises(ValidationError):
        w.app.auth.change_role(w.admin, w.vol.id, "client")                  # cannot become client


@pytest.mark.req("UC-04", "NFR-04")
def test_deactivated_user_loses_access_and_self_deactivation_blocked(w):
    w.app.auth.set_active(w.admin, w.staff.id, False)
    with pytest.raises(AuthenticationError):
        w.app.clients.get_client(w.staff, w.client.id)
    with pytest.raises(ConflictError):
        w.app.auth.set_active(w.admin, w.admin.id, False)


def test_refresh_rejects_none_and_unknown_actor(w):
    with pytest.raises(AuthenticationError):
        w.app.clients.search(None)
