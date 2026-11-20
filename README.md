
# HostelOS Core v1

A focused hostel admin system with four sections: Dashboard, Rooms & Beds, Tenants, and Fees & Payments.

## Run (Windows PowerShell)
```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```
Open http://127.0.0.1:8000

## Core rules
- Register rooms with a bed capacity; beds B1...Bn are created automatically.
- Tenant joining date anchors the recurring monthly rent cycle.
- First full month's rent is created immediately on the joining date.
- Later cycles recur on the original joining day. For short months, the due date is that month's final day; the original anchor day is retained for later months.
- Payments are allocated to a specific rent cycle. Partial payments are supported.
- Dashboard metrics: this month's collections, outstanding dues, active tenants, and cycles due today/overdue.
- Tenant checkout releases the assigned bed.

## Database
SQLite is used by default in `app/database.py` for local setup. New rent cycles are stored in `rent_cycles`; existing database data is preserved with additive SQLite migrations. Back up `hostelos.db` before upgrading.

## WhatsApp
WhatsApp sending is intentionally not part of this core release. It will be reconnected after rent cycle and payment logic is tested end-to-end.


## v1.7 — Tenant editing
- Edit tenant name and mobile number.
- Update monthly rent; only future, unstarted cycles with no payments are updated.
- Reassign active tenants to an available bed; the previous bed is released.
- Checked-out tenant room/bed assignment is locked.
- Existing rent cycles and payment history are preserved; joining date is not editable.
\n\n## v1.8 — Search and filters\n- Search tenant directory by name or phone number.\n- Filter tenant directory by Active / Checked Out and room.\n- Search unpaid rent cycles by tenant name or phone and filter by room.\n- Fees & Payments continues to show unpaid cycles only.\n
\n## v1.9 — Database backup and restore
- Download a consistent SQLite database snapshot from Backup & Restore.
- Restore a previously downloaded `.db`, `.sqlite`, or `.sqlite3` backup.
- Restore validates SQLite integrity and required HostelOS tables before replacing data.
- Before restore, the current database is copied into the `backups` folder as a safety copy.
- Uploaded restore files are limited to 100 MB.
- Keep downloaded backups somewhere separate from the computer running HostelOS.


## v2.0 — Owner login and cloud database preparation
- Added a single-owner email/password login gate. Credentials are supplied through ADMIN_EMAIL and ADMIN_PASSWORD environment variables; no default password is shipped.
- Login uses a signed, HttpOnly cookie with a 12-hour expiry. Set APP_ENV=production and a random SESSION_SECRET (at least 32 characters) in hosting.
- DATABASE_URL supports local SQLite and PostgreSQL via psycopg 3.
- SQLite-only migrations and local backup/restore are disabled for PostgreSQL deployments.
- Added `scripts/migrate_sqlite_to_postgres.py` to copy local SQLite records into an EMPTY PostgreSQL database. It refuses to import if target tables already contain records.
- Added `render.yaml` as a deployment starting point.
- This is a single-owner pilot; multi-owner registration and tenant-level data isolation are not implemented yet.

### Required hosting environment variables
- `ADMIN_EMAIL`: owner's login email.
- `ADMIN_PASSWORD`: strong unique password.
- `SESSION_SECRET`: random secret of at least 32 characters.
- `DATABASE_URL`: PostgreSQL connection string.
- `APP_ENV`: `production`.

### Local login testing
Set `ADMIN_EMAIL`, `ADMIN_PASSWORD`, and `SESSION_SECRET` before starting. No default login credentials are included.
