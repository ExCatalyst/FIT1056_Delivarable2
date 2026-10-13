"""Domain entities (dataclasses). Each one serialises to/from a plain dict for JSON storage."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Optional

class Role:
    STAFF = "staff"
    VOLUNTEER = "volunteer"
    ADMIN = "admin"
    CLIENT = "client"
    ALL = (STAFF, VOLUNTEER, ADMIN, CLIENT)
    INTERNAL = (STAFF, VOLUNTEER, ADMIN)


class DonationStatus:
    OFFERED = "offered"
    RECEIVED = "received"
    REJECTED = "rejected"


class Condition:
    AVAILABLE = "available"
    DAMAGED = "damaged"
    EXPIRED = "expired"
    MISSING = "missing"
    ALL = (AVAILABLE, DAMAGED, EXPIRED, MISSING)


class OrderStatus:
    PREPARING = "preparing"
    READY = "ready"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskStatus:
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class IssueType:
    DAMAGED_FOOD = "damaged_food"
    MISSING_STOCK = "missing_stock"
    INCOMPLETE_ORDER = "incomplete_order"
    ALL = (DAMAGED_FOOD, MISSING_STOCK, INCOMPLETE_ORDER)


class Record:
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


@dataclass
class User(Record):
    id: str
    username: str
    password_hash: str
    salt: str
    role: str
    site_id: str
    full_name: str = ""

    # Only for client role
    client_id: Optional[str] = None
    active: bool = True
    failed_attempts: int = 0
    locked: bool = False

    def public_dict(self) -> Dict[str, Any]:
        d = self.to_dict()
        d.pop("password_hash")
        d.pop("salt")
        return d


@dataclass
class Client(Record):
    """Only data needed to provide food support is stored (FR-CPM-01): no financial details."""
    id: str
    site_id: str
    name: str
    household_size: int
    contact: str = ""
    allergies: List[str] = field(default_factory=list)
    dietary: List[str] = field(default_factory=list)
    cultural: List[str] = field(default_factory=list)
    accessibility: List[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Donation(Record):
    id: str
    site_id: str
    donor_ref: str
    items: List[Dict[str, Any]]
    collection_method: str
    status: str
    created_by: str
    created_at: str
    updated_at: str = ""
    decided_by: Optional[str] = None


@dataclass
class InventoryItem(Record):
    id: str
    site_id: str
    name: str
    quantity: int
    unit: str
    expiry: str
    allergens: List[str] = field(default_factory=list)
    dietary_tags: List[str] = field(default_factory=list)
    category: str = ""
    condition: str = Condition.AVAILABLE
    donation_id: Optional[str] = None
    flagged: bool = False
    created_at: str = ""


@dataclass
class Order(Record):
    id: str
    site_id: str
    client_id: str
    pickup_ref: str
    status: str
    created_by: str
    created_at: str
    items: List[Dict[str, Any]] = field(default_factory=list)
    pickup_time: Optional[str] = None
    substitution_notes: List[Dict[str, str]] = field(default_factory=list)
    flagged: bool = False
    updated_at: str = ""
    completed_by: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass
class Task(Record):
    id: str
    site_id: str
    title: str
    assigned_to: str
    status: str
    created_by: str
    created_at: str
    description: str = ""
    order_id: Optional[str] = None
    updated_at: str = ""


@dataclass
class IssueReport(Record):
    id: str
    site_id: str
    reporter_id: str
    issue_type: str
    note: str
    created_at: str
    inventory_id: Optional[str] = None
    order_id: Optional[str] = None
    status: str = "open"
    reviewed_by: Optional[str] = None


@dataclass
class ChangeRequest(Record):
    id: str
    site_id: str
    client_id: str
    requested_by: str
    changes: Dict[str, Any]
    created_at: str
    status: str = "pending"
    decided_by: Optional[str] = None
    decided_at: Optional[str] = None


@dataclass
class AuditEntry(Record):
    id: str
    timestamp: str
    user_id: str
    role: str
    site_id: str
    action: str
    entity: str
    entity_id: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StockMovement(Record):
    id: str
    timestamp: str
    site_id: str
    inventory_id: str
    item_name: str
    delta: int
    reason: str
    ref_id: str = ""
