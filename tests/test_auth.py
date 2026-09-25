import pytest
from app import create_app
from app.extensions import db
from app.models import User, Franchise, AuctionState, AuctionStatus
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

def test_admin_login(client):
    response = client.post('/login', data={
        'username': 'admin',
        'password': 'SPLAdmin@2026!'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Admin' in response.data or b'Dashboard' in response.data or b'SPL' in response.data

def test_franchise_password_login(client):
    response = client.post('/login', data={
        'username': 'cybervipers',
        'password': 'Vipers@2026!'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Cyber Vipers' in response.data or b'Franchise' in response.data

def test_invalid_credentials_generic_error(client):
    response = client.post('/login', data={
        'username': 'cybervipers',
        'password': 'WrongPassword123'
    }, follow_redirects=True)
    assert b'Invalid username or password' in response.data
    assert b'User not found' not in response.data

def test_logout(client):
    client.post('/login', data={'username': 'admin', 'password': 'SPLAdmin@2026!'})
    response = client.post('/logout', follow_redirects=True)
    assert response.status_code == 200

def test_unauthenticated_access_blocked(client):
    response = client.get('/admin', follow_redirects=False)
    assert response.status_code in [302, 401]

def test_franchise_cannot_access_admin(app, client):
    client.post('/login', data={'username': 'cybervipers', 'password': 'Vipers@2026!'})
    response = client.get('/admin', follow_redirects=False)
    assert response.status_code in [403, 302]
