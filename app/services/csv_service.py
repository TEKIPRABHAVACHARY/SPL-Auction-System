import csv
import io
from app.extensions import db
from app.models import Player, PlayerRole, PlayerCategory, PlayerStatus

REQUIRED_COLUMNS = ['roll_number', 'name', 'photo', 'role', 'branch', 'year', 'experience', 'category', 'base_price']

def parse_and_import_players_csv(csv_content):
    """
    Parses and validates CSV text content.
    Returns summary dict:
    {
        'imported': int,
        'skipped': int,
        'duplicates': int,
        'errors': list of error dicts
    }
    """
    result = {
        'imported': 0,
        'skipped': 0,
        'duplicates': 0,
        'errors': []
    }

    if isinstance(csv_content, bytes):
        csv_content = csv_content.decode('utf-8-sig', errors='replace')

    stream = io.StringIO(csv_content)
    reader = csv.DictReader(stream)

    if not reader.fieldnames:
        result['errors'].append({'row': 0, 'message': 'CSV file is empty or unreadable.'})
        return result

    # Normalize header names (lowercase, strip whitespace)
    normalized_headers = [h.strip().lower() for h in reader.fieldnames if h]
    
    missing_headers = [col for col in REQUIRED_COLUMNS if col not in normalized_headers]
    if missing_headers:
        result['errors'].append({
            'row': 0,
            'message': f"Missing required column headers: {', '.join(missing_headers)}"
        })
        return result

    existing_roll_numbers = {p.roll_number.lower() for p in Player.query.all()}
    batch_roll_numbers = set()

    row_index = 1
    players_to_add = []

    for raw_row in reader:
        row_index += 1
        # Normalize keys in raw_row
        row = {k.strip().lower(): (v.strip() if v else '') for k, v in raw_row.items() if k}

        roll_number = row.get('roll_number', '').strip()
        name = row.get('name', '').strip()
        photo = row.get('photo', '').strip()
        role = row.get('role', '').strip().upper()
        branch = row.get('branch', '').strip()
        year = row.get('year', '').strip()
        experience = row.get('experience', '').strip()
        category = row.get('category', '').strip().upper()
        base_price_str = row.get('base_price', '').strip()

        # Row Validations
        if not roll_number:
            result['skipped'] += 1
            result['errors'].append({'row': row_index, 'message': 'Missing required field: roll_number'})
            continue

        if not name:
            result['skipped'] += 1
            result['errors'].append({'row': row_index, 'message': f"Row {row_index} ({roll_number}): Missing required field: name"})
            continue

        # Duplicate check in DB or batch
        if roll_number.lower() in existing_roll_numbers or roll_number.lower() in batch_roll_numbers:
            result['duplicates'] += 1
            result['skipped'] += 1
            result['errors'].append({'row': row_index, 'message': f"Row {row_index}: Duplicate roll number '{roll_number}'"})
            continue

        # Role validation
        if role not in PlayerRole.CHOICES:
            result['skipped'] += 1
            result['errors'].append({
                'row': row_index,
                'message': f"Row {row_index} ({roll_number}): Invalid role '{role}'. Must be one of {PlayerRole.CHOICES}"
            })
            continue

        # Category validation
        if category not in PlayerCategory.CHOICES:
            result['skipped'] += 1
            result['errors'].append({
                'row': row_index,
                'message': f"Row {row_index} ({roll_number}): Invalid category '{category}'. Must be one of {PlayerCategory.CHOICES}"
            })
            continue

        # Base price validation
        try:
            base_price = float(base_price_str)
            if base_price < 0:
                raise ValueError()
        except ValueError:
            result['skipped'] += 1
            result['errors'].append({
                'row': row_index,
                'message': f"Row {row_index} ({roll_number}): Invalid base_price '{base_price_str}'. Must be a positive number."
            })
            continue

        player = Player(
            roll_number=roll_number,
            name=name,
            photo=photo or 'default_player.png',
            role=role,
            branch=branch,
            year=year,
            experience=experience,
            category=category,
            base_price=base_price,
            status=PlayerStatus.AVAILABLE
        )

        players_to_add.append(player)
        batch_roll_numbers.add(roll_number.lower())

    if players_to_add:
        try:
            db.session.add_all(players_to_add)
            db.session.commit()
            result['imported'] = len(players_to_add)
        except Exception as e:
            db.session.rollback()
            result['errors'].append({'row': 0, 'message': f"Database transaction failed: {str(e)}"})

    return result
