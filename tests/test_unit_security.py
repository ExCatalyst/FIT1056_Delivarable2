"""Unit tests: RBAC matrix, site isolation and password hashing (NFR-04)."""
import pytest

from app.errors import PermissionDenied
from app.models import User
from app.security import PasswordHasher, check_site, has_permission, require, resolve_site


def user(role, site="S1"):
    return User(id="U1", username="u", password_hash="", salt="", role=role, site_id=site)


# role, permission, expected   (equivalence classes: one representative per role x permission area)
RBAC = [
    ("staff", "donation.record", True), ("staff", "order.complete", True), ("staff", "client.view_full", True),
    ("staff", "report.view", True), ("staff", "user.manage", False), ("staff", "audit.view", False),
    ("volunteer", "task.view_own", True), ("volunteer", "issue.submit", True),
    ("volunteer", "client.view_full", False), ("volunteer", "donation.record", False),
    ("volunteer", "order.complete", False), ("volunteer", "report.view", False),
    ("volunteer", "user.manage", False), ("volunteer", "audit.view", False),
    ("admin", "user.manage", True), ("admin", "audit.view", True), ("admin", "report.view", True),
    ("admin", "donation.record", False), ("admin", "order.complete", False),
    ("client", "request.submit", True), ("client", "order.view_own", True),
    ("client", "client.view_full", False), ("client", "inventory.view", False), ("client", "donation.record", False),
    ("ghost-role", "inventory.view", False),
]


@pytest.mark.req("NFR-04", "AC-05", "AC-16")
@pytest.mark.parametrize("role,perm,expected", RBAC)
def test_permission_matrix(role, perm, expected):
    assert has_permission(user(role), perm) is expected


@pytest.mark.req("NFR-04")
def test_require_raises_permission_denied():
    with pytest.raises(PermissionDenied):
        require(user("volunteer"), "client.view_full")
    require(user("staff"), "client.view_full")  # no exception


@pytest.mark.req("NFR-04")
def test_check_site():
    check_site(user("staff", "S1"), "S1")
    check_site(user("admin", "HQ"), "S9")      # admins are cross-site
    with pytest.raises(PermissionDenied):
        check_site(user("staff", "S1"), "S2")


@pytest.mark.req("NFR-04", "FR-REP-01")
def test_resolve_site_rules():
    assert resolve_site(user("admin", "HQ")) is None            # admin: all sites
    assert resolve_site(user("admin", "HQ"), "S2") == "S2"
    assert resolve_site(user("staff", "S1")) == "S1"
    assert resolve_site(user("staff", "S1"), "S1") == "S1"
    with pytest.raises(PermissionDenied):
        resolve_site(user("staff", "S1"), "S2")


@pytest.mark.req("NFR-04")
def test_password_hasher_verify_and_salting():
    h = PasswordHasher(1000)
    digest, salt = h.hash("secret123")
    assert digest != "secret123"
    assert h.verify("secret123", digest, salt)
    assert not h.verify("Secret123", digest, salt)
    digest2, salt2 = h.hash("secret123")
    assert salt != salt2 and digest != digest2                 # random salt per hash
    assert h.hash("secret123", salt)[0] == digest              # deterministic for the same salt
