"""Shared input validation helpers."""
from datetime import date, datetime
from typing import Any, Dict, List

from .errors import ValidationError


def clean_list(values) -> List[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    seen, out = set(), []
    for v in values:
        v = str(v).strip().lower()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def parse_date(value: Any, field: str = "date") -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise ValidationError("Invalid date.", {field: "Use the format YYYY-MM-DD."})


def parse_datetime(value: Any, field: str = "datetime") -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value).strip().replace(" ", "T")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValidationError("Invalid date/time.", {field: "Use the format YYYY-MM-DD HH:MM."})


def is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def require_positive_int(value: Any, field: str = "quantity") -> int:
    if not is_positive_int(value):
        raise ValidationError("Invalid quantity.", {field: "Quantity must be a whole number greater than zero."})
    return value


def normalise_donation_items(items, today: date) -> List[Dict[str, Any]]:
    """FR-DM-01/02/03: validates mandatory fields and rejects zero/negative quantities."""
    errors: Dict[str, str] = {}
    cleaned: List[Dict[str, Any]] = []
    if not items:
        errors["items"] = "At least one donated item is required."
    for i, raw in enumerate(items or []):
        prefix = f"items[{i}]"
        name = str(raw.get("name", "")).strip()
        if not name:
            errors[f"{prefix}.name"] = "Item name is required."
        qty = raw.get("quantity")
        if qty is None or qty == "":
            errors[f"{prefix}.quantity"] = "Quantity is required."
        elif not is_positive_int(qty):
            errors[f"{prefix}.quantity"] = "Quantity must be a whole number greater than zero."
        expiry = raw.get("expiry")
        expiry_text = None
        if expiry in (None, ""):
            errors[f"{prefix}.expiry"] = "Expiry date is required."
        else:
            try:
                d = parse_date(expiry)
                if d < today:
                    errors[f"{prefix}.expiry"] = "Expiry date has already passed."
                else:
                    expiry_text = d.isoformat()
            except ValidationError:
                errors[f"{prefix}.expiry"] = "Use the format YYYY-MM-DD."
        cleaned.append({
            "name": name,
            "quantity": qty,
            "unit": str(raw.get("unit", "unit")).strip() or "unit",
            "expiry": expiry_text,
            "allergens": clean_list(raw.get("allergens")),
            "dietary_tags": clean_list(raw.get("dietary_tags")),
            "category": str(raw.get("category", "")).strip(),
        })
    if errors:
        raise ValidationError("Please correct the highlighted fields.", errors)
    return cleaned
