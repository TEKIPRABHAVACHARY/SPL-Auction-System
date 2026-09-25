import pytest
from app import create_app
from app.extensions import db
from app.models import Player, Franchise, User, AuctionState, AuctionStatus, Transaction, Bid, SystemSettings
from app.services.seed_service import seed_database
from app.services.auction_service import place_bid, finalize_sold, finalize_unsold

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

@pytest.fixture
def test_player(app):
    with app.app_context():
        player = Player(
            roll_number='301',
            name='Virat Kohli Test',
            role='BATSMAN',
            category='MARQUEE',
            base_price=10000.0,
            status='AVAILABLE'
        )
        db.session.add(player)
        db.session.commit()
        return player.id

def test_initial_auction_state_waiting(client):
    response = client.get('/api/auction/state')
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'WAITING'
    assert data['active_player'] is None

def test_find_player_by_roll(admin_client, test_player, app):
    response = admin_client.post('/api/auction/find-player', json={'roll_number': '301'})
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert data['player']['name'] == 'Virat Kohli Test'

def test_find_invalid_roll_number(admin_client):
    response = admin_client.post('/api/auction/find-player', json={'roll_number': '999999'})
    assert response.status_code == 400
    data = response.get_json()
    assert data['success'] is False

def test_activate_player_preview_state(admin_client, test_player, app):
    response = admin_client.post('/api/auction/activate', json={'player_id': test_player})
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'PLAYER_PREVIEW'

    # Verify state via API
    res = admin_client.get('/api/auction/state')
    state_data = res.get_json()
    assert state_data['status'] == 'PLAYER_PREVIEW'
    assert state_data['active_player']['id'] == test_player
    assert state_data['current_bid'] == 10000.0

def test_start_bidding_and_timer(admin_client, test_player):
    admin_client.post('/api/auction/activate', json={'player_id': test_player})
    response = admin_client.post('/api/auction/start')
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'BIDDING'

    res = admin_client.get('/api/auction/state')
    state_data = res.get_json()
    assert state_data['status'] == 'BIDDING'
    assert state_data['remaining_seconds'] > 0

def test_valid_bidding_flow_and_increments(app, client, admin_client, test_player):
    with app.app_context():
        f1 = Franchise.query.filter_by(short_name='F01').first()
        f2 = Franchise.query.filter_by(short_name='F02').first()
        f1_id, f2_id = f1.id, f2.id

    admin_client.post('/api/auction/activate', json={'player_id': test_player})
    admin_client.post('/api/auction/start')

    with app.app_context():
        # 1st Bid by Franchise 1 = base_price (₹10,000)
        state = place_bid(f1_id, 10000.0)
        assert state.current_bid == 10000.0
        assert state.highest_bidder_id == f1_id

        # 2nd Bid by Franchise 2 = current_bid + increment (₹10,000 + ₹2,000 = ₹12,000) per Section 44 rules
        state = place_bid(f2_id, 12000.0)
        assert state.current_bid == 12000.0
        assert state.highest_bidder_id == f2_id

def test_bid_validations_rejections(app, test_player):
    with app.app_context():
        f1 = Franchise.query.filter_by(short_name='F01').first()
        f2 = Franchise.query.filter_by(short_name='F02').first()
        f1_id, f2_id = f1.id, f2.id

        state = AuctionState.query.first()
        state.status = 'WAITING'
        db.session.commit()

        # Cannot bid when WAITING
        with pytest.raises(ValueError, match="not accepting bids"):
            place_bid(f1_id, 10000.0)

        # Activate & Start
        state.status = 'BIDDING'
        state.active_player_id = test_player
        state.current_bid = 10000.0
        state.highest_bidder_id = None
        db.session.commit()

        # Low bid rejection
        with pytest.raises(ValueError, match="Minimum required bid"):
            place_bid(f1_id, 5000.0)

        # Valid First Bid
        place_bid(f1_id, 10000.0)

        # Double-bid rejection (Self-bidding)
        with pytest.raises(ValueError, match="already the highest bidder"):
            place_bid(f1_id, 12000.0)

        # Insufficient purse rejection
        f2_obj = Franchise.query.get(f2_id)
        f2_obj.remaining_purse = 5000.0
        db.session.commit()

        with pytest.raises(ValueError, match="Insufficient purse"):
            place_bid(f2_id, 12000.0)

def test_squad_limit_15_rejection(app, test_player):
    with app.app_context():
        f1 = Franchise.query.filter_by(short_name='F01').first()
        f1.squad_limit = 15
        db.session.commit()

        # Add 15 sold players to f1
        for i in range(15):
            p = Player(roll_number=f"SQ_{i}", name=f"Squad Player {i}", status='SOLD', sold_to=f1.id)
            db.session.add(p)
        db.session.commit()

        state = AuctionState.query.first()
        state.status = 'BIDDING'
        state.active_player_id = test_player
        state.current_bid = 10000.0
        state.highest_bidder_id = None
        db.session.commit()

        with pytest.raises(ValueError, match="Squad limit reached"):
            place_bid(f1.id, 10000.0)

def test_pause_resume_and_extend_timer(admin_client, test_player):
    admin_client.post('/api/auction/activate', json={'player_id': test_player})
    admin_client.post('/api/auction/start')

    # Pause
    res = admin_client.post('/api/auction/pause')
    assert res.status_code == 200
    assert res.get_json()['status'] == 'PAUSED'

    # Resume
    res = admin_client.post('/api/auction/resume')
    assert res.status_code == 200
    assert res.get_json()['status'] == 'BIDDING'

    # Extend (+10s)
    res = admin_client.post('/api/auction/extend', json={'seconds': 10})
    assert res.status_code == 200
    assert res.get_json()['success'] is True

def test_atomic_sold_transaction(app, admin_client, test_player):
    admin_client.post('/api/auction/activate', json={'player_id': test_player})
    admin_client.post('/api/auction/start')

    with app.app_context():
        f1 = Franchise.query.filter_by(short_name='F01').first()
        initial_purse = f1.remaining_purse
        place_bid(f1.id, 50000.0)
        admin_id = User.query.filter_by(role='ADMIN').first().id

        player, franchise, sold_price = finalize_sold(admin_id)

        assert player.status == 'SOLD'
        assert player.sold_to == f1.id
        assert player.sold_price == 50000.0
        assert franchise.remaining_purse == initial_purse - 50000.0
        assert franchise.squad_count == 1

        # Check Transaction record created
        tx = Transaction.query.filter_by(player_id=player.id).first()
        assert tx is not None
        assert tx.amount == 50000.0
        assert tx.type in ['PURCHASE', 'PLAYER_PURCHASE']

        # Check AuctionState status set to SOLD
        state = AuctionState.query.first()
        assert state.status in ['SOLD', 'WAITING']

def test_unsold_workflow(app, admin_client, test_player):
    admin_client.post('/api/auction/activate', json={'player_id': test_player})
    admin_client.post('/api/auction/start')

    with app.app_context():
        f1 = Franchise.query.filter_by(short_name='F01').first()
        initial_purse = f1.remaining_purse
        admin_id = User.query.filter_by(role='ADMIN').first().id

        player = finalize_unsold(admin_id)

        assert player.status == 'UNSOLD'
        assert f1.remaining_purse == initial_purse  # No purse deduction

        state = AuctionState.query.first()
        assert state.status in ['UNSOLD', 'WAITING']

def test_public_api_no_future_player_leakage(client):
    response = client.get('/api/auction/state')
    assert response.status_code == 200
    data = response.get_json()
    assert 'player_queue' not in data
    assert 'next_player' not in data
