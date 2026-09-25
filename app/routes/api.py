from flask import Blueprint, jsonify, request, current_app
from flask_login import current_user, login_required
from app.models import AuctionStatus, Franchise, Player, SystemSettings, Bid, AuditLog
from app.utils.decorators import admin_required, franchise_required
from app.services.auction_service import (
    get_auction_state, find_player_by_roll, activate_player, start_bidding,
    pause_auction, resume_auction, extend_timer, place_bid, finalize_sold, finalize_unsold, reset_to_waiting,
    find_second_chance_player_by_roll, start_second_chance_auction, end_second_chance_auction, get_next_bid_increment
)

api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route('/auction/state', methods=['GET'])
def get_state():
    """
    Role-customized live polling endpoint.
    Returns JSON state for public projector display, franchise dashboards, and admin console.
    Strictly prohibits exposing future players, player queues, or hidden database data.
    """
    state = get_auction_state()
    player = Player.query.get(state.active_player_id) if state.active_player_id else None
    highest_bidder = Franchise.query.get(state.highest_bidder_id) if state.highest_bidder_id else None

    # Version timestamp for polling optimization
    version_ts = int(state.updated_at.timestamp()) if state.updated_at else 0

    # Base Public State
    res = {
        'status': state.status,
        'current_bid': state.current_bid,
        'remaining_seconds': state.remaining_seconds,
        'event_name': SystemSettings.get_setting('event_name', 'SPL'),
        'event_subtitle': SystemSettings.get_setting('event_subtitle', 'Sphoorthy Premier League'),
        'version': version_ts,
        'active_player': player.to_dict() if player else None,
        'highest_bidder': {
            'id': highest_bidder.id,
            'name': highest_bidder.name,
            'short_name': highest_bidder.short_name,
            'logo': highest_bidder.logo
        } if highest_bidder else None
    }

    # Calculate Next Required Bid Amount
    increment = get_next_bid_increment(state.current_bid)
    if not highest_bidder and player:
        next_valid_bid = float(player.base_price or 10000.0)
    else:
        next_valid_bid = state.current_bid + increment
    res['next_valid_bid'] = next_valid_bid

    # Franchise-Specific State Additions
    if current_user.is_authenticated and current_user.is_franchise and current_user.franchise_id:
        franchise = Franchise.query.get(current_user.franchise_id)
        if franchise:
            can_bid = True
            cannot_bid_reason = None

            if state.status != AuctionStatus.BIDDING:
                can_bid = False
                cannot_bid_reason = f"Auction is currently {state.status}"
            elif state.remaining_seconds <= 0:
                can_bid = False
                cannot_bid_reason = "Time Expired"
            elif not franchise.is_active:
                can_bid = False
                cannot_bid_reason = "Franchise Inactive"
            elif franchise.squad_count >= franchise.squad_limit:
                can_bid = False
                cannot_bid_reason = f"Squad Limit Reached ({franchise.squad_count}/{franchise.squad_limit})"
            elif franchise.remaining_purse < next_valid_bid:
                can_bid = False
                cannot_bid_reason = f"Insufficient Purse (Need ₹{next_valid_bid:,.0f})"
            elif state.highest_bidder_id == franchise.id:
                can_bid = False
                cannot_bid_reason = "You are Highest Bidder"

            res['franchise_info'] = {
                'id': franchise.id,
                'name': franchise.name,
                'short_name': franchise.short_name,
                'remaining_purse': franchise.remaining_purse,
                'spent_purse': franchise.spent_purse,
                'squad_count': franchise.squad_count,
                'squad_limit': franchise.squad_limit,
                'can_bid': can_bid,
                'cannot_bid_reason': cannot_bid_reason,
                'is_highest_bidder': (state.highest_bidder_id == franchise.id)
            }

    # Admin-Specific Additions (Recent Bids for active player)
    if current_user.is_authenticated and current_user.is_admin and player:
        recent_bids = Bid.query.filter_by(player_id=player.id).order_by(Bid.created_at.desc()).limit(10).all()
        res['recent_bids'] = [{
            'id': b.id,
            'franchise_name': b.franchise.name if b.franchise else 'Unknown',
            'franchise_short': b.franchise.short_name if b.franchise else '---',
            'amount': b.amount,
            'timestamp': b.created_at.strftime('%H:%M:%S')
        } for b in recent_bids]

    return jsonify(res)

