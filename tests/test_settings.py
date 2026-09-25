import pytest
from app import create_app
from app.extensions import db
from app.models import SystemSettings
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

def test_view_settings_page(admin_client):
    response = admin_client.get('/admin/settings')
    assert response.status_code == 200
    assert b'Global Auction Defaults' in response.data or b'System Configuration' in response.data or b'Settings' in response.data

def test_save_settings(admin_client, app):
    response = admin_client.post('/admin/settings', data={
        'event_name': 'SPL 2026',
        'event_subtitle': 'Sphoorthy Premier League Season 5',
        'starting_purse': '750000',
        'squad_limit': '18',
        'base_price': '15000',
        'timer_seconds': '45',
        'theme_default': 'dark'
    }, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        assert SystemSettings.get_setting('event_name') == 'SPL 2026'
        assert SystemSettings.get_setting('starting_purse') == '750000'
        assert SystemSettings.get_setting('timer_seconds') == '45'
