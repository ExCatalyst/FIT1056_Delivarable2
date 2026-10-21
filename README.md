# FoodShare Tracker

A local Python and Streamlit MVP for food bank staff, volunteers and administrators.
The frontend calls the existing `FoodShareApp` services for all business operations.

## Run the app

Open a terminal in this repository. Use Python 3.10 or later.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m streamlit run streamlit_app.py
```

Open the local URL printed in the terminal. On first use, create the administrator
account in the setup form. There are no built-in passwords or pre-created accounts.
An administrator then creates staff and volunteer accounts in **Accounts and audit**.
Use the same site name for staff and volunteers who work together.

The included `data/foodshare.json` is an empty placeholder. To avoid replacing it,
the frontend uses `data/foodshare-local.json`, which is created automatically on
first use and ignored by Git. Backups go into `data/backups/` and are ignored too.
Do not commit real client details, credentials or backups.

To use another data file, set this variable **before** starting Streamlit:

```powershell
$env:FOODSHARE_DATA_FILE = "C:\path\to\foodshare.json"
```

Use one Streamlit process for a local demonstration. Its cached `FoodShareApp`
shares one store/lock across sessions. The JSON backend is not a deployment-ready
multi-process or multi-site database. Do not edit its data file externally while
the app is running; stop and restart the server when changing the data source.

## MVP scope and permissions

| Role | Screens and permitted actions |
| --- | --- |
| Staff | Record and decide donation offers; search/update inventory; create/edit client profiles; build suitable hampers, record substitutions and pickup times, complete orders; assign tasks and review issues; view reports. |
| Volunteer | View inventory and mark food conditions; see only their assigned tasks; update task progress; view a linked hamper's food list, pickup reference and safety flag; report stock/hamper problems. |
| Admin | Review inventory, donations, client profiles, orders, tasks and cross-site reports; create/manage internal accounts; filter audit records; make/restore local backups. |

Permissions follow the existing backend. Admins do not perform staff-only operational
changes. Use a separate staff account to demonstrate those workflows. Volunteers
cannot open full client profiles, account management or reports. Completing a
volunteer task does not complete an order or deduct stock.

Clients and donors have no self-service frontend in this MVP. Staff enter their
details on their behalf, following the agreed interpretation of the team report's
MVP scope. Email/SMS notifications are also outside the agreed scope.

## Main workflows

1. **Account setup:** Admin creates a staff account and a volunteer account at the same site.
2. **Receive food:** Staff record an offer in Donations. Review the offer, select
   Received, confirm, and save. Its food batches then appear in Inventory.
3. **Record needs:** Staff create a client profile with household size, allergies,
   dietary/cultural preferences and accessibility needs. Only necessary details are collected.
4. **Prepare a hamper:** Staff create an order for the client, add suitable food,
   check any dietary warnings, optionally record a substitution note, and arrange pickup.
   Recorded allergens and unavailable/expired food are excluded by the service.
5. **Assign packing:** Staff assign a task to an active volunteer from their site,
   linking the hamper if appropriate. Keep personal client details out of task instructions.
6. **Volunteer work:** Volunteer opens the assigned task, checks the safety flag,
   updates progress, or submits an issue. Staff review issues and make any operational corrections.
7. **Distribute food:** Staff confirm collection and complete the order. This is
   the point where the exact quantities are deducted from inventory.
8. **Review:** Staff/admins generate stock movement or demand reports and download
   CSVs. Admins can filter audit activity by group, account, date and site.

## Code guide

| File/folder | Purpose |
| --- | --- |
| `streamlit_app.py` | Startup, sign-in, session clearing, role-based navigation and error boundary. |
| `ui/dashboard.py` | Role-specific overview and low-stock reminders. |
| `ui/donations.py` | Donation form, offer list and receiving/rejection. |
| `ui/inventory.py` | Search, condition, low-stock and near-expiry filters; condition updates. |
| `ui/clients.py` | Staff-assisted profile forms and authorised review. |
| `ui/orders.py` | Suitable food selection, quantities, substitution notes, status, pickup and completion. |
| `ui/tasks.py` | Task assignment, volunteer packing views, progress and issue review. |
| `ui/reports.py` | Stock/demand reports and CSV downloads. |
| `ui/admin.py` | Account creation, roles, activation/unlocking, audit and backups. |
| `ui/common.py` | Shared tables, readable errors, confirmations and form cancellation. |
| `app/` | Existing application/domain/storage services. |
| `.streamlit/config.toml` | Native light theme with green primary controls and dark text. |
| `tests/test_frontend.py` | User-facing checks with isolated temporary data. |

One small backend integration was needed: `TaskService.assignable_volunteers`.
It returns only active, unlocked same-site volunteer identifiers and display names
to staff. It does not expose password hashes, salts or the full account directory.

## Automated checks

```powershell
.venv\Scripts\python -m pytest tests/test_frontend.py -q
```

The checks use Streamlit's AppTest and temporary JSON files. They cover internal
roles/screens, first-run setup and invalid sign-in, donation validation/cancel,
allergen exclusion, confirmed order completion and stock deduction, volunteer
privacy/progress/issues, live role changes, report date validation, safe volunteer
selection, client creation, task assignment, account creation and stock conditions.

These frontend checks are part of the team's QA work, not a claim that every backend
function or every project requirement has complete test coverage. Expand the team's
test plan with the required equivalence classes, boundaries and MC/DC evidence.

## Accessibility and usability review still needed

The UI uses labelled native controls, a consistent light theme, clear section
headings, text-based statuses, empty-state guidance, validation messages and
confirmation for consequential changes. Major entry forms have Cancel / clear
controls; navigation allows returning to the dashboard without saving.

Before submission, perform and record real checks rather than treating this list
as evidence that testing happened:

- Use browser zoom at **200%** on donation, inventory, task and hamper screens;
  check readability and whether tables/controls need scrolling.
- Measure normal-text contrast against the report's **4.5:1** target and check
  keyboard navigation, focus visibility and labelled controls in a browser.
- Run the report's persona think-aloud scenarios (UT-01 through UT-07), recording
  completion, errors and feedback. Do not present automated tests as user feedback.
- Verify the **two-second inventory search target with 500 records** on the target device.
- Exercise backup/restore using disposable demonstration data, including the
  possibility that accounts created after a backup disappear when it is restored.

An automated browser was unavailable in the development session. AppTest rendering
and workflow checks passed, but visual layout, 200% zoom and browser-specific
keyboard/accessibility behaviour still need this manual review.

## Known boundaries for the final report

- Inventory uses the fields currently supported by the backend. Dedicated storage
  requirement fields and a configured four-site directory are not implemented.
  Administrators enter consistent site identifiers when creating accounts.
- Low-stock reminders use the backend's available-quantity totals by food name.
  They do not infer expected food types that have no available batches, or convert units.
- A volunteer's issue report flags food/orders for staff review. It does not itself
  change stock condition, final order state or inventory quantities.
- Backup controls are available after a valid local data file has loaded. A corrupt
  file that prevents startup needs administrator recovery outside the UI.
- Role/account changes are refreshed on the next user interaction. The server does
  not push updates to idle browser sessions automatically.

No report diagrams, user-testing findings or individual contribution claims are
generated by this frontend. Update those deliverables using the actual implementation
and genuine team evaluation evidence.
