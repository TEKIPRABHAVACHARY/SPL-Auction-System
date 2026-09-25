from datetime import datetime
from app.extensions import db

class PlayerRole:
    BATSMAN = 'BATSMAN'
    BOWLER = 'BOWLER'
    ALL_ROUNDER = 'ALL_ROUNDER'
    WICKETKEEPER = 'WICKETKEEPER'

    CHOICES = [BATSMAN, BOWLER, ALL_ROUNDER, WICKETKEEPER]

class PlayerCategory:
    MARQUEE = 'MARQUEE'
    PREMIUM = 'PREMIUM'
    COMPETITIVE = 'COMPETITIVE'
    EMERGING = 'EMERGING'
    NORMAL = 'NORMAL'

    CHOICES = [MARQUEE, PREMIUM, COMPETITIVE, EMERGING, NORMAL]

class PlayerStatus:
    AVAILABLE = 'AVAILABLE'
    SOLD = 'SOLD'
    UNSOLD = 'UNSOLD'
    FINAL_UNSOLD = 'FINAL_UNSOLD'

    CHOICES = [AVAILABLE, SOLD, UNSOLD, FINAL_UNSOLD]

class Player(db.Model):
    __tablename__ = 'players'

    id = db.Column(db.Integer, primary_key=True)
    roll_number = db.Column(db.String(30), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    photo = db.Column(db.String(255), nullable=True)
    role = db.Column(db.String(50), nullable=False, default=PlayerRole.BATSMAN)
    branch = db.Column(db.String(50), nullable=True)
    year = db.Column(db.String(20), nullable=True)
    experience = db.Column(db.String(255), nullable=True)
    category = db.Column(db.String(50), nullable=False, default=PlayerCategory.NORMAL)
    base_price = db.Column(db.Float, default=10000.0, nullable=False)
    status = db.Column(db.String(30), default=PlayerStatus.AVAILABLE, nullable=False)
    is_second_chance_eligible = db.Column(db.Boolean, default=False, nullable=False)
    sold_to = db.Column(db.Integer, db.ForeignKey('franchises.id'), nullable=True)
    sold_price = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    franchise = db.relationship('Franchise', foreign_keys=[sold_to], back_populates='sold_players')

    def to_dict(self):
        return {
            'id': self.id,
            'roll_number': self.roll_number,
            'name': self.name,
            'photo': self.photo,
            'role': self.role,
            'branch': self.branch,
            'year': self.year,
            'experience': self.experience,
            'category': self.category,
            'base_price': self.base_price,
            'status': self.status,
            'is_second_chance_eligible': self.is_second_chance_eligible,
            'sold_to': self.sold_to,
            'sold_price': self.sold_price
        }

    def __repr__(self):
        return f'<Player {self.name} ({self.roll_number}) - {self.category}>'
