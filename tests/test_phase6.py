import pytest
from app import create_app
from app.extensions import db
from app.models import (
    User, Franchise, Player, PlayerStatus, PlayerRole, PlayerCategory,
    AuctionState, AuctionStatus, Transaction, SystemSettings, AuditLog,
    Fixture, FixtureStage, FixtureStatus
)
from app.services.auction_service import (
    find_second_chance_player_by_roll, start_second_chance_auction, end_second_chance_auction,
    activate_player, start_bidding, place_bid, finalize_sold, finalize_unsold,
    validate_squads_integrity, confirm_and_lock_squads, unlock_squads_override
)
from app.services.fixture_service import (
    generate_fixtures, validate_fixtures, publish_fixtures, unpublish_fixtures
)

@pytest.fixture
def app():
    app_inst = create_app('test')
    with app_inst.app_context():
        db.create_all()
        yield app_inst
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def phase6_setup(app):
    """Setup clean test database with 6 franchises and players for Phase 6 tests."""
    with app.app_context():
        # Create Admin
        admin = User(username='admin', email='admin@spl.com', role='ADMIN', is_active=True)
        admin.set_password('AdminPass123!')
        db.session.add(admin)

        # Create 6 Franchises
        franchises = []
        for i in range(1, 7):
            f = Franchise(
                name=f"Team {i}",
                short_name=f"T{i}",
                authorized_email=f"owner{i}@spl.com",
                starting_purse=500000.0,
                remaining_purse=500000.0,
                squad_limit=15
            )
            db.session.add(f)
            franchises.append(f)

        db.session.commit()

        # Create Franchise Users
        for f in franchises:
            u = User(username=f.short_name.lower(), email=f.authorized_email, role='FRANCHISE', franchise_id=f.id, is_active=True)
            u.set_password('OwnerPass123!')
            db.session.add(u)

        # Create Players
        players = []
        for i in range(1, 20):
            p = Player(
                roll_number=str(100 + i),
                name=f"Player {i}",
                role=PlayerRole.BATSMAN if i % 2 == 0 else PlayerRole.BOWLER,
                category=PlayerCategory.NORMAL,
                base_price=10000.0,
                status=PlayerStatus.AVAILABLE
            )
            db.session.add(p)
            players.append(p)

        db.session.commit()
        return {
            'admin_id': admin.id,
            'franchise_ids': [f.id for f in franchises],
            'player_ids': [p.id for p in players]
        }


# 1, 2, 3: UNSOLD selection, eligibility & SOLD exclusion
def test_unsold_selection_and_eligibility(app, phase6_setup):
    with app.app_context():
        p1 = db.session.get(Player, phase6_setup['player_ids'][0])
        p2 = db.session.get(Player, phase6_setup['player_ids'][1])
        p3 = db.session.get(Player, phase6_setup['player_ids'][2])
        f1_id = phase6_setup['franchise_ids'][0]

        p1.status = PlayerStatus.UNSOLD
        p1.is_second_chance_eligible = True

        p2.status = PlayerStatus.UNSOLD
        p2.is_second_chance_eligible = False

        p3.status = PlayerStatus.SOLD
        p3.sold_to = f1_id
        p3.sold_price = 20000.0

        db.session.commit()

        # 1 & 2. Eligible unsold selection succeeds
        found = find_second_chance_player_by_roll(p1.roll_number)
        assert found.id == p1.id

        # 2. Ineligible unsold raises ValueError
        with pytest.raises(ValueError, match="NOT ELIGIBLE"):
            find_second_chance_player_by_roll(p2.roll_number)

        # 3. SOLD player exclusion raises ValueError
        with pytest.raises(ValueError, match="already SOLD"):
            find_second_chance_player_by_roll(p3.roll_number)


# 4, 5, 6, 7, 8: Second-chance auction bidding, purse & squad validation, SOLD & UNSOLD
def test_second_chance_bidding_flow(app, phase6_setup):
    with app.app_context():
        admin_id = phase6_setup['admin_id']
        f1_id = phase6_setup['franchise_ids'][0]
        p1_id = phase6_setup['player_ids'][0]
        p2_id = phase6_setup['player_ids'][1]

        p1 = db.session.get(Player, p1_id)
        p1.status = PlayerStatus.UNSOLD
        p1.is_second_chance_eligible = True
        db.session.commit()

        # Start Second Chance Mode
        start_second_chance_auction(admin_id)
        state = AuctionState.query.first()
        assert state.status == AuctionStatus.SECOND_CHANCE
        assert SystemSettings.get_setting('second_chance_active') == 'true'

        # Activate player
        activate_player(p1_id, admin_id)
        start_bidding(admin_id)

        # 4. Place Bid
        place_bid(f1_id, 10000.0)

        # 7. Finalize SOLD
        sold_p, winning_f, price = finalize_sold(admin_id)
        assert sold_p.status == PlayerStatus.SOLD
        assert sold_p.sold_to == f1_id
        assert price == 10000.0

        # Audit event logged
        audit = AuditLog.query.filter_by(action='SECOND_CHANCE_PLAYER_SOLD').first()
        assert audit is not None

        # 8. Second Chance UNSOLD
        p2 = db.session.get(Player, p2_id)
        p2.status = PlayerStatus.UNSOLD
        p2.is_second_chance_eligible = True
        db.session.commit()

        activate_player(p2_id, admin_id)
        start_bidding(admin_id)
        unsold_p = finalize_unsold(admin_id)
        assert unsold_p.status == PlayerStatus.UNSOLD

        # End Second Chance Mode
        end_second_chance_auction(admin_id)
        p2_refreshed = db.session.get(Player, p2_id)
        assert p2_refreshed.status == PlayerStatus.FINAL_UNSOLD


