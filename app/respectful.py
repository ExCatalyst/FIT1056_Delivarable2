"""Simple respectful-language check for client-facing text (NFR-03)."""
from .errors import ValidationError

DISALLOWED_PHRASES = (
    "freeloader", "scrounger", "beggar", "handout", "charity case",
    "less fortunate", "undeserving", "lazy", "sponge",
)


def check_respectful(text: str, field: str = "note") -> None:
    lowered = text.lower()
    found = [p for p in DISALLOWED_PHRASES if p in lowered]
    if found:
        raise ValidationError(
            "Please use neutral, respectful wording.",
            {field: "Avoid wording such as: " + ", ".join(found)},
        )
