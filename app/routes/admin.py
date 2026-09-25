import os
import csv
import io
import re
from datetime import datetime
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, Response, make_response
from flask_login import login_required, current_user
from app.extensions import db
from app.models import User, Player, PlayerRole, PlayerCategory, PlayerStatus, Franchise, AuctionState, AuctionStatus, SystemSettings, AuditLog, Transaction, Bid, Fixture, FixtureStage, FixtureStatus
from app.utils.decorators import admin_required
from app.services.csv_service import parse_and_import_players_csv
from app.services.audit_service import log_audit
from app.services.auction_service import validate_squads_integrity, confirm_and_lock_squads, unlock_squads_override
from app.services.fixture_service import generate_fixtures, validate_fixtures, publish_fixtures, unpublish_fixtures
from app.services.backup_service import create_database_backup, list_backups, restore_database_backup
from app.services.health_service import check_system_health, run_deep_auction_check

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']

@admin_bp.route('')
@admin_bp.route('/')
@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    auction_state = AuctionState.query.first()
    auction_status = auction_state.status if auction_state else AuctionStatus.WAITING
    active_player = Player.query.get(auction_state.active_player_id) if auction_state and auction_state.active_player_id else None
    highest_bidder = Franchise.query.get(auction_state.highest_bidder_id) if auction_state and auction_state.highest_bidder_id else None

    total_players = Player.query.count()
    available_players = Player.query.filter_by(status=PlayerStatus.AVAILABLE).count()
    sold_players = Player.query.filter_by(status=PlayerStatus.SOLD).count()
    unsold_players = Player.query.filter_by(status=PlayerStatus.UNSOLD).count()

    all_franchises = Franchise.query.order_by(Franchise.id.asc()).all()
    active_franchises = [f for f in all_franchises if f.is_active]

    total_capacity = sum(f.squad_limit for f in active_franchises) if active_franchises else 90
    total_purse = sum(f.starting_purse for f in active_franchises) if active_franchises else 3000000.0

    recent_audit_events = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(8).all()

    return render_template(
        'admin/dashboard.html',
        auction_status=auction_status,
        auction_state=auction_state,
        active_player=active_player,
        highest_bidder=highest_bidder,
        total_players=total_players,
        available_players=available_players,
        sold_players=sold_players,
        unsold_players=unsold_players,
        total_franchises=len(all_franchises),
        active_franchises_count=len(active_franchises),
        total_capacity=total_capacity,
        total_purse=total_purse,
        all_franchises=all_franchises,
        recent_audit_events=recent_audit_events
    )

# ==================== PLAYER MANAGEMENT ====================

@admin_bp.route('/players', methods=['GET'])
@login_required
@admin_required
def players():
    search = request.args.get('search', '').strip()
    role_filter = request.args.get('role', '').strip()
    category_filter = request.args.get('category', '').strip()
    status_filter = request.args.get('status', '').strip()

    query = Player.query

    if search:
        query = query.filter(
            (Player.name.ilike(f'%{search}%')) |
            (Player.roll_number.ilike(f'%{search}%')) |
            (Player.branch.ilike(f'%{search}%'))
        )
    if role_filter:
        query = query.filter_by(role=role_filter)
    if category_filter:
        query = query.filter_by(category=category_filter)
    if status_filter:
        query = query.filter_by(status=status_filter)

    player_list = query.order_by(Player.id.desc()).all()

    return render_template(
        'admin/players.html',
        players=player_list,
        roles=PlayerRole.CHOICES,
        categories=PlayerCategory.CHOICES,
        statuses=PlayerStatus.CHOICES,
        search=search,
        selected_role=role_filter,
        selected_category=category_filter,
        selected_status=status_filter
    )

@admin_bp.route('/players/add', methods=['POST'])
@login_required
@admin_required
def add_player():
    roll_number = request.form.get('roll_number', '').strip()
    name = request.form.get('name', '').strip()
    role = request.form.get('role', '').strip().upper()
    branch = request.form.get('branch', '').strip()
    year = request.form.get('year', '').strip()
    experience = request.form.get('experience', '').strip()
    category = request.form.get('category', '').strip().upper()
    base_price_str = request.form.get('base_price', '10000').strip()
    status = request.form.get('status', PlayerStatus.AVAILABLE).strip().upper()

    if not roll_number or not name:
        flash('Roll number and Name are required.', 'danger')
        return redirect(url_for('admin.players'))

    if Player.query.filter_by(roll_number=roll_number).first():
        flash(f'Player with roll number "{roll_number}" already exists.', 'danger')
        return redirect(url_for('admin.players'))

    try:
        base_price = float(base_price_str)
    except ValueError:
        base_price = 10000.0

    photo_filename = 'default_player.png'
    file = request.files.get('photo_file')
    if file and file.filename and allowed_file(file.filename):
        filename = secure_filename(f"{roll_number}_{file.filename}")
        file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
        photo_filename = filename
    elif request.form.get('photo_url'):
        photo_filename = request.form.get('photo_url').strip()

    player = Player(
        roll_number=roll_number,
        name=name,
        photo=photo_filename,
        role=role if role in PlayerRole.CHOICES else PlayerRole.BATSMAN,
        branch=branch,
        year=year,
        experience=experience,
        category=category if category in PlayerCategory.CHOICES else PlayerCategory.NORMAL,
        base_price=base_price,
        status=status if status in PlayerStatus.CHOICES else PlayerStatus.AVAILABLE
    )

    db.session.add(player)
    db.session.commit()

    log_audit(current_user.id, 'ADD_PLAYER', 'Player', player.id, None, player.name)
    flash(f'Player "{name}" added successfully.', 'success')
    return redirect(url_for('admin.players'))

