from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Voucher(db.Model):
    __tablename__ = 'vouchers'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    room_number = db.Column(db.String(10), nullable=True)
    voucher_code = db.Column(db.String(20), unique=True, nullable=False)
    max_devices = db.Column(db.Integer, nullable=False)
    expiry_time = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default='active')
    
    devices = db.relationship('VoucherDevice', backref='voucher', lazy=True)

class VoucherDevice(db.Model):
    __tablename__ = 'voucher_devices'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    voucher_id = db.Column(db.Integer, db.ForeignKey('vouchers.id'), nullable=False)
    mac_address = db.Column(db.String(20), nullable=False)
    first_login = db.Column(db.DateTime, default=datetime.utcnow)

class LoginLog(db.Model):
    __tablename__ = 'login_logs'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    voucher_code = db.Column(db.String(20), nullable=False)
    mac_address = db.Column(db.String(20), nullable=False)
    login_time = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address = db.Column(db.String(45), nullable=True)
class SystemConfig(db.Model):
    __tablename__ = 'system_config'
    id = db.Column(db.Integer, primary_key=True)
    config_key = db.Column(db.String(50), unique=True, nullable=False)
    config_value = db.Column(db.String(255), nullable=True)