@api_bp.route('/auction/find-player', methods=['POST'])
@login_required
@admin_required
def api_find_player():
    data = request.get_json() or request.form
    roll_number = data.get('roll_number')
    try:
        player = find_player_by_roll(roll_number)
        return jsonify({'success': True, 'player': player.to_dict()})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/activate', methods=['POST'])
@login_required
@admin_required
def api_activate_player():
    data = request.get_json() or request.form
    player_id = data.get('player_id')
    try:
        state = activate_player(player_id, current_user.id)
        return jsonify({'success': True, 'status': state.status})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/start', methods=['POST'])
@login_required
@admin_required
def api_start_bidding():
    try:
        state = start_bidding(current_user.id)
        return jsonify({'success': True, 'status': state.status, 'timer_seconds': state.timer_seconds})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/pause', methods=['POST'])
@login_required
@admin_required
def api_pause_auction():
    try:
        state = pause_auction(current_user.id)
        return jsonify({'success': True, 'status': state.status, 'paused_seconds_left': state.paused_seconds_left})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/resume', methods=['POST'])
@login_required
@admin_required
def api_resume_auction():
    try:
        state = resume_auction(current_user.id)
        return jsonify({'success': True, 'status': state.status, 'remaining_seconds': state.remaining_seconds})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/extend', methods=['POST'])
@login_required
@admin_required
def api_extend_timer():
    data = request.get_json() or request.form
    try:
        seconds = int(data.get('seconds', 10))
        state = extend_timer(seconds, current_user.id)
        return jsonify({'success': True, 'remaining_seconds': state.remaining_seconds})
    except (ValueError, TypeError) as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/bid', methods=['POST'])
@login_required
@franchise_required
def api_place_bid():
    data = request.get_json() or request.form
    try:
        amount = float(data.get('amount'))
        state = place_bid(current_user.franchise_id, amount)
        return jsonify({
            'success': True,
            'current_bid': state.current_bid,
            'highest_bidder_id': state.highest_bidder_id
        })
    except (ValueError, TypeError) as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/sold', methods=['POST'])
@login_required
@admin_required
def api_finalize_sold():
    try:
        player, franchise, sold_price = finalize_sold(current_user.id)
        return jsonify({
            'success': True,
            'message': f"Player {player.name} sold to {franchise.name} for Rs. {sold_price:,.0f}",
            'player_name': player.name,
            'franchise_name': franchise.name,
            'sold_price': sold_price
        })
    except (ValueError, RuntimeError) as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/unsold', methods=['POST'])
@login_required
@admin_required
def api_finalize_unsold():
    try:
        player = finalize_unsold(current_user.id)
        return jsonify({
            'success': True,
            'message': f"Player {player.name} marked UNSOLD.",
            'player_name': player.name
        })
    except (ValueError, RuntimeError) as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/reset', methods=['POST'])
@login_required
@admin_required
def api_reset_waiting():
    try:
        state = reset_to_waiting(current_user.id)
        return jsonify({'success': True, 'status': state.status})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/second-chance/find-player', methods=['POST'])
@login_required
@admin_required
def api_find_second_chance_player():
    data = request.get_json() or request.form
    roll_number = data.get('roll_number')
    try:
        player = find_second_chance_player_by_roll(roll_number)
        return jsonify({'success': True, 'player': player.to_dict()})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/second-chance/start', methods=['POST'])
@login_required
@admin_required
def api_start_second_chance():
    try:
        state = start_second_chance_auction(current_user.id)
        return jsonify({'success': True, 'status': state.status})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/second-chance/end', methods=['POST'])
@login_required
@admin_required
def api_end_second_chance():
    try:
        state = end_second_chance_auction(current_user.id)
        return jsonify({'success': True, 'status': state.status})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/events', methods=['GET'])
@login_required
@admin_required
def api_get_audit_events():
    """Return recent auction audit events stream for Admin event monitor."""
    events = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(15).all()
    return jsonify({
        'events': [{
            'id': e.id,
            'time': e.created_at.strftime('%H:%M:%S'),
            'action': e.action,
            'details': e.new_value or e.old_value or ''
        } for e in events]
    })

