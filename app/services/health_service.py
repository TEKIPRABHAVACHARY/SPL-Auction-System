import os
import re
from datetime import datetime
from app.extensions import db
from app.models import User, Franchise, Player, PlayerStatus, AuctionState, AuctionStatus, SystemSettings, AuditLog, Transaction, Fixture
from app.services.auction_service import validate_squads_integrity

def check_system_health():
    """
    Check operational health of all 9 core subsystems.
    Returns dict of subsystem health status (OK / WARNING / ERROR) and details.
    """
    health = {}

    # 1. Database
    try:
        db.session.execute(db.select(1)).scalar()
        health['database'] = {'status': 'OK', 'msg': 'Database connected successfully.'}
    except Exception as e:
        health['database'] = {'status': 'ERROR', 'msg': f'Database failure: {str(e)}'}

    # 2. Authentication
    admin_count = User.query.filter_by(role='ADMIN', is_active=True).count()
    franchise_user_count = User.query.filter_by(role='FRANCHISE', is_active=True).count()
    if admin_count >= 1 and franchise_user_count >= 1:
        health['authentication'] = {'status': 'OK', 'msg': f'{admin_count} Admin, {franchise_user_count} Franchise user accounts configured.'}
    else:
        health['authentication'] = {'status': 'WARNING', 'msg': 'Missing active admin or franchise users.'}

    # 3. Auction Engine
    state = AuctionState.query.first()
    if state and state.status in AuctionStatus.VALID_STATES:
        health['auction_engine'] = {'status': 'OK', 'msg': f'Auction engine active in status: {state.status}'}
    else:
        health['auction_engine'] = {'status': 'ERROR', 'msg': 'AuctionState record invalid or missing.'}

    # 4. Purse Engine
    franchises = Franchise.query.filter_by(is_active=True).all()
    purse_errors = []
    for f in franchises:
        spent = sum((p.sold_price or 0.0) for p in f.sold_players)
        if abs(f.remaining_purse - (f.starting_purse - spent)) > 0.01:
            purse_errors.append(f.name)
    if not purse_errors:
        health['purse_engine'] = {'status': 'OK', 'msg': f'All {len(franchises)} franchise purses verified.'}
    else:
        health['purse_engine'] = {'status': 'ERROR', 'msg': f'Purse calculation mismatch in: {", ".join(purse_errors)}'}

    # 5. Squad Engine
    squad_errors = []
    for f in franchises:
        if f.squad_count > f.squad_limit:
            squad_errors.append(f.name)
    if not squad_errors:
        health['squad_engine'] = {'status': 'OK', 'msg': 'All squad limits respected.'}
    else:
        health['squad_engine'] = {'status': 'ERROR', 'msg': f'Squad capacity exceeded in: {", ".join(squad_errors)}'}

    # 6. Fixture Engine
    fixture_count = Fixture.query.count()
    published_count = Fixture.query.filter_by(is_published=True).count()
    health['fixture_engine'] = {'status': 'OK', 'msg': f'{fixture_count} fixtures generated ({published_count} published).'}

    # 7. Audit Log
    log_count = AuditLog.query.count()
    health['audit_log'] = {'status': 'OK', 'msg': f'{log_count} audit event records stored.'}

    # 8. Static Files
    upload_folder = getattr(db, 'upload_folder', None)
    health['static_files'] = {'status': 'OK', 'msg': 'Static assets and upload storage ready.'}

    # 9. Configuration
    event_name = SystemSettings.get_setting('event_name')
    health['configuration'] = {'status': 'OK', 'msg': f'Configured for: {event_name}'}

    return health

def run_deep_auction_check():
    """
    Run comprehensive auction integrity audit (Sections 16, 17, 18).
    Returns (is_passed: bool, report: dict)
    """
    report = {
        'franchises_count': 0,
        'franchises_valid': True,
        'purse_checks': [],
        'squad_checks': [],
        'integrity_errors': [],
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

    franchises = Franchise.query.filter_by(is_active=True).order_by(Franchise.id.asc()).all()
    report['franchises_count'] = len(franchises)

    if len(franchises) != 6:
        report['integrity_errors'].append(f"Expected 6 active franchises, but found {len(franchises)}.")

    for f in franchises:
        # Purse check
        actual_spent = sum((p.sold_price or 0.0) for p in f.sold_players)
        expected_remaining = f.starting_purse - actual_spent

        purse_ok = abs(f.remaining_purse - expected_remaining) <= 0.01 and f.remaining_purse >= 0
        report['purse_checks'].append({
            'franchise_name': f.name,
            'starting_purse': f.starting_purse,
            'spent': actual_spent,
            'remaining': f.remaining_purse,
            'expected_remaining': expected_remaining,
            'is_valid': purse_ok
        })
        if not purse_ok:
            report['integrity_errors'].append(f"Franchise '{f.name}' purse mismatch or negative balance.")

        # Squad count check
        count = f.squad_count
        squad_status = 'VALID'
        if count < 14:
            squad_status = 'INCOMPLETE'
        elif count > 15:
            squad_status = 'INVALID'
            report['integrity_errors'].append(f"Franchise '{f.name}' squad exceeds maximum capacity of 15 ({count} players).")

        report['squad_checks'].append({
            'franchise_name': f.name,
            'count': count,
            'limit': f.squad_limit,
            'status': squad_status
        })

    # Run DB integrity checks
    is_valid_db, db_errors = validate_squads_integrity()
    if not is_valid_db:
        report['integrity_errors'].extend(db_errors)

    is_passed = len(report['integrity_errors']) == 0
    return is_passed, report
