from sqlalchemy import inspect, text
from .database import engine

def run_sqlite_migrations():
    if engine.dialect.name != "sqlite":
        return
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "residents" not in tables:
        return
    with engine.begin() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(residents)")).fetchall()}
        if "checkout_date" not in cols:
            conn.execute(text("ALTER TABLE residents ADD COLUMN checkout_date DATE"))
        if "joining_date" not in cols:
            conn.execute(text("ALTER TABLE residents ADD COLUMN joining_date DATE"))
        if "rent_due_day" not in cols:
            conn.execute(text("ALTER TABLE residents ADD COLUMN rent_due_day INTEGER NOT NULL DEFAULT 5"))
        if "reminder_enabled" not in cols:
            conn.execute(text("ALTER TABLE residents ADD COLUMN reminder_enabled BOOLEAN NOT NULL DEFAULT 1"))
        pcols = {r[1] for r in conn.execute(text("PRAGMA table_info(payments)")).fetchall()}
        if "cycle_id" not in pcols:
            conn.execute(text("ALTER TABLE payments ADD COLUMN cycle_id INTEGER"))
