import pytest
from app import create_app
from app.extensions import db
from app.models import Franchise, User
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

def test_google_login_redirect(client):
    response = client.get('/auth/google/login', follow_redirects=False)
    assert response.status_code in [200, 302]
    if response.status_code == 302:
        assert 'google' in response.location.lower() or 'auth' in response.location.lower()
    else:
        assert b'google' in response.data.lower()

def test_google_callback_unauthorized(client):
    response = client.get('/auth/google/callback?mock_email=unauthorized@gmail.com', follow_redirects=True)
    assert response.status_code == 200
    assert b'access denied' in response.data.lower() or b'not currently authorized' in response.data.lower()

def test_disabled_franchise_cannot_login(client, app):
    with app.app_context():
        user = User.query.filter_by(username='cybervipers').first()
        user.is_active = False
        db.session.commit()

    response = client.post('/login', data={
        'username': 'cybervipers',
        'password': 'Vipers@2026!'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'inactive' in response.data.lower() or b'contact the admin' in response.data.lower()

def test_franchise_cannot_access_another_franchise_data(app, client):
    with app.app_context():
        f1 = Franchise.query.filter_by(short_name='F01').first()
        user = User.query.filter_by(franchise_id=f1.id).first()
        user_id = user.id

    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True

    response = client.get('/franchise/dashboard')
    assert response.status_code == 200
    assert b'Cyber Vipers' in response.data
    assert b'Tech Titans' not in response.data
