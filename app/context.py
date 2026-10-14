"""Shared context passed to every service."""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable

from .errors import AuthenticationError, NotFound
from .models import User
from .security import PasswordHasher
from .storage import JsonStore


@dataclass
class Context:
    store: JsonStore
    clock: Callable[[], datetime]
    hasher: PasswordHasher
    audit: Any = None

    def now(self) -> datetime:
        return self.clock()

    def today(self) -> date:
        return self.clock().date()

    def stamp(self) -> str:
        return self.clock().isoformat(timespec="seconds")

    def refresh(self, actor: User) -> User:
        """Reloads the actor so role changes, deactivation and locking take effect immediately."""
        if actor is None:
            raise AuthenticationError("Please log in.")
        try:
            user = self.store.get("users", actor.id, User)
        except NotFound:
            raise AuthenticationError("Please log in.")
        if not user.active or user.locked:
            raise AuthenticationError("This account is inactive or locked.")
        return user
