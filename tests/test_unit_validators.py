"""Unit tests: validators + respectful-language check.
Techniques: equivalence partitioning (EP) and boundary value analysis (BVA) on quantity, expiry date, password-free inputs."""
from datetime import date, datetime

import pytest

from app.errors import ValidationError
from app.respectful import check_respectful
from app.validators import (clean_list, is_positive_int, normalise_donation_items, parse_date,
                                  parse_datetime, require_positive_int)

TODAY = date(2026, 9, 15)


def one(**over):
    base = {"name": "Rice", "quantity": 5, "expiry": "2026-12-31"}
    base.update(over)
    return [base]


def error_fields(items):
    with pytest.raises(ValidationError) as ei:
        normalise_donation_items(items, TODAY)
    return ei.value.fields


# ---------- quantity: EP + BVA (FR-DM-02) ----------
@pytest.mark.req("FR-DM-02", "AC-02")
@pytest.mark.parametrize("qty", [1, 2, 500], ids=["lower-boundary", "valid-small", "valid-large"])
def test_quantity_valid_partition_and_lower_boundary(qty):
    assert normalise_donation_items(one(quantity=qty), TODAY)[0]["quantity"] == qty


@pytest.mark.req("FR-DM-02", "AC-02")
@pytest.mark.parametrize("qty", [0, -1, -100], ids=["boundary-zero", "boundary-minus-one", "negative"])
def test_quantity_zero_and_negative_rejected(qty):
    assert "items[0].quantity" in error_fields(one(quantity=qty))


@pytest.mark.req("FR-DM-02", "FR-DM-03")
@pytest.mark.parametrize("qty", ["5", 2.5, True, None, ""], ids=["string", "float", "bool", "none", "empty"])
def test_quantity_wrong_type_or_missing_rejected(qty):
    assert "items[0].quantity" in error_fields(one(quantity=qty))


@pytest.mark.parametrize("value,expected", [(1, True), (0, False), (-1, False), (True, False), (1.0, False), ("1", False)])
def test_is_positive_int_partitions(value, expected):
    assert is_positive_int(value) is expected


def test_require_positive_int_returns_value_or_raises():
    assert require_positive_int(3) == 3
    with pytest.raises(ValidationError):
        require_positive_int(0)


# ---------- expiry date: BVA around "today" (FR-DM-01/03) ----------
@pytest.mark.req("FR-DM-01", "FR-DM-03")
@pytest.mark.parametrize("expiry,ok", [("2026-09-14", False), ("2026-09-15", True), ("2026-09-16", True)],
                         ids=["yesterday", "today", "tomorrow"])
def test_expiry_boundary_around_today(expiry, ok):
    if ok:
        assert normalise_donation_items(one(expiry=expiry), TODAY)[0]["expiry"] == expiry
    else:
        assert "items[0].expiry" in error_fields(one(expiry=expiry))


@pytest.mark.req("FR-DM-03", "AC-04")
@pytest.mark.parametrize("expiry", [None, "", "15/09/2026", "2026-13-01", "soon"])
def test_expiry_missing_or_malformed_rejected(expiry):
    assert "items[0].expiry" in error_fields(one(expiry=expiry))


# ---------- mandatory fields (FR-DM-03) ----------
@pytest.mark.req("FR-DM-03", "AC-04")
def test_blank_name_rejected():
    assert "items[0].name" in error_fields(one(name="   "))


@pytest.mark.req("FR-DM-03")
@pytest.mark.parametrize("items", [[], None])
def test_no_items_rejected(items):
    assert "items" in error_fields(items)


@pytest.mark.req("FR-DM-03", "AC-04")
def test_all_problems_reported_together():
    fields = error_fields([{"name": "", "quantity": 0, "expiry": None}])
    assert {"items[0].name", "items[0].quantity", "items[0].expiry"} <= set(fields)


@pytest.mark.req("FR-DM-01")
def test_optional_fields_default_and_normalise():
    out = normalise_donation_items(one(allergens=[" Nuts", "NUTS"], dietary_tags="Halal"), TODAY)[0]
    assert out["allergens"] == ["nuts"] and out["dietary_tags"] == ["halal"]
    assert out["unit"] == "unit" and out["category"] == ""


# ---------- helpers ----------
@pytest.mark.parametrize("raw,expected", [
    (None, []), ("Nuts", ["nuts"]), ([" Nuts", "nuts", "", "Milk"], ["nuts", "milk"]), ([], [])])
def test_clean_list(raw, expected):
    assert clean_list(raw) == expected


def test_parse_date_accepts_str_date_datetime():
    assert parse_date("2026-09-15") == TODAY
    assert parse_date(TODAY) == TODAY
    assert parse_date(datetime(2026, 9, 15, 8, 0)) == TODAY


@pytest.mark.parametrize("bad", ["2026/09/15", "", None, "15-09-2026", "2026-02-30"])
def test_parse_date_invalid(bad):
    with pytest.raises(ValidationError):
        parse_date(bad)


@pytest.mark.parametrize("text", ["2026-09-15 10:30", "2026-09-15T10:30", "2026-09-15T10:30:45"])
def test_parse_datetime_valid_formats(text):
    assert parse_datetime(text).date() == TODAY


@pytest.mark.parametrize("bad", ["tomorrow", "2026-09-15", "10:30"])
def test_parse_datetime_invalid(bad):
    with pytest.raises(ValidationError):
        parse_datetime(bad)


# ---------- NFR-03 respectful language ----------
@pytest.mark.req("NFR-03", "AC-15")
def test_respectful_text_passes():
    check_respectful("Substituted tinned peas for beans as requested.")


@pytest.mark.req("NFR-03", "AC-15")
@pytest.mark.parametrize("text", ["Typical freeloader", "she is a CHARITY CASE", "just a handout", "so lazy"])
def test_disrespectful_text_rejected_case_insensitive(text):
    with pytest.raises(ValidationError) as ei:
        check_respectful(text)
    assert "note" in ei.value.fields
