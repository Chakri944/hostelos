"""
Copy local HostelOS SQLite records into an EMPTY PostgreSQL database.
Set DATABASE_URL to the PostgreSQL URL and SQLITE_PATH to the local SQLite path.
Run once from the project root: python scripts/migrate_sqlite_to_postgres.py
"""
import os
from sqlalchemy import create_engine, select, text
from app.database import engine as target_engine
from app.database import Base
from app import models  # register model metadata

sqlite_path = os.getenv("SQLITE_PATH", "hostelos.db")
if not os.path.exists(sqlite_path):
    raise SystemExit(f"SQLite source not found: {sqlite_path}")
if target_engine.dialect.name != "postgresql":
    raise SystemExit("DATABASE_URL must point to PostgreSQL.")

source_engine = create_engine(f"sqlite:///{os.path.abspath(sqlite_path)}")
Base.metadata.create_all(bind=target_engine)

with target_engine.connect() as conn:
    counts = {}
    for table in Base.metadata.sorted_tables:
        counts[table.name] = conn.execute(text(f'SELECT COUNT(*) FROM "{table.name}"')).scalar_one()
    if any(counts.values()):
        raise SystemExit("Target PostgreSQL database is not empty. Migration stopped to prevent overwriting records.")

with source_engine.connect() as source, target_engine.begin() as target:
    for table in Base.metadata.sorted_tables:
        rows = source.execute(select(table)).mappings().all()
        if rows:
            target.execute(table.insert(), [dict(row) for row in rows])

with target_engine.begin() as conn:
    for table in Base.metadata.sorted_tables:
        if "id" in table.c:
            sequence = conn.execute(
                text("SELECT pg_get_serial_sequence(:table_name, 'id')"),
                {"table_name": table.name}
            ).scalar()
            if sequence:
                conn.execute(
                    text(f"SELECT setval(CAST(:sequence AS regclass), COALESCE((SELECT MAX(id) FROM \"{table.name}\"), 1), true)"),
                    {"sequence": sequence}
                )

source_engine.dispose()
print("Migration complete. Verify table counts and sample tenant/payment histories before switching over.")
