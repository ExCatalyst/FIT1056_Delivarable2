"""Password hashing and role-based access control (RBAC) - NFR-04."""
import hashlib
import hmac
import os
from typing import Tuple

from .errors import PermissionDenied
from .models import Role, User


class PasswordHasher:
    def __init__(self, iterations: int = 200_000):
        self.iterations = iterations

    def hash(self, password: str, salt: str = None) -> Tuple[str, str]:
        salt_bytes = bytes.fromhex(salt) if salt else os.urandom(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, self.iterations)
        return digest.hex(), salt_bytes.hex()

    def verify(self, password: str, password_hash: str, salt: str) -> bool:
        candidate, _ = self.hash(password, salt)
        return hmac.compare_digest(candidate, password_hash)


# Minimum-privilege permission sets per role.
PERMISSIONS = {
    Role.STAFF: {
        "donation.record", "donation.decide", "donation.view",
        "inventory.view", "inventory.mark_condition",
        "client.manage", "client.view_full", "client.review_requests",
        "order.manage", "order.complete", "order.view_full",
        "task.manage", "task.view_all",
        "issue.review", "report.view",
    },
    Role.VOLUNTEER: {
        "inventory.view", "inventory.mark_condition",
        "task.view_own", "task.update_status",
        "issue.submit", "order.view_task", "order.edit_quantity",
    },
    Role.ADMIN: {
        "user.manage", "audit.view", "report.view",
        "inventory.view", "client.view_full", "task.view_all", "donation.view",
        "order.view_full",
    },
    Role.CLIENT: {"request.submit", "order.view_own"},
}


def has_permission(user: User, permission: str) -> bool:
    return permission in PERMISSIONS.get(user.role, set())


def require(user: User, permission: str) -> None:
    if not has_permission(user, permission):
        raise PermissionDenied("You do not have permission to perform this action.")


def check_site(user: User, site_id: str) -> None:
    """Admins/managers can work across sites; everyone else only within their own site."""
    if user.role == Role.ADMIN:
        return
    if user.site_id != site_id:
        raise PermissionDenied("This record belongs to another site.")


def resolve_site(user: User, requested_site: str = None):
    """Returns the site filter to use. None means 'all sites' (admin only)."""
    if user.role == Role.ADMIN:
        return requested_site
    if requested_site and requested_site != user.site_id:
        raise PermissionDenied("You can only access your own site.")
    return user.site_id
