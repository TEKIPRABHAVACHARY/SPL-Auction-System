import sqlalchemy as sa
from app.extensions import db

def sync_database_schema(app=None):
    """
    Auto-migrates any missing columns in existing SQLite database tables
    to match SQLAlchemy models without losing existing table data.
    """
    if app:
        with app.app_context():
            _do_sync()
    else:
        _do_sync()

def _do_sync():
    try:
        inspector = sa.inspect(db.engine)
        existing_tables = inspector.get_table_names()

        for table_name, table in db.metadata.tables.items():
            if table_name not in existing_tables:
                continue

            existing_columns = {c['name'] for c in inspector.get_columns(table_name)}
            for column in table.columns:
                if column.name not in existing_columns:
                    col_type = column.type.compile(db.engine.dialect)
                    default_clause = ""
                    if column.default is not None and column.default.arg is not None:
                        val = column.default.arg
                        if isinstance(val, bool):
                            default_clause = f" DEFAULT {1 if val else 0}"
                        elif isinstance(val, (int, float)):
                            default_clause = f" DEFAULT {val}"
                        elif isinstance(val, str):
                            default_clause = f" DEFAULT '{val}'"

                    alter_sql = f"ALTER TABLE {table_name} ADD COLUMN {column.name} {col_type}{default_clause}"
                    with db.engine.connect() as conn:
                        conn.execute(sa.text(alter_sql))
                        conn.commit()
                    print(f"[DB SYNC] Auto-migrated missing column: {table_name}.{column.name}")
    except Exception as e:
        print(f"[DB SYNC] Warning during schema sync: {e}")
