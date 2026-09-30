import os
from app import create_app
from app.extensions import db
from app.services.seed_service import seed_database
from app.services.db_sync_service import sync_database_schema

app = create_app(os.environ.get('FLASK_ENV', 'dev'))

@app.cli.command('init-db')
def init_db_command():
    """Clear existing data and create new JSON storage with initial seed data."""
    db.create_all()
    sync_database_schema()
    seed_database()
    print("JSON storage initialized and seeded successfully.")

with app.app_context():
    # Ensure tables, columns, and seed data exist on startup
    db.create_all()
    sync_database_schema()
    seed_database()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if port == 5000 and s.connect_ex(('127.0.0.1', 5000)) == 0:
            print("[INFO] Port 5000 is currently in use (macOS AirPlay Receiver). Switching to port 5001.")
            port = 5001
    print(f"[INFO] Starting SPL Auction System on http://127.0.0.1:{port}/")
    app.run(host='127.0.0.1', port=port, debug=True)