@admin_bp.route('/players/<int:id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_player(id):
    player = Player.query.get_or_404(id)
    old_data = player.to_dict()

    player.roll_number = (request.form.get('roll_number') or player.roll_number or '').strip()
    player.name = (request.form.get('name') or player.name or '').strip()
    player.role = (request.form.get('role') or player.role or '').strip().upper()
    player.branch = (request.form.get('branch') or player.branch or '').strip()
    player.year = (request.form.get('year') or player.year or '').strip()
    player.experience = (request.form.get('experience') or player.experience or '').strip()
    player.category = (request.form.get('category') or player.category or '').strip().upper()
    player.status = (request.form.get('status') or player.status or '').strip().upper()

    try:
        player.base_price = float(request.form.get('base_price', player.base_price))
    except ValueError:
        pass

    file = request.files.get('photo_file')
    if file and file.filename and allowed_file(file.filename):
        filename = secure_filename(f"{player.roll_number}_{file.filename}")
        file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
        player.photo = filename
    elif request.form.get('photo_url'):
        player.photo = request.form.get('photo_url').strip()

    db.session.commit()
    log_audit(current_user.id, 'EDIT_PLAYER', 'Player', player.id, old_data, player.to_dict())
    flash(f'Player "{player.name}" updated successfully.', 'success')
    return redirect(url_for('admin.players'))

@admin_bp.route('/players/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_player(id):
    player = Player.query.get_or_404(id)
    name = player.name
    db.session.delete(player)
    db.session.commit()

    log_audit(current_user.id, 'DELETE_PLAYER', 'Player', id, name, None)
    flash(f'Player "{name}" deleted successfully.', 'info')
    return redirect(url_for('admin.players'))

@admin_bp.route('/players/import-csv', methods=['POST'])
@login_required
@admin_required
def import_csv():
    file = request.files.get('csv_file')
    if not file or not file.filename:
        flash('Please select a valid CSV file.', 'danger')
        return redirect(url_for('admin.players'))

    content = file.read()
    import_result = parse_and_import_players_csv(content)

    log_audit(
        current_user.id, 'IMPORT_PLAYERS_CSV', 'Player', None,
        None, f"Imported: {import_result['imported']}, Skipped: {import_result['skipped']}"
    )

    return render_template(
        'admin/players.html',
        players=Player.query.order_by(Player.id.desc()).all(),
        roles=PlayerRole.CHOICES,
        categories=PlayerCategory.CHOICES,
        statuses=PlayerStatus.CHOICES,
        import_result=import_result
    )

@admin_bp.route('/players/<int:id>/json')
@login_required
@admin_required
def get_player_json(id):
    player = Player.query.get_or_404(id)
    return jsonify(player.to_dict())

# ==================== FRANCHISE MANAGEMENT ====================

@admin_bp.route('/franchises', methods=['GET'])
@login_required
@admin_required
def franchises():
    franchise_list = Franchise.query.order_by(Franchise.id.asc()).all()
    return render_template('admin/franchises.html', franchises=franchise_list)

@admin_bp.route('/franchises/add', methods=['POST'])
@login_required
@admin_required
def add_franchise():
    name = request.form.get('name', '').strip()
    short_name = request.form.get('short_name', '').strip().upper()
    authorized_email = request.form.get('authorized_email', '').strip().lower()
    owner_name = request.form.get('owner_name', '').strip()
    google_auth_enabled = 'google_auth_enabled' in request.form or request.form.get('google_auth_enabled') == 'true'

    if not name or not short_name:
        flash('Franchise name and short name are required.', 'danger')
        return redirect(url_for('admin.franchises'))

    if Franchise.query.filter_by(short_name=short_name).first():
        flash(f'Franchise code "{short_name}" already exists.', 'danger')
        return redirect(url_for('admin.franchises'))

    if authorized_email:
        existing_email = Franchise.query.filter_by(authorized_email=authorized_email).first()
        if existing_email:
            flash('This Google account is already assigned to another franchise.', 'danger')
            return redirect(url_for('admin.franchises'))

    try:
        starting_purse = float(request.form.get('starting_purse', 500000))
        squad_limit = int(request.form.get('squad_limit', 15))
    except ValueError:
        starting_purse = 500000.0
        squad_limit = 15

    logo_filename = 'default_logo.png'
    file = request.files.get('logo_file')
    if file and file.filename and allowed_file(file.filename):
        filename = secure_filename(f"logo_{short_name}_{file.filename}")
        file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
        logo_filename = filename

    franchise = Franchise(
        name=name,
        short_name=short_name,
        authorized_email=authorized_email or None,
        owner_name=owner_name or None,
        google_auth_enabled=google_auth_enabled,
        starting_purse=starting_purse,
        remaining_purse=starting_purse,
        squad_limit=squad_limit,
        logo=logo_filename,
        is_active=True
    )

    db.session.add(franchise)
    db.session.commit()

    log_audit(current_user.id, 'FRANCHISE_CREATED', 'Franchise', franchise.id, None, franchise.name, franchise_id=franchise.id)
    flash(f'Franchise "{name}" created successfully.', 'success')
    return redirect(url_for('admin.franchises'))

@admin_bp.route('/franchises/<int:id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_franchise(id):
    franchise = Franchise.query.get_or_404(id)
    old_name = franchise.name
    old_email = franchise.authorized_email
    old_owner = franchise.owner_name

    new_name = request.form.get('name', franchise.name).strip()
    new_short = request.form.get('short_name', franchise.short_name).strip().upper()
    email_input = request.form.get('authorized_email', '').strip().lower()
    owner_name_input = request.form.get('owner_name', '').strip()

    if email_input:
        existing_email = Franchise.query.filter_by(authorized_email=email_input).first()
        if existing_email and existing_email.id != franchise.id:
            flash('This Google account is already assigned to another franchise.', 'danger')
            return redirect(url_for('admin.franchises'))

    franchise.name = new_name
    franchise.short_name = new_short
    franchise.authorized_email = email_input if email_input else None
    franchise.owner_name = owner_name_input if owner_name_input else None
    franchise.google_auth_enabled = 'google_auth_enabled' in request.form or request.form.get('google_auth_enabled') == 'true'
    franchise.is_active = 'is_active' in request.form or request.form.get('is_active') == 'true'

    try:
        new_starting = float(request.form.get('starting_purse', franchise.starting_purse))
        spent = franchise.spent_purse
        franchise.starting_purse = new_starting
        franchise.remaining_purse = max(0.0, new_starting - spent)
        franchise.squad_limit = int(request.form.get('squad_limit', franchise.squad_limit))
    except ValueError:
        pass

    file = request.files.get('logo_file')
    if file and file.filename and allowed_file(file.filename):
        filename = secure_filename(f"logo_{franchise.short_name}_{file.filename}")
        file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
        franchise.logo = filename
        log_audit(current_user.id, 'FRANCHISE_LOGO_UPLOADED', 'Franchise', franchise.id, None, filename, franchise_id=franchise.id)

    db.session.commit()

    log_audit(
        current_user.id, 'FRANCHISE_UPDATED', 'Franchise', franchise.id,
        f"Name: {old_name}, Email: {old_email}, Owner: {old_owner}",
        f"Name: {franchise.name}, Email: {franchise.authorized_email}, Owner: {franchise.owner_name}",
        franchise_id=franchise.id
    )
    flash(f'Franchise "{franchise.name}" updated successfully.', 'success')
    return redirect(url_for('admin.franchises'))

@admin_bp.route('/franchises/<int:id>/remove-logo', methods=['POST'])
@login_required
@admin_required
def remove_franchise_logo(id):
    franchise = Franchise.query.get_or_404(id)
    old_logo = franchise.logo
    franchise.logo = 'default_logo.png'
    db.session.commit()

    log_audit(current_user.id, 'FRANCHISE_LOGO_REMOVED', 'Franchise', franchise.id, old_logo, 'default_logo.png', franchise_id=franchise.id)
    flash(f'Logo for franchise "{franchise.name}" reset to default.', 'info')
    return redirect(url_for('admin.franchises'))

@admin_bp.route('/franchises/<int:id>/toggle-google', methods=['POST'])
@login_required
@admin_required
def toggle_franchise_google(id):
    franchise = Franchise.query.get_or_404(id)
    franchise.google_auth_enabled = not franchise.google_auth_enabled
    db.session.commit()

    status_str = 'ENABLED' if franchise.google_auth_enabled else 'DISABLED'
    log_audit(current_user.id, 'GOOGLE_AUTH_TOGGLED', 'Franchise', franchise.id, None, status_str, franchise_id=franchise.id)
    flash(f'Google Authentication for "{franchise.name}" set to {status_str}.', 'success')
    return redirect(url_for('admin.franchises'))

@admin_bp.route('/franchises/<int:id>/inspect')
@login_required
@admin_required
def inspect_franchise(id):
    franchise = Franchise.query.get_or_404(id)
    players = Player.query.filter_by(sold_to=franchise.id).all()
    purchases = Transaction.query.filter(Transaction.franchise_id == franchise.id, Transaction.type.in_(['PLAYER_PURCHASE', 'PURCHASE'])).order_by(Transaction.created_at.desc()).all()
    bids = Bid.query.filter_by(franchise_id=franchise.id).order_by(Bid.created_at.desc()).all()

    role_counts = {
        PlayerRole.BATSMAN: sum(1 for p in players if p.role == PlayerRole.BATSMAN),
        PlayerRole.BOWLER: sum(1 for p in players if p.role == PlayerRole.BOWLER),
        PlayerRole.ALL_ROUNDER: sum(1 for p in players if p.role == PlayerRole.ALL_ROUNDER),
        PlayerRole.WICKETKEEPER: sum(1 for p in players if p.role == PlayerRole.WICKETKEEPER)
    }

    return render_template(
        'admin/franchise_inspect.html',
        franchise=franchise,
        players=players,
        purchases=purchases,
        bids=bids,
        role_counts=role_counts
    )

# ==================== ADMIN AUDIT LOG PLATFORM ====================

@admin_bp.route('/audit-logs', methods=['GET'])
@login_required
@admin_required
def audit_logs():
    search = request.args.get('search', '').strip()
    action_filter = request.args.get('action', '').strip()
    status_filter = request.args.get('status', '').strip()
    franchise_filter = request.args.get('franchise_id', '').strip()
    user_filter = request.args.get('user_id', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    query = AuditLog.query

    if search:
        query = query.filter(
            (AuditLog.action.ilike(f'%{search}%')) |
            (AuditLog.old_value.ilike(f'%{search}%')) |
            (AuditLog.new_value.ilike(f'%{search}%')) |
            (AuditLog.ip_address.ilike(f'%{search}%'))
        )

    if action_filter:
        query = query.filter(AuditLog.action == action_filter)

    if status_filter:
        query = query.filter(AuditLog.status == status_filter)

    if franchise_filter and franchise_filter.isdigit():
        query = query.filter(AuditLog.franchise_id == int(franchise_filter))

    if user_filter and user_filter.isdigit():
        query = query.filter(AuditLog.admin_id == int(user_filter))

    if date_from:
        try:
            df = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(AuditLog.created_at >= df)
        except ValueError:
            pass

    if date_to:
        try:
            dt = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            query = query.filter(AuditLog.created_at <= dt)
        except ValueError:
            pass

    logs_list = query.order_by(AuditLog.created_at.desc()).all()

    all_logs = AuditLog.query.all()
    total_events = len(all_logs)

    login_actions = {
        'LOGIN_SUCCESS', 'LOGIN_FAILED', 'GOOGLE_LOGIN_SUCCESS',
        'GOOGLE_LOGIN_FAILED', 'GOOGLE_ACCOUNT_UNAUTHORIZED',
        'ADMIN_LOGIN', 'LOGOUT'
    }
    auction_actions = {
        'BID_PLACED', 'PLAYER_SOLD', 'PLAYER_UNSOLD',
        'SECOND_CHANCE_STARTED', 'SECOND_CHANCE_SOLD', 'SECOND_CHANCE_ENDED'
    }
    security_actions = {
        'LOGIN_FAILED', 'GOOGLE_LOGIN_FAILED', 'GOOGLE_ACCOUNT_UNAUTHORIZED',
        'SETTINGS_CHANGED', 'ADMIN_PASSWORD_CHANGED', 'FRANCHISE_DISABLED',
        'USER_DISABLED', 'SECURITY_ALERT'
    }

    login_events = sum(1 for log in all_logs if log.action in login_actions)
    auction_events = sum(1 for log in all_logs if log.action in auction_actions)
    admin_actions_count = sum(1 for log in all_logs if log.admin_id is not None)
    security_events = sum(1 for log in all_logs if log.action in security_actions or log.status in ['FAILED', 'DENIED'])

    franchises = Franchise.query.order_by(Franchise.name.asc()).all()
    users = User.query.order_by(User.username.asc()).all()

    distinct_actions = db.session.query(AuditLog.action).distinct().all()
    action_options = [a[0] for a in distinct_actions if a[0]]

    return render_template(
        'admin/audit_logs.html',
        logs=logs_list,
        total_events=total_events,
        login_events=login_events,
        auction_events=auction_events,
        admin_actions_count=admin_actions_count,
        security_events=security_events,
        franchises=franchises,
        users=users,
        action_options=action_options,
        search=search,
        selected_action=action_filter,
        selected_status=status_filter,
        selected_franchise=franchise_filter,
        selected_user=user_filter,
        date_from=date_from,
        date_to=date_to
    )

# ==================== SETTINGS MANAGEMENT ====================

@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def settings():
    franchises = Franchise.query.order_by(Franchise.id.asc()).all()

    if request.method == 'POST':
        event_name = request.form.get('event_name', 'SPL').strip()
        event_subtitle = request.form.get('event_subtitle', 'Sphoorthy Premier League').strip()
        starting_purse = request.form.get('starting_purse', '500000').strip()
        squad_limit = request.form.get('squad_limit', '15').strip()
        base_price = request.form.get('base_price', '10000').strip()
        timer_seconds = request.form.get('timer_seconds', '30').strip()
        theme_default = request.form.get('theme_default', 'dark').strip()
        show_price_public = 'true' if 'show_purchase_price_publicly' in request.form or request.form.get('show_purchase_price_publicly') == 'true' else 'false'

        SystemSettings.set_setting('event_name', event_name)
        SystemSettings.set_setting('event_subtitle', event_subtitle)
        SystemSettings.set_setting('starting_purse', starting_purse)
        SystemSettings.set_setting('squad_limit', squad_limit)
        SystemSettings.set_setting('base_price', base_price)
        SystemSettings.set_setting('timer_seconds', timer_seconds)
        SystemSettings.set_setting('theme_default', theme_default)
        SystemSettings.set_setting('SHOW_PURCHASE_PRICE_PUBLICLY', show_price_public)

        # Process Captain & Vice-Captain assignments
        for f in franchises:
            cap_val = request.form.get(f'captain_{f.id}')
            vc_val = request.form.get(f'vice_captain_{f.id}')
            f.captain_id = int(cap_val) if cap_val and cap_val.isdigit() else None
            f.vice_captain_id = int(vc_val) if vc_val and vc_val.isdigit() else None

        db.session.commit()

        log_audit(current_user.id, 'UPDATE_SETTINGS', 'SystemSettings', None, None, f"Event: {event_name}")
        flash('System settings saved successfully.', 'success')
        return redirect(url_for('admin.settings'))

    audit_logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(20).all()

    return render_template(
        'admin/settings.html',
        event_name=SystemSettings.get_setting('event_name', 'SPL'),
        event_subtitle=SystemSettings.get_setting('event_subtitle', 'Sphoorthy Premier League'),
        starting_purse=SystemSettings.get_setting('starting_purse', '500000'),
        squad_limit=SystemSettings.get_setting('squad_limit', '15'),
        base_price=SystemSettings.get_setting('base_price', '10000'),
        timer_seconds=SystemSettings.get_setting('timer_seconds', '30'),
        theme_default=SystemSettings.get_setting('theme_default', 'dark'),
        show_purchase_price_publicly=SystemSettings.get_setting('SHOW_PURCHASE_PRICE_PUBLICLY', 'true'),
        franchises=franchises,
        audit_logs=audit_logs
    )

# ==================== LIVE AUCTION CONTROL ====================

@admin_bp.route('/auction')
@login_required
@admin_required
def auction_control():
    return render_template('admin/auction.html')

# ==================== PHASE 6 MODULES ====================

# 1. UNSOLD PLAYER MANAGEMENT
@admin_bp.route('/unsold', methods=['GET'])
@login_required
@admin_required
def unsold_players():
    search = request.args.get('search', '').strip()
    role_filter = request.args.get('role', '').strip()
    category_filter = request.args.get('category', '').strip()

    query = Player.query.filter(Player.status.in_([PlayerStatus.UNSOLD, PlayerStatus.FINAL_UNSOLD]))

    if search:
        query = query.filter(
            (Player.name.ilike(f'%{search}%')) |
            (Player.roll_number.ilike(f'%{search}%'))
        )
    if role_filter:
        query = query.filter_by(role=role_filter)
    if category_filter:
        query = query.filter_by(category=category_filter)

    unsold_list = query.order_by(Player.roll_number.asc()).all()

    return render_template(
        'admin/unsold.html',
        players=unsold_list,
        roles=PlayerRole.CHOICES,
        categories=PlayerCategory.CHOICES,
        search=search,
        selected_role=role_filter,
        selected_category=category_filter
    )

@admin_bp.route('/unsold/toggle-eligibility/<int:id>', methods=['POST'])
@login_required
@admin_required
def toggle_unsold_eligibility(id):
    player = Player.query.get_or_404(id)
    if player.status not in [PlayerStatus.UNSOLD, PlayerStatus.FINAL_UNSOLD]:
        flash(f"Player {player.name} is not unsold.", 'warning')
        return redirect(url_for('admin.unsold_players'))

    player.is_second_chance_eligible = not player.is_second_chance_eligible
    db.session.commit()

    status_str = "ELIGIBLE for Second Chance" if player.is_second_chance_eligible else "REMOVED from Second Chance"
    log_audit(current_user.id, 'TOGGLE_SECOND_CHANCE_ELIGIBILITY', 'Player', player.id, None, status_str)
    flash(f"Player {player.name} is now {status_str}.", 'success')
    return redirect(url_for('admin.unsold_players'))

@admin_bp.route('/unsold/bulk-eligibility', methods=['POST'])
@login_required
@admin_required
def bulk_unsold_eligibility():
    action = request.form.get('action')
    unsold_players_list = Player.query.filter(Player.status.in_([PlayerStatus.UNSOLD, PlayerStatus.FINAL_UNSOLD])).all()

    count = 0
    if action == 'mark_all_eligible':
        for p in unsold_players_list:
            p.is_second_chance_eligible = True
            count += 1
        flash(f"Marked {count} unsold players as ELIGIBLE for second chance.", 'success')
    elif action == 'remove_all_eligibility':
        for p in unsold_players_list:
            p.is_second_chance_eligible = False
            count += 1
        flash(f"Removed second-chance eligibility from {count} unsold players.", 'info')

    db.session.commit()
    log_audit(current_user.id, 'BULK_SECOND_CHANCE_ELIGIBILITY', 'Player', None, None, f"Action: {action}, Affected: {count}")
    return redirect(url_for('admin.unsold_players'))

# 2. SECOND-CHANCE AUCTION DASHBOARD
@admin_bp.route('/second-chance', methods=['GET'])
@login_required
@admin_required
def second_chance_dashboard():
    total_unsold = Player.query.filter(Player.status.in_([PlayerStatus.UNSOLD, PlayerStatus.FINAL_UNSOLD])).count()
    eligible_unsold = Player.query.filter_by(status=PlayerStatus.UNSOLD, is_second_chance_eligible=True).count()

    # Second chance sold count from transactions/audits
    second_chance_sold = AuditLog.query.filter_by(action='SECOND_CHANCE_PLAYER_SOLD').count()
    is_active = SystemSettings.get_setting('second_chance_active') == 'true'

    return render_template(
        'admin/second_chance.html',
        total_unsold=total_unsold,
        eligible_unsold=eligible_unsold,
        second_chance_sold=second_chance_sold,
        is_active=is_active
    )

# 3. FINAL SQUAD VERIFICATION & LOCKING
@admin_bp.route('/final-squads', methods=['GET'])
@login_required
@admin_required
def final_squads():
    franchises = Franchise.query.order_by(Franchise.id.asc()).all()

    # Build franchise breakdown with details
    squad_data = []
    for f in franchises:
        players = Player.query.filter_by(sold_to=f.id).order_by(Player.name.asc()).all()
        squad_data.append({
            'franchise': f,
            'players': players,
            'spent': f.spent_purse,
            'remaining': f.remaining_purse,
            'count': len(players)
        })

    is_valid, errors = validate_squads_integrity()
    is_locked = SystemSettings.get_setting('squads_locked') == 'true'

    return render_template(
        'admin/final_squads.html',
        squads=squad_data,
        is_valid=is_valid,
        validation_errors=errors,
        is_locked=is_locked
    )

@admin_bp.route('/final-squads/confirm', methods=['POST'])
@login_required
@admin_required
def confirm_squads():
    try:
        confirm_and_lock_squads(current_user.id)
        flash('FINAL SQUADS CONFIRMED AND LOCKED PERMANENTLY! 🏆', 'success')
    except ValueError as e:
        flash(f"Confirmation failed: {str(e)}", 'danger')

    return redirect(url_for('admin.final_squads'))

@admin_bp.route('/final-squads/unlock-override', methods=['POST'])
@login_required
@admin_required
def unlock_squads():
    reason = request.form.get('reason', '').strip()
    try:
        unlock_squads_override(current_user.id, reason)
        flash('Authorized Admin squad unlock override executed.', 'warning')
    except ValueError as e:
        flash(f"Unlock failed: {str(e)}", 'danger')

    return redirect(url_for('admin.final_squads'))

# 4. FIXTURE MANAGEMENT
@admin_bp.route('/fixtures', methods=['GET'])
@login_required
@admin_required
def fixtures_management():
    all_fixtures = Fixture.query.order_by(Fixture.match_number.asc()).all()
    franchises = Franchise.query.filter_by(is_active=True).all()
    is_valid, errors = validate_fixtures()
    is_published = any(f.is_published for f in all_fixtures) if all_fixtures else False

    return render_template(
        'admin/fixtures.html',
        fixtures=all_fixtures,
        franchises=franchises,
        is_valid=is_valid,
        validation_errors=errors,
        is_published=is_published,
        stages=FixtureStage.CHOICES,
        statuses=FixtureStatus.CHOICES
    )

@admin_bp.route('/fixtures/add', methods=['POST'])
@login_required
@admin_required
def add_fixture():
    try:
        match_number = int(request.form.get('match_number'))
        team_a_id = int(request.form.get('team_a_id'))
        team_b_id = int(request.form.get('team_b_id'))
        match_date = request.form.get('match_date', '').strip()
        match_time = request.form.get('match_time', '').strip()
        venue = request.form.get('venue', 'College Ground').strip()
        stage = request.form.get('stage', FixtureStage.LEAGUE).strip()

        if team_a_id == team_b_id:
            flash('Team A and Team B cannot be the same franchise.', 'danger')
            return redirect(url_for('admin.fixtures_management'))

        fixture = Fixture(
            match_number=match_number,
            team_a_id=team_a_id,
            team_b_id=team_b_id,
            match_date=match_date,
            match_time=match_time,
            venue=venue,
            stage=stage,
            is_published=False
        )
        db.session.add(fixture)
        db.session.commit()
        log_audit(current_user.id, 'ADD_FIXTURE', 'Fixture', fixture.id, None, f"Match #{match_number}")
        flash(f"Match #{match_number} added successfully.", 'success')
    except (ValueError, TypeError) as e:
        flash(f"Failed to add fixture: {str(e)}", 'danger')

    return redirect(url_for('admin.fixtures_management'))

@admin_bp.route('/fixtures/<int:id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_fixture(id):
    fixture = Fixture.query.get_or_404(id)
    try:
        fixture.match_number = int(request.form.get('match_number', fixture.match_number))
        fixture.team_a_id = int(request.form.get('team_a_id', fixture.team_a_id))
        fixture.team_b_id = int(request.form.get('team_b_id', fixture.team_b_id))
        fixture.match_date = request.form.get('match_date', fixture.match_date).strip()
        fixture.match_time = request.form.get('match_time', fixture.match_time).strip()
        fixture.venue = request.form.get('venue', fixture.venue).strip()
        fixture.stage = request.form.get('stage', fixture.stage).strip()
        fixture.status = request.form.get('status', fixture.status).strip()

        db.session.commit()
        log_audit(current_user.id, 'FIXTURE_EDITED', 'Fixture', fixture.id, None, f"Updated Match #{fixture.match_number}")
        flash(f"Match #{fixture.match_number} updated.", 'success')
    except (ValueError, TypeError) as e:
        flash(f"Edit failed: {str(e)}", 'danger')

    return redirect(url_for('admin.fixtures_management'))

@admin_bp.route('/fixtures/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_fixture(id):
    fixture = Fixture.query.get_or_404(id)
    num = fixture.match_number
    db.session.delete(fixture)
    db.session.commit()
    log_audit(current_user.id, 'DELETE_FIXTURE', 'Fixture', id, f"Match #{num}", None)
    flash(f"Match #{num} deleted.", 'info')
    return redirect(url_for('admin.fixtures_management'))

@admin_bp.route('/fixtures/generate', methods=['POST'])
@login_required
@admin_required
def generate_draft_fixtures():
    format_type = request.form.get('format_type', 'SINGLE_ROUND_ROBIN')
    venue = request.form.get('venue', 'College Ground').strip()
    try:
        generated = generate_fixtures(format_type, venue, current_user.id)
        flash(f"Generated {len(generated)} draft fixtures using {format_type}. Please review before publishing.", 'success')
    except ValueError as e:
        flash(f"Fixture generation failed: {str(e)}", 'danger')

    return redirect(url_for('admin.fixtures_management'))

@admin_bp.route('/fixtures/publish', methods=['POST'])
@login_required
@admin_required
def publish_all_fixtures():
    try:
        count = publish_fixtures(current_user.id)
        flash(f"Successfully published {count} fixtures to public portal! 📅", 'success')
    except ValueError as e:
        flash(f"Publish failed: {str(e)}", 'danger')

    return redirect(url_for('admin.fixtures_management'))

@admin_bp.route('/fixtures/unpublish', methods=['POST'])
@login_required
@admin_required
def unpublish_all_fixtures():
    try:
        count = unpublish_fixtures(current_user.id)
        flash(f"Unpublished {count} fixtures.", 'info')
    except ValueError as e:
        flash(f"Unpublish failed: {str(e)}", 'danger')

    return redirect(url_for('admin.fixtures_management'))

# 5. FINAL AUCTION SUMMARY & REPORT
@admin_bp.route('/auction-summary', methods=['GET'])
@login_required
@admin_required
def auction_summary():
    total_registered = Player.query.count()
    total_sold = Player.query.filter_by(status=PlayerStatus.SOLD).count()
    total_unsold = Player.query.filter_by(status=PlayerStatus.UNSOLD).count()
    final_unsold = Player.query.filter_by(status=PlayerStatus.FINAL_UNSOLD).count()

    second_chance_sold = AuditLog.query.filter_by(action='SECOND_CHANCE_PLAYER_SOLD').count()

    franchises = Franchise.query.order_by(Franchise.id.asc()).all()
    franchise_summaries = []

    all_prices = []
    for f in franchises:
        players = Player.query.filter_by(sold_to=f.id).all()
        prices = [p.sold_price for p in players if p.sold_price is not None]
        all_prices.extend(prices)

        franchise_summaries.append({
            'franchise': f,
            'squad_count': len(players),
            'spent': f.spent_purse,
            'remaining': f.remaining_purse,
            'highest_purchase': max(prices) if prices else 0.0,
            'lowest_purchase': min(prices) if prices else 0.0
        })

    highest_purchase = max(all_prices) if all_prices else 0.0
    lowest_purchase = min(all_prices) if all_prices else 0.0
    total_money_spent = sum(all_prices)

    return render_template(
        'admin/auction_summary.html',
        total_registered=total_registered,
        total_sold=total_sold,
        total_unsold=total_unsold,
        second_chance_sold=second_chance_sold,
        final_unsold=final_unsold,
        franchise_summaries=franchise_summaries,
        highest_purchase=highest_purchase,
        lowest_purchase=lowest_purchase,
        total_money_spent=total_money_spent
    )

@admin_bp.route('/auction-summary/download', methods=['GET'])
@login_required
@admin_required
def download_auction_report():
    players = Player.query.order_by(Player.roll_number.asc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Roll Number', 'Player Name', 'Role', 'Category', 'Base Price', 'Status', 'Franchise', 'Purchase Price'])

    for p in players:
        franchise_name = p.franchise.name if p.franchise else '---'
        sold_price_str = f"Rs. {p.sold_price:,.0f}" if p.sold_price is not None else 'N/A'
        writer.writerow([
            p.roll_number,
            p.name,
            p.role,
            p.category,
            f"Rs. {p.base_price:,.0f}",
            p.status,
            franchise_name,
            sold_price_str
        ])

    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = 'attachment; filename=SPL_Auction_Report.csv'
    response.headers['Content-type'] = 'text/csv'
    return response

# ==================== PHASE 7 MODULES ====================

# 1. ADMIN SECURITY & PASSWORD CHANGE
@admin_bp.route('/settings/security', methods=['GET', 'POST'])
@login_required
@admin_required
def security_settings():
    is_default_admin = current_user.check_password('SPLAdmin@2026!')

    if request.method == 'POST':
        current_pass = request.form.get('current_password', '')
        new_pass = request.form.get('new_password', '')
        confirm_pass = request.form.get('confirm_password', '')

        if not current_user.check_password(current_pass):
            flash('Current password is incorrect.', 'danger')
            return redirect(url_for('admin.security_settings'))

        if len(new_pass) < 10:
            flash('New password must be at least 10 characters in length.', 'danger')
            return redirect(url_for('admin.security_settings'))

        if not (re.search(r'[A-Z]', new_pass) and re.search(r'[a-z]', new_pass) and re.search(r'[0-9]', new_pass) and re.search(r'[^A-Za-z0-9]', new_pass)):
            flash('New password must contain uppercase, lowercase, number, and special character.', 'danger')
            return redirect(url_for('admin.security_settings'))

        if new_pass != confirm_pass:
            flash('New password and confirmation do not match.', 'danger')
            return redirect(url_for('admin.security_settings'))

        current_user.set_password(new_pass)
        db.session.commit()
        log_audit(current_user.id, 'PASSWORD_CHANGED', 'User', current_user.id, None, 'Admin password changed successfully')
        flash('Admin password updated successfully! Please keep your new credentials secure.', 'success')
        return redirect(url_for('admin.security_settings'))

    return render_template(
        'admin/change_password.html',
        is_default_admin=is_default_admin
    )

# 2. USER & FRANCHISE LOGIN MANAGEMENT
@admin_bp.route('/users', methods=['GET'])
@login_required
@admin_required
def users_management():
    users = User.query.order_by(User.id.asc()).all()
    franchises = Franchise.query.filter_by(is_active=True).all()
    return render_template(
        'admin/users.html',
        users=users,
        franchises=franchises
    )

@admin_bp.route('/users/create', methods=['POST'])
@login_required
@admin_required
def create_user():
    username = request.form.get('username', '').strip().lower()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    role = request.form.get('role', 'FRANCHISE').strip().upper()
    franchise_id = request.form.get('franchise_id')

    if not username or not password:
        flash('Username and password are required.', 'danger')
        return redirect(url_for('admin.users_management'))

    if User.query.filter_by(username=username).first():
        flash(f"Username '{username}' already exists.", 'danger')
        return redirect(url_for('admin.users_management'))

    f_id = int(franchise_id) if franchise_id and franchise_id.isdigit() else None
    display_name = username.title()
    if f_id:
        f_obj = Franchise.query.get(f_id)
        if f_obj:
            display_name = f_obj.name

    user = User(
        username=username,
        email=email or f"{username}@spl.com",
        display_name=display_name,
        role=role,
        franchise_id=f_id,
        is_active=True
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    log_audit(current_user.id, 'USER_CREATED', 'User', user.id, None, f"User {username} created ({role})")
    flash(f"User account '{username}' created successfully.", 'success')
    return redirect(url_for('admin.users_management'))

@admin_bp.route('/users/<int:id>/reset-password', methods=['POST'])
@login_required
@admin_required
def reset_user_password(id):
    user = User.query.get_or_404(id)
    new_password = request.form.get('new_password', '')
    if not new_password or len(new_password) < 6:
        flash('Password must be at least 6 characters long.', 'danger')
        return redirect(url_for('admin.users_management'))

    user.set_password(new_password)
    db.session.commit()
    log_audit(current_user.id, 'USER_PASSWORD_RESET', 'User', user.id, None, f"Password reset for {user.username}")
    flash(f"Password for user '{user.username}' reset successfully.", 'success')
    return redirect(url_for('admin.users_management'))

@admin_bp.route('/users/<int:id>/toggle-status', methods=['POST'])
@login_required
@admin_required
def toggle_user_status(id):
    user = User.query.get_or_404(id)
    if user.id == current_user.id:
        flash('You cannot deactivate your own logged-in admin account.', 'danger')
        return redirect(url_for('admin.users_management'))

    user.is_active = not user.is_active
    db.session.commit()

    action_str = 'USER_ENABLED' if user.is_active else 'USER_DISABLED'
    log_audit(current_user.id, action_str, 'User', user.id, None, f"Status set to {user.is_active}")
    flash(f"User '{user.username}' status set to {'ACTIVE' if user.is_active else 'INACTIVE'}.", 'info')
    return redirect(url_for('admin.users_management'))

# 3. AUCTION & PURSE INTEGRITY AUDIT
@admin_bp.route('/system/auction-check', methods=['GET'])
@login_required
@admin_required
def auction_integrity_audit():
    is_passed, report = run_deep_auction_check()
    return render_template(
        'admin/auction_check.html',
        is_passed=is_passed,
        report=report
    )

# 4. SYSTEM HEALTH DASHBOARD
@admin_bp.route('/system/health', methods=['GET'])
@login_required
@admin_required
def system_health_dashboard():
    health = check_system_health()
    auction_state = AuctionState.query.first()
    status = auction_state.status if auction_state else AuctionStatus.WAITING

    return render_template(
        'admin/system_health.html',
        health=health,
        auction_status=status
    )

# 5. EVENT CONTROL PANEL
@admin_bp.route('/event-control', methods=['GET'])
@login_required
@admin_required
def event_control_panel():
    state = AuctionState.query.first()
    player = Player.query.get(state.active_player_id) if state and state.active_player_id else None
    highest_bidder = Franchise.query.get(state.highest_bidder_id) if state and state.highest_bidder_id else None

    total_sold = Player.query.filter_by(status=PlayerStatus.SOLD).count()
    total_unsold = Player.query.filter_by(status=PlayerStatus.UNSOLD).count()
    is_sc = SystemSettings.get_setting('second_chance_active') == 'true'
    is_locked = SystemSettings.get_setting('squads_locked') == 'true'
    fixtures_published = Fixture.query.filter_by(is_published=True).count() > 0

    return render_template(
        'admin/event_control.html',
        state=state,
        player=player,
        highest_bidder=highest_bidder,
        total_sold=total_sold,
        total_unsold=total_unsold,
        is_sc=is_sc,
        is_locked=is_locked,
        fixtures_published=fixtures_published
    )

# 6. DATABASE BACKUP & RESTORE
@admin_bp.route('/backup', methods=['GET'])
@login_required
@admin_required
def backup_dashboard():
    backups = list_backups()
    return render_template(
        'admin/backup.html',
        backups=backups
    )

@admin_bp.route('/backup/create', methods=['POST'])
@login_required
@admin_required
def trigger_backup():
    try:
        filename = create_database_backup(current_user.id)
        flash(f"Database backup snapshot '{filename}' created successfully in instance/backups directory.", 'success')
    except Exception as e:
        flash(f"Backup failed: {str(e)}", 'danger')

    return redirect(url_for('admin.backup_dashboard'))

@admin_bp.route('/backup/restore', methods=['POST'])
@login_required
@admin_required
def trigger_restore():
    filename = request.form.get('filename')
    reason = request.form.get('reason', '').strip()
    try:
        restore_database_backup(filename, current_user.id, reason)
        flash(f"Database restored successfully from '{filename}'.", 'warning')
    except Exception as e:
        flash(f"Restore failed: {str(e)}", 'danger')

    return redirect(url_for('admin.backup_dashboard'))


