import os
from app import create_app
from app.extensions import db
from app.services.seed_service import seed_database
from app.services.db_sync_service import sync_database_schema

app = create_app(os.environ.get('FLASK_ENV', 'dev'))

@app.cli.command('init-db')
def init_db_command():
    """Clear existing data and create new tables with initial seed data."""
    db.create_all()
    sync_database_schema()
    seed_database()
    print("Database initialized and seeded successfully.")

with app.app_context():
    # Ensure tables, columns, and seed data exist on startup
    db.create_all()
    sync_database_schema()
    seed_database()

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
