"""JSON file persistence with atomic writes, rollback transactions and daily backups.

JSON has no built-in transactions or foreign keys, so integrity is enforced here
(atomic write via temp file + rename, all-or-nothing transactions) and in the services
(reference checks). NFR-06: dated backups and restore of the latest backup.
"""
import copy
import json
import os
import shutil
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List

from .errors import NotFound, StorageError

COLLECTIONS = ("users", "clients", "donations", "inventory", "orders", "tasks", "issues", "change_requests")
LISTS = ("audit", "movements")


class JsonStore:
    def __init__(self, path, backup_dir=None, clock: Callable[[], datetime] = datetime.now):
        self.path = Path(path)
        self.backup_dir = Path(backup_dir) if backup_dir else self.path.parent / "backups"
        self.clock = clock
        self._lock = threading.RLock()
        self._depth = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    # ---------- loading / writing ----------
    @staticmethod
    def _empty() -> Dict[str, Any]:
        data: Dict[str, Any] = {"version": 1, "counters": {}}
        for c in COLLECTIONS:
            data[c] = {}
        for l in LISTS:
            data[l] = []
        return data

    def _read_file(self, path: Path) -> Dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            raise StorageError(f"Data file {path.name} could not be read. Restore the latest backup.") from exc
        merged = self._empty()
        merged.update(raw)
        return merged

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            data = self._empty()
            self._write(data)
            return data
        return self._read_file(self.path)

    def _write(self, data: Dict[str, Any], dest: Path = None) -> None:
        dest = dest or self.path
        tmp = dest.with_name(dest.name + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            # atomic: a failed save never corrupts the existing file
            os.replace(tmp, dest)  
        except OSError as exc:
            if tmp.exists():
                tmp.unlink()
            raise StorageError("Data could not be saved.") from exc

    # ---------- transactions ----------
    @contextmanager
    def transaction(self):
        """All changes inside the block are saved together, or rolled back if an error occurs."""
        with self._lock:
            outermost = self._depth == 0
            snapshot = copy.deepcopy(self.data) if outermost else None
            self._depth += 1
            try:
                yield self
            except BaseException:
                self._depth -= 1
                if outermost:
                    self.data = snapshot
                raise
            else:
                self._depth -= 1
                if outermost:
                    try:
                        self._write(self.data)
                    except StorageError:
                        self.data = snapshot
                        raise

    # ---------- record access ----------
    def next_number(self, name: str) -> int:
        counters = self.data["counters"]
        counters[name] = counters.get(name, 0) + 1
        return counters[name]

    def next_id(self, prefix: str) -> str:
        return f"{prefix}-{self.next_number(prefix):04d}"

    def get(self, collection: str, record_id: str, cls):
        raw = self.data[collection].get(record_id)
        if raw is None:
            raise NotFound(f"{cls.__name__} {record_id} was not found.")
        return cls.from_dict(copy.deepcopy(raw))

    def find(self, collection: str, cls, predicate=None) -> List[Any]:
        out = []
        for raw in self.data[collection].values():
            obj = cls.from_dict(copy.deepcopy(raw))
            if predicate is None or predicate(obj):
                out.append(obj)
        return out

    def put(self, collection: str, obj) -> None:
        self._require_transaction()
        self.data[collection][obj.id] = obj.to_dict()

    def append(self, list_name: str, obj) -> None:
        self._require_transaction()
        self.data[list_name].append(obj.to_dict())

    def _require_transaction(self):
        if self._depth == 0:
            raise RuntimeError("Writes must happen inside store.transaction().")

    # ---------- backup and recovery (NFR-06) ----------
    def _backups(self) -> List[Path]:
        if not self.backup_dir.exists():
            return []
        return sorted(self.backup_dir.glob(f"{self.path.stem}-*.json"))

    def backup(self) -> Path:
        with self._lock:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = self.clock().strftime("%Y%m%d-%H%M%S")
            dest = self.backup_dir / f"{self.path.stem}-{stamp}.json"
            self._write(self.data, dest)
            return dest

    def ensure_daily_backup(self):
        """Creates a backup if none exists yet for today's date. Returns the path or None."""
        today = self.clock().strftime("%Y%m%d")
        if any(p.name.startswith(f"{self.path.stem}-{today}") for p in self._backups()):
            return None
        return self.backup()

    def latest_backup(self):
        backups = self._backups()
        return backups[-1] if backups else None

    def restore_latest(self) -> Path:
        with self._lock:
            latest = self.latest_backup()
            if latest is None:
                raise NotFound("No backup is available to restore.")
            self.data = self._read_file(latest)
            self._write(self.data)
            return latest
