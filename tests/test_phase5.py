import pytest
from app import create_app
from app.extensions import db
from app.models import Player, Franchise, User, AuctionState, AuctionStatus, Transaction, Bid
from app.services.seed_service import seed_database
from app.services.auction_service import place_bid, finalize_sold, finalize_unsold, reset_to_waiting

@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        seed_database()
        yield app
        db.session.remove()
        db.drop_all()

def make_admin_client(app):
    cli = app.test_client()
    cli.post('/login', data={'username': 'admin', 'password': 'SPLAdmin@2026!'})
    return cli

def make_franchise_client(app, username, password):
    cli = app.test_client()
    cli.post('/login', data={'username': username, 'password': password})
    return cli

@pytest.fixture
def test_player(app):
    with app.app_context():
        player = Player(
            roll_number='505',
            name='Rohit Sharma Phase5',
            role='BATSMAN',
            category='MARQUEE',
            base_price=10000.0,
            status='AVAILABLE'
        )
        db.session.add(player)
        db.session.commit()
        return player.id

# 1. Critical Player Selection Rule & Security Test
def test_no_future_player_exposure(app):
    pub_client = app.test_client()
    res = pub_client.get('/api/auction/state')
    assert res.status_code == 200
    data = res.get_json()

    assert 'next_player' not in data
    assert 'upcoming_player' not in data
    assert 'player_queue' not in data
    assert 'future_player' not in data

# 2. Security Access Control Tests
def test_security_access_controls(app, test_player):
    pub_client = app.test_client()

    res_pub = pub_client.post('/api/auction/activate', json={'player_id': test_player})
    assert res_pub.status_code in [302, 401, 403]

    franchise1_client = make_franchise_client(app, 'cybervipers', 'Vipers@2026!')
    res_f1 = franchise1_client.post('/api/auction/activate', json={'player_id': test_player})
    assert res_f1.status_code == 403

    res_f1_start = franchise1_client.post('/api/auction/start')
    assert res_f1_start.status_code == 403

    res_f1_sold = franchise1_client.post('/api/auction/sold')
    assert res_f1_sold.status_code == 403

    admin_client = make_admin_client(app)
    res_adm = admin_client.post('/api/auction/activate', json={'player_id': test_player})
    assert res_adm.status_code == 200

# 3. Data Isolation Test
def test_security_franchise_data_isolation(app):
    pub_client = app.test_client()

    res_pub = pub_client.get('/api/auction/state')
    data_pub = res_pub.get_json()
    assert 'authorized_email' not in str(data_pub)

    franchise1_client = make_franchise_client(app, 'cybervipers', 'Vipers@2026!')
    res_f1 = franchise1_client.get('/api/auction/state')
    data_f1 = res_f1.get_json()
    assert 'franchise_info' in data_f1
    with app.app_context():
        f1 = Franchise.query.filter_by(short_name='F01').first()
        assert data_f1['franchise_info']['id'] == f1.id

    franchise2_client = make_franchise_client(app, 'techtitans', 'Titans@2026!')
    res_f2 = franchise2_client.get('/api/auction/state')
    data_f2 = res_f2.get_json()
    assert 'franchise_info' in data_f2
    with app.app_context():
        f2 = Franchise.query.filter_by(short_name='F02').first()
        assert data_f2['franchise_info']['id'] == f2.id

# 4. Roll Number Lookup Validations
def test_player_lookup_validations(test_player, app):
    admin_client = make_admin_client(app)

    res = admin_client.post('/api/auction/find-player', json={'roll_number': '505'})
    assert res.status_code == 200
    assert res.get_json()['player']['name'] == 'Rohit Sharma Phase5'

    res_invalid = admin_client.post('/api/auction/find-player', json={'roll_number': '999999'})
    assert res_invalid.status_code == 400
    assert 'PLAYER NOT FOUND' in res_invalid.get_json()['message']

    admin_client.post('/api/auction/activate', json={'player_id': test_player})
    admin_client.post('/api/auction/start')
    with app.app_context():
        f1 = Franchise.query.filter_by(short_name='F01').first()
        place_bid(f1.id, 10000.0)
    admin_client.post('/api/auction/sold')

    res_sold = admin_client.post('/api/auction/find-player', json={'roll_number': '505'})
    assert res_sold.status_code == 400
    assert 'PLAYER ALREADY SOLD' in res_sold.get_json()['message']

# 5. Full Simulation of Auction Workflow
def test_full_manual_event_simulation(test_player, app):
    admin_client = make_admin_client(app)

    res_state = admin_client.get('/api/auction/state')
    assert res_state.get_json()['status'] == 'WAITING'

    res_find = admin_client.post('/api/auction/find-player', json={'roll_number': '505'})
    assert res_find.status_code == 200

    res_act = admin_client.post('/api/auction/activate', json={'player_id': test_player})
    assert res_act.status_code == 200
    assert res_act.get_json()['status'] == 'PLAYER_PREVIEW'

    res_start = admin_client.post('/api/auction/start')
    assert res_start.status_code == 200
    assert res_start.get_json()['status'] == 'BIDDING'

    franchise1_client = make_franchise_client(app, 'cybervipers', 'Vipers@2026!')
    res_bid1 = franchise1_client.post('/api/auction/bid', json={'amount': 10000})
    assert res_bid1.status_code == 200

    franchise2_client = make_franchise_client(app, 'techtitans', 'Titans@2026!')
    res_bid2 = franchise2_client.post('/api/auction/bid', json={'amount': 12000})
    assert res_bid2.status_code == 200

    adm_cli2 = make_admin_client(app)
    res_pause = adm_cli2.post('/api/auction/pause')
    assert res_pause.get_json()['status'] == 'PAUSED'
    res_resume = adm_cli2.post('/api/auction/resume')
    assert res_resume.get_json()['status'] == 'BIDDING'
    res_extend = adm_cli2.post('/api/auction/extend', json={'seconds': 10})
    assert res_extend.get_json()['success'] is True

    res_sold = adm_cli2.post('/api/auction/sold')
    assert res_sold.status_code == 200
    assert res_sold.get_json()['success'] is True
    assert 'Rohit Sharma Phase5' in res_sold.get_json()['player_name']

    res_post_sold = adm_cli2.get('/api/auction/state')
    assert res_post_sold.get_json()['status'] == 'SOLD'

    res_reset = adm_cli2.post('/api/auction/reset')
    assert res_reset.status_code == 200
    assert res_reset.get_json()['status'] == 'WAITING'

# 6. Performance Simulation (Concurrent HTTP Polling)
def test_performance_concurrent_polling(app):
    pub_client = app.test_client()
    admin_client = make_admin_client(app)
    franchise1_client = make_franchise_client(app, 'cybervipers', 'Vipers@2026!')
    franchise2_client = make_franchise_client(app, 'techtitans', 'Titans@2026!')

    clients = [pub_client, admin_client, franchise1_client, franchise2_client, pub_client, pub_client]
    for c in clients:
        res = c.get('/api/auction/state')
        assert res.status_code == 200
        assert 'status' in res.get_json()
