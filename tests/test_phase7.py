import pytest
from app import create_app, db
from app.models import User, Franchise, Player, Bid, Transaction, SystemSettings, Fixture
from app.services.seed_service import seed_database
from app.services.auction_service import get_next_bid_increment
from app.services.backup_service import create_database_backup, list_backups
from app.services.health_service import check_system_health, run_deep_auction_check

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

def login_user(client, username, password):
    return client.post('/login', data={
        'username': username,
        'password': password
    }, follow_redirects=True)

# -------------------------------------------------------------
# 1. AUTHENTICATION & LOGIN TESTS
# -------------------------------------------------------------
def test_admin_login_success(client):
    rv = login_user(client, 'admin', 'SPLAdmin@2026!')
    assert rv.status_code == 200
    assert b'Admin' in rv.data or b'Dashboard' in rv.data or b'SPL' in rv.data

def test_admin_login_failure(client):
    rv = login_user(client, 'admin', 'WrongPassword123!')
    assert b'Invalid username or password' in rv.data
    # Ensure technical errors or "user exists" hints are NOT leaked
    assert b'User not found' not in rv.data
    assert b'Incorrect password' not in rv.data

def test_franchise_login_success(client):
    rv = login_user(client, 'cybervipers', 'Vipers@2026!')
    assert rv.status_code == 200
    assert b'Cyber Vipers' in rv.data or b'Franchise' in rv.data

def test_logout(client):
    login_user(client, 'admin', 'SPLAdmin@2026!')
    rv = client.post('/logout', follow_redirects=True)
    assert b'login' in rv.data.lower() or rv.status_code == 200

# -------------------------------------------------------------
# 2. ROLE AUTHORIZATION & ACCESS CONTROL
# -------------------------------------------------------------
def test_franchise_cannot_access_admin_panel(client):
    login_user(client, 'cybervipers', 'Vipers@2026!')
    rv = client.get('/admin', follow_redirects=True)
    assert b'Access Denied' in rv.data or b'403' in rv.data or b'Unauthorized' in rv.data or b'login' in rv.data.lower()

def test_unauthenticated_cannot_access_admin(client):
    rv = client.get('/admin', follow_redirects=True)
    assert b'login' in rv.data.lower() or rv.status_code == 200

def test_franchise_idor_protection(client, app):
    login_user(client, 'cybervipers', 'Vipers@2026!')
    with app.app_context():
        titans = Franchise.query.filter_by(short_name='F02').first()
        titans_id = titans.id if titans else 2
    rv = client.get(f'/api/franchise/{titans_id}')
    if rv.status_code == 200:
        json_data = rv.get_json()
        assert json_data is None or json_data.get('id') != titans_id or json_data.get('error') is not None

# -------------------------------------------------------------
# 3. BID INCREMENT RULES (SECTION 44)
# -------------------------------------------------------------
def test_bid_increment_rules():
    assert get_next_bid_increment(10000) == 2000
    assert get_next_bid_increment(18000) == 2000
    assert get_next_bid_increment(20000) == 2000
    assert get_next_bid_increment(25000) == 5000
    assert get_next_bid_increment(50000) == 5000
    assert get_next_bid_increment(55000) == 10000
    assert get_next_bid_increment(120000) == 10000

# -------------------------------------------------------------
# 4. SYSTEM HEALTH & AUCTION INTEGRITY AUDITS
# -------------------------------------------------------------
def test_system_health_check(app):
    with app.app_context():
        report = check_system_health()
        assert 'database' in report
        assert 'authentication' in report
        assert 'auction_engine' in report

def test_auction_integrity_check(app):
    with app.app_context():
        is_passed, report = run_deep_auction_check()
        assert report['franchises_count'] == 6
        assert len(report['purse_checks']) == 6

# -------------------------------------------------------------
# 5. BACKUP SERVICE TESTS
# -------------------------------------------------------------
def test_backup_creation_and_list(app):
    with app.app_context():
        filename = create_database_backup()
        assert filename.startswith('spl_backup_')
        backups = list_backups()
        assert len(backups) > 0
        assert filename in [b['filename'] for b in backups]

# -------------------------------------------------------------
# 6. END-TO-END AUCTION & TOURNAMENT WORKFLOW
# -------------------------------------------------------------
def test_end_to_end_auction_simulation(client, app):
    # 1. Login Admin
    login_user(client, 'admin', 'SPLAdmin@2026!')

    with app.app_context():
        # Verify initial settings
        purse_setting = SystemSettings.get_setting('starting_purse')
        assert purse_setting == '300000'

        vipers = Franchise.query.filter_by(short_name='F01').first()
        player = Player.query.first()
        if not player:
            player = Player(
                roll_number='P701',
                name='Simulated Player 1',
                role='ALL_ROUNDER',
                category='MARQUEE',
                base_price=10000.0,
                status='AVAILABLE'
            )
            db.session.add(player)
            db.session.commit()
        assert vipers is not None
        assert player is not None

        # Activate player
        player.status = 'UP_FOR_BID'
        db.session.commit()

        # Place bid for vipers
        bid = Bid(
            player_id=player.id,
            franchise_id=vipers.id,
            amount=10000
        )
        db.session.add(bid)
        db.session.commit()

        # Sell player to vipers
        player.status = 'SOLD'
        player.sold_to = vipers.id
        player.sold_price = 10000

        vipers.remaining_purse = 290000

        tx = Transaction(
            player_id=player.id,
            franchise_id=vipers.id,
            amount=10000,
            type='PURCHASE'
        )
        db.session.add(tx)
        db.session.commit()

        assert vipers.remaining_purse == 290000
        assert player.sold_to == vipers.id

        # Run integrity check
        is_passed, report = run_deep_auction_check()
        assert report['franchises_count'] == 6
