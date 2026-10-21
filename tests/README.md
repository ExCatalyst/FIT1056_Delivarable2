# FoodShare Tracker - automated tests

Layout expected:  `<project>/app/*.py`  (your backend package)  +  `<project>/tests/`  +  `<project>/pytest.ini`

    pip install pytest pytest-cov
    pytest -v                                   # run everything
    pytest --cov=foodshare --cov-branch --cov-report=term-missing

Before running, fix two bad imports in the backend:  `donations.py` -> `from .inventory import receive_donation`,
`orders.py` -> `from .security import check_site, has_permission, require`.
If your package folder is not called `app`, change the import in `conftest.py` and in the test files.

| File | Level | Technique |
|---|---|---|
| test_unit_validators / test_unit_security / test_unit_storage | unit | EP, BVA (quantity, expiry, password length), positive/negative/edge |
| test_auth, test_donations, test_inventory, test_clients, test_orders, test_tasks, test_reports_audit | service/functional per feature F-01..F-06 | EP, BVA, state transitions, RBAC |
| test_mcdc | decision logic | MC/DC on `is_available` (3 conditions) and quantity-edit authorisation (3 conditions) |
| test_nfr | NFR-04/05/06 | permission matrix, 500-record timing, backup/restore |
| test_functional_e2e | end-to-end | one scenario per use case UC-01..UC-06 + full donation->report chain |
| test_known_defects | defects | `xfail(strict=True)` tests describing expected behaviour for DEF-01..06 |

Every test carries `@pytest.mark.req("FR-..", "AC-..", "UC-..")`; each run writes `test_reports/traceability.csv`
(requirement -> test -> result) for the Requirements-Design-Test Traceability section.
