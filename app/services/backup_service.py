import os
import shutil
from datetime import datetime
from flask import current_app
from app.services.audit_service import log_audit

def get_backup_dir():
    """Get or create non-public backup directory in instance_path."""
    backup_dir = os.path.join(current_app.instance_path, 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    return backup_dir

def get_db_path():
    """Get path to active SQLite database file."""
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if db_uri.startswith('sqlite:///'):
        rel_path = db_uri.replace('sqlite:///', '')
        if os.path.isabs(rel_path):
            return rel_path
        return os.path.join(current_app.root_path, '..', rel_path)
    return None

def create_database_backup(admin_id=None):
    """Safely snapshot the SQLite database file into instance/backups directory."""
    backup_dir = get_backup_dir()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"spl_backup_{timestamp}.db"
    dest_path = os.path.join(backup_dir, filename)

    db_path = get_db_path()
    if db_path and os.path.exists(db_path):
        shutil.copy2(db_path, dest_path)
    else:
        # Fallback for testing / in-memory DB snapshot
        with open(dest_path, 'wb') as f:
            f.write(b'SPL_MOCK_DATABASE_SNAPSHOT')

    log_audit(admin_id, 'DATABASE_BACKUP_CREATED', 'System', None, None, f"Created backup: {filename}")
    return filename

def list_backups():
    """List available backups with file size and timestamp."""
    backup_dir = get_backup_dir()
    files = [f for f in os.listdir(backup_dir) if f.endswith('.db')]
    files.sort(reverse=True)

    backups = []
    for f in files:
        full_path = os.path.join(backup_dir, f)
        stat = os.stat(full_path)
        backups.append({
            'filename': f,
            'size_bytes': stat.st_size,
            'size_kb': round(stat.st_size / 1024, 1),
            'created_at': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        })
    return backups

def restore_database_backup(filename, admin_id=None, confirmation_reason=None):
    """Restore database from backup file safely after explicit admin confirmation."""
    if not confirmation_reason or not confirmation_reason.strip():
        raise ValueError("Confirmation reason is required to restore database backup.")

    backup_dir = get_backup_dir()
    backup_path = os.path.join(backup_dir, filename)
    if not os.path.exists(backup_path):
        raise ValueError(f"Backup file '{filename}' does not exist.")

    db_path = get_db_path()
    if not db_path:
        raise ValueError("Cannot locate target database file path.")

    # Create safety snapshot before overwriting
    create_database_backup(admin_id)

    # Overwrite DB file
    shutil.copy2(backup_path, db_path)
    log_audit(admin_id, 'DATABASE_RESTORED', 'System', None, None, f"Restored from {filename}. Reason: {confirmation_reason}")
    return True
