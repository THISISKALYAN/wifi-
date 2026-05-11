from flask import Flask, request, jsonify, render_template, redirect, url_for
from datetime import datetime
from models import db, Voucher, VoucherDevice, LoginLog, SystemConfig
import requests

import os

app = Flask(__name__)
# Use DATABASE_URL from environment if available (for Render/Railway), else local SQLite
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///meraki_vouchers.db')
# Workaround for Render's postgres:// vs postgresql:// protocol requirement
if app.config['SQLALCHEMY_DATABASE_URI'].startswith("postgres://"):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

def authorize_meraki(base_grant_url, duration):
    try:
        response = requests.get(base_grant_url, params={"duration": duration}, timeout=10)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False

@app.route('/api/voucher/create', methods=['POST'])
def create_voucher():
    data = request.get_json()
    
    if not data or 'voucher_code' not in data or 'max_devices' not in data or 'expiry_time' not in data:
        return jsonify({"error": "Missing required fields"}), 400
        
    try:
        expiry_time = datetime.strptime(data['expiry_time'], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return jsonify({"error": "Invalid expiry_time format. Use YYYY-MM-DD HH:MM:SS"}), 400
        
    existing_voucher = Voucher.query.filter_by(voucher_code=data['voucher_code']).first()
    if existing_voucher:
        return jsonify({"error": "Voucher code already exists"}), 409

    voucher = Voucher(
        room_number=data.get('room_number'),
        voucher_code=data['voucher_code'],
        max_devices=data['max_devices'],
        expiry_time=expiry_time
    )
    
    db.session.add(voucher)
    db.session.commit()
    
    # Optional sync with Meraki Dashboard API if configured
    api_key_cfg = SystemConfig.query.filter_by(config_key='meraki_api_key').first()
    network_id_cfg = SystemConfig.query.filter_by(config_key='meraki_network_id').first()
    
    if api_key_cfg and network_id_cfg and api_key_cfg.config_value and network_id_cfg.config_value:
        try:
            headers = {
                'X-Cisco-Meraki-API-Key': api_key_cfg.config_value,
                'Content-Type': 'application/json'
            }
            url = f"https://api.meraki.com/api/v1/networks/{network_id_cfg.config_value}/merakiAuthUsers"
            payload = {
                "email": f"{voucher.voucher_code}@guest.local",
                "name": f"Guest Room {voucher.room_number or 'N/A'}",
                "password": voucher.voucher_code,
                "accountType": "Guest",
                "emailPasswordToUser": False
            }
            requests.post(url, headers=headers, json=payload, timeout=5)
        except Exception as e:
            print(f"Meraki Sync Error: {e}")

    return jsonify({"message": "Voucher created successfully", "voucher_id": voucher.id}), 201

@app.route('/login', methods=['GET'])
def login_page():
    return render_template('login.html')

@app.route('/admin', methods=['GET'])
def admin_page():
    vouchers = Voucher.query.all()
    logs = LoginLog.query.order_by(LoginLog.login_time.desc()).limit(50).all()
    devices = VoucherDevice.query.all()
    
    # Map devices to voucher codes for easy display
    voucher_devices = {}
    for device in devices:
        voucher = Voucher.query.get(device.voucher_id)
        if voucher:
            if voucher.voucher_code not in voucher_devices:
                voucher_devices[voucher.voucher_code] = []
            voucher_devices[voucher.voucher_code].append(device)
            
    # Get configurations
    api_key = SystemConfig.query.filter_by(config_key='meraki_api_key').first()
    network_id = SystemConfig.query.filter_by(config_key='meraki_network_id').first()
    
    return render_template('admin.html', 
                           vouchers=vouchers, 
                           logs=logs, 
                           voucher_devices=voucher_devices,
                           api_key=api_key.config_value if api_key else "",
                           network_id=network_id.config_value if network_id else "")

@app.route('/api/config/update', methods=['POST'])
def update_config():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400
        
    for key, value in data.items():
        config = SystemConfig.query.filter_by(config_key=key).first()
        if config:
            config.config_value = value
        else:
            new_config = SystemConfig(config_key=key, config_value=value)
            db.session.add(new_config)
            
    db.session.commit()
    return jsonify({"message": "Configuration updated successfully"}), 200

@app.route('/api/voucher/delete/<int:id>', methods=['DELETE'])
def delete_voucher(id):
    voucher = Voucher.query.get(id)
    if voucher:
        # Also delete associated devices to avoid constraint issues
        VoucherDevice.query.filter_by(voucher_id=id).delete()
        db.session.delete(voucher)
        db.session.commit()
        return jsonify({"message": "Voucher deleted"}), 200
    return jsonify({"error": "Voucher not found"}), 404

@app.route('/api/voucher/login', methods=['POST'])
def voucher_login():
    data = request.get_json()
    
    if not data or 'voucher_code' not in data or 'client_mac' not in data or 'base_grant_url' not in data:
        return jsonify({"error": "Missing required fields"}), 400
        
    voucher_code = data['voucher_code']
    client_mac = data['client_mac']
    base_grant_url = data['base_grant_url']
    
    voucher = Voucher.query.filter_by(voucher_code=voucher_code).first()
    
    if not voucher:
        return jsonify({"error": "Invalid voucher"}), 404
        
    if voucher.status != 'active':
        return jsonify({"error": "Voucher is not active"}), 403
        
    current_time = datetime.utcnow()
    
    if current_time > voucher.expiry_time:
        return jsonify({"error": "Voucher expired"}), 403
        
    devices = VoucherDevice.query.filter_by(voucher_id=voucher.id).all()
    device_macs = [d.mac_address for d in devices]
    
    if client_mac not in device_macs:
        if len(devices) >= voucher.max_devices:
            return jsonify({"error": "Device limit reached"}), 403
        else:
            new_device = VoucherDevice(voucher_id=voucher.id, mac_address=client_mac)
            db.session.add(new_device)
            
    log = LoginLog(
        voucher_code=voucher_code,
        mac_address=client_mac,
        ip_address=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()
    
    duration = max(1, int((voucher.expiry_time - current_time).total_seconds() / 60))
    
    authorize_meraki(base_grant_url, duration)
    
    return jsonify({"message": "Access granted"}), 200

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0')