from datetime import datetime
from app.extensions import db

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    franchise_id = db.Column(db.Integer, db.ForeignKey('franchises.id'), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    target_type = db.Column(db.String(50), nullable=True)
    target_id = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(20), default='SUCCESS', nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    admin = db.relationship('User', foreign_keys=[admin_id])
    franchise = db.relationship('Franchise', foreign_keys=[franchise_id])

    def __repr__(self):
        return f'<AuditLog admin_id={self.admin_id} action={self.action}>'
