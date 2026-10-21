"""Unit tests: JSON persistence, transactions, atomic writes, backup/restore (NFR-06)."""
from datetime import datetime, timedelta

import pytest

from app.errors import NotFound, StorageError
from app.models import Client
from app.storage import JsonStore


@pytest.fixture
def store(tmp_path):
    return JsonStore(tmp_path / "d" / "db.json", tmp_path / "bk", lambda: datetime(2026, 9, 15, 10, 0, 0))


def cl(i="CLI-0001", name="A"):
    return Client(id=i, site_id="S1", name=name, household_size=1)


def test_new_store_creates_empty_file(store):
    assert store.path.exists()
    assert store.data["users"] == {} and store.data["audit"] == []


def test_write_outside_transaction_refused(store):
    with pytest.raises(RuntimeError):
        store.put("clients", cl())
    with pytest.raises(RuntimeError):
        store.append("audit", cl())


def test_commit_persists_to_disk(store, tmp_path):
    with store.transaction():
        store.put("clients", cl())
    reopened = JsonStore(store.path)
    assert reopened.get("clients", "CLI-0001", Client).name == "A"


def test_rollback_on_error_leaves_memory_and_disk_unchanged(store):
    with pytest.raises(ValueError):
        with store.transaction():
            store.put("clients", cl())
            raise ValueError("boom")
    assert store.data["clients"] == {}
    assert JsonStore(store.path).data["clients"] == {}


def test_nested_transaction_failure_rolls_back_everything(store):
    with pytest.raises(ValueError):
        with store.transaction():
            store.put("clients", cl("CLI-0001"))
            with store.transaction():
                store.put("clients", cl("CLI-0002"))
                raise ValueError
    assert store.data["clients"] == {}


def test_failed_disk_write_rolls_back_memory(store, monkeypatch):
    def fail(*a, **k):
        raise StorageError("disk full")
    monkeypatch.setattr(store, "_write", fail)
    with pytest.raises(StorageError):
        with store.transaction():
            store.put("clients", cl())
    assert store.data["clients"] == {}


def test_next_id_sequence_and_format(store):
    with store.transaction():
        assert store.next_id("CLI") == "CLI-0001"
        assert store.next_id("CLI") == "CLI-0002"
        assert store.next_id("ORD") == "ORD-0001"


def test_get_missing_raises_not_found(store):
    with pytest.raises(NotFound):
        store.get("clients", "nope", Client)


def test_get_returns_copy_not_live_reference(store):
    with store.transaction():
        store.put("clients", cl())
    c = store.get("clients", "CLI-0001", Client)
    c.name = "changed"
    assert store.get("clients", "CLI-0001", Client).name == "A"


def test_corrupt_file_raises_storage_error(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    with pytest.raises(StorageError):
        JsonStore(p)


def test_no_temp_file_left_after_write(store):
    with store.transaction():
        store.put("clients", cl())
    assert not list(store.path.parent.glob("*.tmp"))


# ---------- NFR-06 backup / restore ----------
@pytest.mark.req("NFR-06", "AC-32")
def test_backup_and_restore_latest(store):
    with store.transaction():
        store.put("clients", cl("CLI-0001", "before"))
    store.backup()
    with store.transaction():
        store.put("clients", cl("CLI-0001", "after"))
        store.put("clients", cl("CLI-0002", "extra"))
    store.restore_latest()
    assert store.get("clients", "CLI-0001", Client).name == "before"
    assert "CLI-0002" not in store.data["clients"]
    assert JsonStore(store.path).get("clients", "CLI-0001", Client).name == "before"  # restore is persisted


@pytest.mark.req("NFR-06")
def test_restore_without_backup_raises(store):
    with pytest.raises(NotFound):
        store.restore_latest()


@pytest.mark.req("NFR-06")
def test_daily_backup_created_once_per_day(tmp_path):
    now = {"t": datetime(2026, 9, 15, 10, 0, 0)}
    s = JsonStore(tmp_path / "db.json", tmp_path / "bk", lambda: now["t"])
    assert s.ensure_daily_backup() is not None
    assert s.ensure_daily_backup() is None                   # same day -> no second backup
    now["t"] += timedelta(days=1)
    assert s.ensure_daily_backup() is not None               # next day -> new backup
    assert len(list((tmp_path / "bk").glob("*.json"))) == 2
