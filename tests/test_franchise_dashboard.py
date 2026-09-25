import pytest
from app import create_app
from app.extensions import db
from app.models import Franchise, User, Player, Bid, Transaction
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
def franchise_a_client(app):
    cl = app.test_client()
    with app.app_context():
        user = User.query.filter_by(username='cybervipers').first()
        u_id = str(user.id)
    with cl.session_transaction() as sess:
        sess['_user_id'] = u_id
        sess['_fresh'] = True
    return cl

@pytest.fixture
def franchise_b_client(app):
    cl = app.test_client()
    with app.app_context():
        user = User.query.filter_by(username='techtitans').first()
        u_id = str(user.id)
    with cl.session_transaction() as sess:
        sess['_user_id'] = u_id
        sess['_fresh'] = True
    return cl

@pytest.fixture
def admin_client(app):
    cl = app.test_client()
    cl.post('/login', data={'username': 'admin', 'password': 'SPLAdmin@2026!'})
    return cl

def test_franchise_a_dashboard_access(franchise_a_client):
    response = franchise_a_client.get('/franchise/dashboard')
    assert response.status_code == 200
    assert b'Cyber Vipers' in response.data
    assert b'Tech Titans' not in response.data

def test_franchise_b_dashboard_access(franchise_b_client):
    response = franchise_b_client.get('/franchise/dashboard')
    assert response.status_code == 200
    assert b'Tech Titans' in response.data
    assert b'Cyber Vipers' not in response.data

def test_client_franchise_id_parameter_ignored(franchise_a_client):
    response = franchise_a_client.get('/franchise/dashboard?franchise_id=2')
    assert response.status_code == 200
    assert b'Cyber Vipers' in response.data
    assert b'Tech Titans' not in response.data

def test_franchise_squad_view_and_analytics(app, franchise_a_client):
    with app.app_context():
        f1 = Franchise.query.filter_by(short_name='F01').first()
        p1 = Player(roll_number='P101', name='Batsman 1', role='BATSMAN', category='MARQUEE', sold_to=f1.id, sold_price=50000.0, status='SOLD')
        p2 = Player(roll_number='P102', name='Bowler 1', role='BOWLER', category='PREMIUM', sold_to=f1.id, sold_price=30000.0, status='SOLD')
        db.session.add_all([p1, p2])
        db.session.commit()

    response = franchise_a_client.get('/franchise/squad')
    assert response.status_code == 200
    assert b'Batsman 1' in response.data
    assert b'Bowler 1' in response.data

def test_franchise_purchases_and_bids_view(app, franchise_a_client):
    with app.app_context():
        f1 = Franchise.query.filter_by(short_name='F01').first()
        p = Player(roll_number='P103', name='Player Three', status='SOLD', sold_to=f1.id, sold_price=40000.0)
        db.session.add(p)
        db.session.commit()

        tx = Transaction(player_id=p.id, franchise_id=f1.id, amount=40000.0, type='PURCHASE')
        bid = Bid(player_id=p.id, franchise_id=f1.id, amount=40000.0)
        db.session.add_all([tx, bid])
        db.session.commit()

    res_purchases = franchise_a_client.get('/franchise/purchases')
    assert res_purchases.status_code == 200
    assert b'Player Three' in res_purchases.data

    res_bids = franchise_a_client.get('/franchise/bids')
    assert res_bids.status_code == 200
    assert b'Player Three' in res_bids.data

def test_franchise_activity_and_profile_views(franchise_a_client):
    res_activity = franchise_a_client.get('/franchise/activity')
    assert res_activity.status_code == 200

    res_profile = franchise_a_client.get('/franchise/profile')
    assert res_profile.status_code == 200
    assert b'Cyber Vipers' in res_profile.data

def test_franchise_cannot_access_admin_routes(franchise_a_client):
    res = franchise_a_client.get('/admin/dashboard')
    assert res.status_code == 403

    res_players = franchise_a_client.get('/admin/players')
    assert res_players.status_code == 403

def test_franchise_api_data_isolation(app):
    client1 = app.test_client()
    client1.post('/login', data={'username': 'cybervipers', 'password': 'Vipers@2026!'})
    res_a = client1.get('/franchise/api/dashboard')
    assert res_a.status_code == 200
    assert res_a.get_json()['short_name'] == 'F01'

    client2 = app.test_client()
    client2.post('/login', data={'username': 'techtitans', 'password': 'Titans@2026!'})
    res_b = client2.get('/franchise/api/dashboard')
    assert res_b.status_code == 200
    assert res_b.get_json()['short_name'] == 'F02'

def test_admin_inspect_franchise(admin_client, app):
    with app.app_context():
        f1 = Franchise.query.filter_by(short_name='F01').first()
        f1_id = f1.id

    response = admin_client.get(f'/admin/franchises/{f1_id}/inspect')
    assert response.status_code == 200
    assert b'Cyber Vipers' in response.data
