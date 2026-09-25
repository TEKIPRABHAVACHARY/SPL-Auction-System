import pytest
from app import create_app
from app.extensions import db
from app.models import Franchise
from app.services.seed_service import seed_database

@pytest.fixture
def app():
    app = create_app('test')
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

def test_admin_view_franchises(admin_client):
    response = admin_client.get('/admin/franchises')
    assert response.status_code == 200
    assert b'Cyber Vipers' in response.data
    assert b'Tech Titans' in response.data

def test_admin_add_franchise(admin_client, app):
    response = admin_client.post('/admin/franchises/add', data={
        'name': 'Quantum Strikers',
        'short_name': 'F07',
        'authorized_email': 'quantum@sphoorthyengg.ac.in',
        'starting_purse': '600000',
        'squad_limit': '16'
    }, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        f = Franchise.query.filter_by(short_name='F07').first()
        assert f is not None
        assert f.name == 'Quantum Strikers'
        assert f.authorized_email == 'quantum@sphoorthyengg.ac.in'
        assert f.starting_purse == 600000.0
        assert f.squad_limit == 16

def test_admin_edit_franchise_authorized_email_and_purse(admin_client, app):
    with app.app_context():
        f = Franchise.query.filter_by(short_name='F01').first()
        f_id = f.id

    response = admin_client.post(f'/admin/franchises/{f_id}/edit', data={
        'name': 'Cyber Vipers Prime',
        'short_name': 'F01',
        'authorized_email': 'vipers_new_owner@gmail.com',
        'starting_purse': '750000',
        'squad_limit': '18',
        'is_active': 'on'
    }, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        updated = Franchise.query.get(f_id)
        assert updated.name == 'Cyber Vipers Prime'
        assert updated.authorized_email == 'vipers_new_owner@gmail.com'
        assert updated.starting_purse == 750000.0
        assert updated.squad_limit == 18
