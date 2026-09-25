import io
import pytest
from app import create_app
from app.extensions import db
from app.models import Player, PlayerRole, PlayerCategory, PlayerStatus
from app.services.seed_service import seed_database

@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        seed_database()
        yield app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def admin_client(client):
    client.post('/login', data={'username': 'admin', 'password': 'SPLAdmin@2026!'})
    return client

def test_admin_add_player_manually(admin_client, app):
    response = admin_client.post('/admin/players/add', data={
        'roll_number': '101',
        'name': 'Rahul Sharma',
        'role': 'BATSMAN',
        'branch': 'CSE',
        'year': '3',
        'category': 'MARQUEE',
        'base_price': '15000'
    }, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        player = Player.query.filter_by(roll_number='101').first()
        assert player is not None
        assert player.name == 'Rahul Sharma'
        assert player.role == PlayerRole.BATSMAN
        assert player.category == PlayerCategory.MARQUEE
        assert player.base_price == 15000.0

def test_admin_edit_player(admin_client, app):
    with app.app_context():
        player = Player(roll_number='102', name='Original Name', role='BOWLER', category='NORMAL', base_price=10000.0)
        db.session.add(player)
        db.session.commit()
        player_id = player.id

    response = admin_client.post(f'/admin/players/{player_id}/edit', data={
        'roll_number': '102',
        'name': 'Updated Name',
        'role': 'ALL_ROUNDER',
        'category': 'PREMIUM',
        'base_price': '25000',
        'status': 'AVAILABLE'
    }, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        updated = db.session.get(Player, player_id)
        assert updated.name == 'Updated Name'
        assert updated.role == PlayerRole.ALL_ROUNDER
        assert updated.category == PlayerCategory.PREMIUM

def test_admin_delete_player(admin_client, app):
    with app.app_context():
        player = Player(roll_number='103', name='To Delete', role='BATSMAN')
        db.session.add(player)
        db.session.commit()
        player_id = player.id

    response = admin_client.post(f'/admin/players/{player_id}/delete', follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        deleted = db.session.get(Player, player_id)
        assert deleted is None

def test_csv_import_valid_and_invalid_rows(admin_client, app):
    csv_data = (
        "roll_number,name,photo,role,branch,year,experience,category,base_price\n"
        "201,Karan Johar,photo1.jpg,BATSMAN,ECE,2,State Level,MARQUEE,20000\n"
        "202,Vijay Kumar,photo2.jpg,BOWLER,EEE,4,College Team,PREMIUM,15000\n"
        "201,Duplicate Person,,BATSMAN,CSE,1,,NORMAL,10000\n"
        ",No Roll,,BATSMAN,CSE,1,,NORMAL,10000\n"
        "203,Invalid Role,,SUPERMAN,CSE,1,,NORMAL,10000\n"
    )

    data = {
        'csv_file': (io.BytesIO(csv_data.encode('utf-8')), 'players.csv')
    }

    response = admin_client.post('/admin/players/import-csv', data=data, content_type='multipart/form-data', follow_redirects=True)
    assert response.status_code == 200
    assert b'CSV Import Summary' in response.data or b'Imported' in response.data or b'Skipped' in response.data

    with app.app_context():
        p1 = Player.query.filter_by(roll_number='201').first()
        p2 = Player.query.filter_by(roll_number='202').first()
        p3 = Player.query.filter_by(roll_number='203').first()

        assert p1 is not None
        assert p1.name == 'Karan Johar'
        assert p2 is not None
        assert p2.name == 'Vijay Kumar'
        assert p3 is None
