import pytest
from app import create_app
from app.extensions import db
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

def test_live_projector_screen_public_access(client):
    response = client.get('/live')
    assert response.status_code == 200
    assert b'WAITING FOR NEXT PLAYER' in response.data or b'SPL' in response.data

def test_live_projector_does_not_reveal_next_player(client):
    response = client.get('/live')
    assert b'Next Player Queue' not in response.data
    assert b'Upcoming Bids' not in response.data

def test_theme_switcher_present_in_templates(client):
    response = client.get('/login')
    assert response.status_code == 200
    assert b'theme-toggle-btn' in response.data or b'theme' in response.data
