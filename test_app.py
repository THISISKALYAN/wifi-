import pytest
from app import app, db
from models import Voucher, VoucherDevice, LoginLog
from datetime import datetime, timedelta

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
        yield client
        
        with app.app_context():
            db.session.remove()
            db.drop_all()

def test_create_voucher(client):
    response = client.post('/api/voucher/create', json={
        "room_number": "301",
        "voucher_code": "ABCD1234",
        "max_devices": 3,
        "expiry_time": "2026-05-10 12:00:00"
    })
    assert response.status_code == 201
    
    with app.app_context():
        v = Voucher.query.filter_by(voucher_code="ABCD1234").first()
        assert v is not None
        assert v.max_devices == 3

def test_voucher_login_success(client, mocker):
    mocker.patch('app.authorize_meraki', return_value=True)
    
    # Create voucher
    future_date = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    client.post('/api/voucher/create', json={
        "voucher_code": "TESTCODE",
        "max_devices": 2,
        "expiry_time": future_date
    })
    
    # Login
    response = client.post('/api/voucher/login', json={
        "voucher_code": "TESTCODE",
        "client_mac": "00:11:22:33:44:55",
        "base_grant_url": "https://n123.network-auth.com/splash/grant"
    })
    
    assert response.status_code == 200
    assert response.json['message'] == "Access granted"

def test_voucher_login_expired(client):
    past_date = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    client.post('/api/voucher/create', json={
        "voucher_code": "EXPIRED",
        "max_devices": 2,
        "expiry_time": past_date
    })
    
    response = client.post('/api/voucher/login', json={
        "voucher_code": "EXPIRED",
        "client_mac": "00:11:22:33:44:55",
        "base_grant_url": "http://test"
    })
    
    assert response.status_code == 403
    assert response.json['error'] == "Voucher expired"

def test_voucher_login_device_limit(client, mocker):
    mocker.patch('app.authorize_meraki', return_value=True)
    
    future_date = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    client.post('/api/voucher/create', json={
        "voucher_code": "LIMIT",
        "max_devices": 1,
        "expiry_time": future_date
    })
    
    # First device connects
    r1 = client.post('/api/voucher/login', json={
        "voucher_code": "LIMIT",
        "client_mac": "DEV_1",
        "base_grant_url": "http://test"
    })
    assert r1.status_code == 200
    
    # Second device fails
    r2 = client.post('/api/voucher/login', json={
        "voucher_code": "LIMIT",
        "client_mac": "DEV_2",
        "base_grant_url": "http://test"
    })
    assert r2.status_code == 403
    assert r2.json['error'] == "Device limit reached"
    
    # First device reconnects (success)
    r3 = client.post('/api/voucher/login', json={
        "voucher_code": "LIMIT",
        "client_mac": "DEV_1",
        "base_grant_url": "http://test"
    })
    assert r3.status_code == 200