from datetime import datetime
from app.extensions import db

class Franchise(db.Model):
    __tablename__ = 'franchises'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    short_name = db.Column(db.String(20), nullable=False, unique=True)
    logo = db.Column(db.String(255), nullable=True)
    authorized_email = db.Column(db.String(120), unique=True, nullable=True, index=True)
    owner_name = db.Column(db.String(100), nullable=True)
    google_auth_enabled = db.Column(db.Boolean, default=True, nullable=False)
    starting_purse = db.Column(db.Float, nullable=False, default=500000.0)
    remaining_purse = db.Column(db.Float, nullable=False, default=500000.0)
    squad_limit = db.Column(db.Integer, nullable=False, default=15)
    captain_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=True)
    vice_captain_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    users = db.relationship('User', back_populates='franchise', lazy='dynamic')
    sold_players = db.relationship('Player', foreign_keys='Player.sold_to', back_populates='franchise', lazy='dynamic')
    captain = db.relationship('Player', foreign_keys=[captain_id])
    vice_captain = db.relationship('Player', foreign_keys=[vice_captain_id])

    @property
    def spent_purse(self):
        return self.starting_purse - self.remaining_purse

    @property
    def squad_count(self):
        return self.sold_players.count()

    def set_authorized_email(self, email):
        if email:
            self.authorized_email = email.strip().lower()
        else:
            self.authorized_email = None

    def __repr__(self):
        return f'<Franchise {self.short_name} - {self.name} ({self.authorized_email})>'
