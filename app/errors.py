"""Domain-specific exceptions. The UI layer can catch FoodShareError and show .message."""
class FoodShareError(Exception):
    def __init__(self, message, fields=None):
        super().__init__(message)
        self.message = message
        # fields maps a field name to a human-readable problem (used to highlight form fields)
        self.fields = fields or {}


class ValidationError(FoodShareError):
    """Input is missing or invalid."""


class PermissionDenied(FoodShareError):
    """The user's role/site does not allow this action."""


class AuthenticationError(FoodShareError):
    """Login failed, or the account is locked/inactive."""


class NotFound(FoodShareError):
    """A referenced record does not exist."""


class ConflictError(FoodShareError):
    """The action conflicts with the current state (e.g. insufficient stock)."""


class StorageError(FoodShareError):
    """The data file could not be read or written."""
