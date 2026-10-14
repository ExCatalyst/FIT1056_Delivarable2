"""Login, lockout and user/role management (UC-01, UC-04, FR-ADM-01 equivalent)."""
from typing import List

from .errors import AuthenticationError, ConflictError, NotFound, ValidationError
from .models import Client, Role, User
from .security import require

MAX_FAILED_ATTEMPTS = 5
MIN_PASSWORD_LENGTH = 8


class AuthService:
    def __init__(self, ctx):
        self.ctx = ctx

    def _find_by_username(self, username: str):
        username = (username or "").strip().lower()
        for u in self.ctx.store.find("users", User):
            if u.username.lower() == username:
                return u
        return None

    def _validate_password(self, password: str) -> None:
        if not password or len(password) < MIN_PASSWORD_LENGTH:
            raise ValidationError("Password too short.", {"password": f"Use at least {MIN_PASSWORD_LENGTH} characters."})

    def bootstrap_admin(self, username: str, password: str, site_id: str = "HQ", full_name: str = "Administrator") -> User:
        """First-run setup: only works while there are no users."""
        store = self.ctx.store
        if store.data["users"]:
            raise ConflictError("The system has already been set up.")
        self._validate_password(password)
        with store.transaction():
            h, s = self.ctx.hasher.hash(password)
            user = User(id=store.next_id("USR"), username=username.strip(), password_hash=h, salt=s,
                        role=Role.ADMIN, site_id=site_id, full_name=full_name)
            store.put("users", user)
            self.ctx.audit.log(user, "user.created", "user", user.id, {"role": Role.ADMIN})
        return user

    def login(self, username: str, password: str) -> User:
        store = self.ctx.store
        user = self._find_by_username(username)
        if user is None:
            raise AuthenticationError("Invalid username or password.")
        if user.locked:
            raise AuthenticationError("Account locked after repeated failed logins. Please contact an administrator.")
        if not user.active:
            raise AuthenticationError("Invalid username or password.")
        if self.ctx.hasher.verify(password or "", user.password_hash, user.salt):
            with store.transaction():
                user.failed_attempts = 0
                store.put("users", user)
                self.ctx.audit.log(user, "auth.login", "user", user.id)
            return user
        with store.transaction():  # record the failure (kept even though we raise afterwards)
            user.failed_attempts += 1
            if user.failed_attempts >= MAX_FAILED_ATTEMPTS:
                user.locked = True
            store.put("users", user)
            self.ctx.audit.log(user, "auth.login_failed", "user", user.id, {"locked": user.locked})
        if user.locked:
            raise AuthenticationError("Account locked after repeated failed logins. Please contact an administrator.")
        raise AuthenticationError("Invalid username or password.")

    def create_user(self, actor: User, username: str, password: str, role: str, site_id: str,
                    full_name: str = "", client_id: str = None) -> User:
        actor = self.ctx.refresh(actor)
        require(actor, "user.manage")
        store = self.ctx.store
        errors = {}
        if not (username or "").strip():
            errors["username"] = "Username is required."
        elif self._find_by_username(username):
            errors["username"] = "Username already exists."
        if role not in Role.ALL:
            errors["role"] = "Unknown role."
        if not site_id:
            errors["site_id"] = "Site is required."
        if errors:
            raise ValidationError("Please correct the highlighted fields.", errors)
        self._validate_password(password)
        if role == Role.CLIENT:
            client = store.get("clients", client_id, Client) if client_id else None
            if client is None or client.site_id != site_id:
                raise ValidationError("A client login must be linked to a client in the same site.", {"client_id": "Invalid client."})
        with store.transaction():
            h, s = self.ctx.hasher.hash(password)
            user = User(id=store.next_id("USR"), username=username.strip(), password_hash=h, salt=s, role=role,
                        site_id=site_id, full_name=full_name, client_id=client_id if role == Role.CLIENT else None)
            store.put("users", user)
            self.ctx.audit.log(actor, "user.created", "user", user.id, {"role": role, "site_id": site_id})
        return user

    def change_role(self, actor: User, user_id: str, new_role: str) -> User:
        actor = self.ctx.refresh(actor)
        require(actor, "user.manage")
        store = self.ctx.store
        target = store.get("users", user_id, User)
        if target.id == actor.id:
            raise ConflictError("You cannot change your own role.")
        if new_role not in Role.INTERNAL or target.role == Role.CLIENT:
            raise ValidationError("That role change is not allowed.", {"role": "Choose staff, volunteer or admin for an internal user."})
        with store.transaction():
            previous = target.role
            target.role = new_role
            store.put("users", target)
            self.ctx.audit.log(actor, "user.role_changed", "user", target.id, {"previous": previous, "new": new_role})
        return target

    def set_active(self, actor: User, user_id: str, active: bool) -> User:
        actor = self.ctx.refresh(actor)
        require(actor, "user.manage")
        store = self.ctx.store
        target = store.get("users", user_id, User)
        if target.id == actor.id:
            raise ConflictError("You cannot deactivate your own account.")
        with store.transaction():
            target.active = bool(active)
            store.put("users", target)
            self.ctx.audit.log(actor, "user.activated" if active else "user.deactivated", "user", target.id)
        return target

    def unlock_user(self, actor: User, user_id: str) -> User:
        actor = self.ctx.refresh(actor)
        require(actor, "user.manage")
        store = self.ctx.store
        target = store.get("users", user_id, User)
        with store.transaction():
            target.locked = False
            target.failed_attempts = 0
            store.put("users", target)
            self.ctx.audit.log(actor, "user.unlocked", "user", target.id)
        return target

    def list_users(self, actor: User) -> List[User]:
        actor = self.ctx.refresh(actor)
        require(actor, "user.manage")
        return sorted(self.ctx.store.find("users", User), key=lambda u: u.id)
