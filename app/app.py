"""Facade that wires the layers together. The Streamlit UI should create ONE FoodShareApp and call its services."""
from datetime import datetime
from pathlib import Path

from .audit import AuditService
from .auth import AuthService
from .clients import ClientService
from .context import Context
from .donations import DonationService
from .inventory import InventoryService
from .orders import OrderService
from .reports import ReportService
from .security import PasswordHasher
from .storage import JsonStore
from .tasks import TaskService


class FoodShareApp:
    def __init__(self, data_file="data/foodshare.json", backup_dir=None, clock=None, hash_iterations=200_000):
        clock = clock or datetime.now
        store = JsonStore(Path(data_file), backup_dir, clock)
        self.ctx = Context(store=store, clock=clock, hasher=PasswordHasher(hash_iterations))
        self.ctx.audit = AuditService(self.ctx)
        self.audit = self.ctx.audit
        self.auth = AuthService(self.ctx)
        self.donations = DonationService(self.ctx)
        self.inventory = InventoryService(self.ctx)
        self.clients = ClientService(self.ctx)
        self.orders = OrderService(self.ctx)
        self.tasks = TaskService(self.ctx)
        self.reports = ReportService(self.ctx)
        store.ensure_daily_backup()  # NFR-06: at most one working day of records is ever at risk

    @property
    def store(self):
        return self.ctx.store

    def backup_now(self):
        return self.ctx.store.backup()

    def restore_latest_backup(self):
        return self.ctx.store.restore_latest()