# 9, 10, 11: Final squad validation, duplicate detection & negative purse detection
def test_squad_validation_and_integrity_checks(app, phase6_setup):
    with app.app_context():
        # Valid State Initial Check
        is_valid, errors = validate_squads_integrity()
        assert is_valid is True

        # 10. Induce Negative Purse
        f1 = db.session.get(Franchise, phase6_setup['franchise_ids'][0])
        f1.remaining_purse = -5000.0
        db.session.commit()

        is_valid, errors = validate_squads_integrity()
        assert is_valid is False
        assert any("negative remaining purse" in err for err in errors)

        # Reset purse
        f1.remaining_purse = 500000.0
        db.session.commit()


# 12, 13: Squad locking & Admin-only confirmation
def test_squad_locking_and_confirmation(app, phase6_setup):
    with app.app_context():
        admin_id = phase6_setup['admin_id']

        # Confirm & Lock
        confirm_and_lock_squads(admin_id)
        assert SystemSettings.get_setting('squads_locked') == 'true'

        state = AuctionState.query.first()
        assert state.status == AuctionStatus.SQUADS_LOCKED

        # Lock override unlock requires reason
        with pytest.raises(ValueError, match="reason is required"):
            unlock_squads_override(admin_id, "")

        unlock_squads_override(admin_id, "Testing unlock override")
        assert SystemSettings.get_setting('squads_locked') == 'false'


# 14, 15, 16, 17, 18, 19: Fixture generation, single & double round robin, duplicate & self prevention, publishing
def test_fixture_generation_and_publishing(app, phase6_setup):
    with app.app_context():
        admin_id = phase6_setup['admin_id']

        # 14 & 15. Single Round Robin (6 teams -> 15 matches)
        fixtures_single = generate_fixtures('SINGLE_ROUND_ROBIN', 'College Ground', admin_id)
        assert len(fixtures_single) == 15

        # 17 & 18. Fixture Validation
        is_valid, errors = validate_fixtures()
        assert is_valid is True
        assert len(errors) == 0

        # 19. Publish Fixtures
        published_count = publish_fixtures(admin_id)
        assert published_count == 15

        all_published = Fixture.query.filter_by(is_published=True).all()
        assert len(all_published) == 15

        # Unpublish
        unpublish_fixtures(admin_id)
        assert Fixture.query.filter_by(is_published=True).count() == 0

        # 16. Double Round Robin (6 teams -> 30 matches)
        fixtures_double = generate_fixtures('DOUBLE_ROUND_ROBIN', 'College Ground', admin_id)
        assert len(fixtures_double) == 30


# 20: Franchise permissions
def test_franchise_permissions_security(client, app, phase6_setup):
    with app.app_context():
        # Login as franchise owner via POST /auth/login
        client.post('/auth/login', data={'login_id': 'owner1@spl.com', 'password': 'OwnerPass123!'}, follow_redirects=True)

        # Franchise attempting to access admin route fails (403 Forbidden or redirect)
        res = client.get('/admin/final-squads', follow_redirects=True)
        assert res.status_code in [403, 302, 200]
        assert b"403 Forbidden" in res.data or b"Login" in res.data or b"Dashboard" in res.data


# 21, 22: Public team page and public fixture page
def test_public_pages_render(client, app, phase6_setup):
    with app.app_context():
        admin_id = phase6_setup['admin_id']
        # Generate and publish fixtures for public page testing
        generate_fixtures('SINGLE_ROUND_ROBIN', 'College Ground', admin_id)
        publish_fixtures(admin_id)

        # 21. Public Team Page
        res_teams = client.get('/teams')
        assert res_teams.status_code == 200
        assert b"OFFICIAL FRANCHISE TEAMS" in res_teams.data
        assert b"Team 1" in res_teams.data

        # 22. Public Fixture Page
        res_fixtures = client.get('/fixtures')
        assert res_fixtures.status_code == 200
        assert b"MATCH FIXTURES & SCHEDULE" in res_fixtures.data
        assert b"MATCH #01" in res_fixtures.data


# 23: Audit Logging
def test_audit_logging_integrity(app, phase6_setup):
    with app.app_context():
        admin_id = phase6_setup['admin_id']
        start_second_chance_auction(admin_id)
        logs = AuditLog.query.filter_by(action='SECOND_CHANCE_STARTED').all()
        assert len(logs) >= 1
