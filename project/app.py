import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, g, flash, jsonify
import qrcode
import uuid
import datetime
import socket
import io
import base64
import os
import cv2
import numpy as np

try:
    import easyocr
    reader = easyocr.Reader(['en'], gpu=False)
    OCR_AVAILABLE = True
except ImportError:
    reader = None
    OCR_AVAILABLE = False
    print("Warning: easyocr not installed. OCR functionality will be mocked.")

# Future Integration:
# Replace simulated barrier animation with GPIO control
# using Raspberry Pi to physically open the gate.

# NOTE:
# 127.0.0.1 works only on same machine.
# For phone access, use laptop's local IPv4 address.
# Example: http://10.43.225.138:5000

# For public QR access from any network,
# deploy this app to cloud hosting
# and set BASE_URL to public domain.
BASE_URL = "http://10.43.225.138:5000" # Change to "https://your-public-domain.com" in production

app = Flask(__name__)
app.secret_key = 'smart_parking_secret'
DATABASE = 'parking.db'

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_connection(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS slots (
                id TEXT PRIMARY KEY,
                status TEXT,
                car_number TEXT,
                phone_number TEXT,
                entry_time TEXT,
                exit_time TEXT,
                session_id TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vehicle_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                car_number TEXT,
                phone_number TEXT,
                slot_id TEXT,
                entry_time TEXT,
                exit_time TEXT,
                total_duration TEXT
            )
        ''')
        cursor.execute("SELECT COUNT(*) FROM slots")
        if cursor.fetchone()[0] == 0:
            for i in range(1, 51):
                slot_id = f"S{i}"
                cursor.execute("INSERT INTO slots (id, status) VALUES (?, ?)", (slot_id, 'vacant'))
        db.commit()

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def login_required(f):
    def wrap(*args, **kwargs):
        if 'logged_in' in session:
            return f(*args, **kwargs)
        else:
            return redirect(url_for('admin_login'))
    wrap.__name__ = f.__name__
    return wrap

@app.route('/')
def index():
    return redirect(url_for('admin_login'))

@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form['username'] == 'admin' and request.form['password'] == 'admin123':
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('admin_login'))

@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    db = get_db()
    cursor = db.cursor()
    if request.method == 'POST':
        car_number = request.form['car_number']
        phone_number = request.form['phone_number']
        
        cursor.execute("SELECT id FROM slots WHERE status = 'vacant' ORDER BY CAST(SUBSTR(id, 2) AS INTEGER) LIMIT 1")
        row = cursor.fetchone()
        if row:
            slot_id = row['id']
            session_id = str(uuid.uuid4())
            entry_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute('''
                UPDATE slots SET status = 'reserved', car_number = ?, phone_number = ?, 
                entry_time = ?, session_id = ? WHERE id = ?
            ''', (car_number, phone_number, entry_time, session_id, slot_id))
            
            # Insert into vehicle_logs
            cursor.execute('''
                INSERT INTO vehicle_logs (car_number, phone_number, slot_id, entry_time)
                VALUES (?, ?, ?, ?)
            ''', (car_number, phone_number, slot_id, entry_time))
            
            db.commit()
            return redirect(url_for('led_display', session_id=session_id))
        else:
            flash("PARKING FULL")

    cursor.execute("SELECT * FROM slots ORDER BY CAST(SUBSTR(id, 2) AS INTEGER)")
    slots = cursor.fetchall()
    
    total = 50
    vacant = sum(1 for s in slots if s['status'] == 'vacant')
    reserved = sum(1 for s in slots if s['status'] == 'reserved')
    occupied = sum(1 for s in slots if s['status'] == 'occupied')
    
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    cursor.execute("SELECT COUNT(*) FROM vehicle_logs WHERE entry_time LIKE ?", (today_str + "%",))
    total_today = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM vehicle_logs WHERE exit_time IS NOT NULL")
    total_completed = cursor.fetchone()[0]
    
    return render_template('dashboard.html', slots=slots, total=total, vacant=vacant, reserved=reserved, 
                           occupied=occupied, total_today=total_today, total_completed=total_completed)

@app.route('/led/<session_id>')
def led_display(session_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT id, car_number FROM slots WHERE session_id = ?", (session_id,))
    row = cursor.fetchone()
    if not row:
        return "Session not found", 404
    
    slot_id = row['id']
    car_number = row['car_number']
    
    # Generate QR dynamically linking to the scan route using current local network IP
    local_ip = get_local_ip()
    qr_data = f"http://{local_ip}:5000/scan/{session_id}"
    img = qrcode.make(qr_data)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    qr_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    cursor.execute("SELECT COUNT(*) FROM slots WHERE status = 'vacant'")
    vacant = cursor.fetchone()[0]
    
    return render_template('led.html', slot_id=slot_id, car_number=car_number, qr_b64=qr_b64, vacant=vacant)

@app.route('/scan/<session_id>')
def scan_qr(session_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT id FROM slots WHERE session_id = ?", (session_id,))
    row = cursor.fetchone()
    if row:
        cursor.execute("UPDATE slots SET status = 'occupied' WHERE session_id = ?", (session_id,))
        db.commit()
        return redirect(url_for('gate_entry'))
    return "Invalid session (Already Scanned or Fake QR)", 400

@app.route('/gate/entry')
def gate_entry():
    return render_template('gate_entry.html')

@app.route('/exit', methods=['GET', 'POST'])
@login_required
def exit_process():
    db = get_db()
    cursor = db.cursor()
    
    if request.method == 'POST':
        if 'process_payment' in request.form:
            car_number = request.form['car_number']
            exit_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Calculate duration
            cursor.execute("SELECT entry_time FROM slots WHERE car_number = ? AND status = 'occupied'", (car_number,))
            slot_row = cursor.fetchone()
            duration_str = ""
            if slot_row:
                entry_time = datetime.datetime.strptime(slot_row['entry_time'], "%Y-%m-%d %H:%M:%S")
                duration = datetime.datetime.now() - entry_time
                hours = int(duration.total_seconds() // 3600)
                minutes = int((duration.total_seconds() % 3600) // 60)
                duration_str = f"{hours} Hours {minutes} Minutes"
            
            # Update vehicle_logs
            cursor.execute('''
                UPDATE vehicle_logs 
                SET exit_time = ?, total_duration = ? 
                WHERE car_number = ? AND exit_time IS NULL
            ''', (exit_time, duration_str, car_number))

            # Free the slot
            cursor.execute('''
                UPDATE slots SET status = 'vacant', exit_time = ?, car_number = NULL, 
                phone_number = NULL, session_id = NULL WHERE car_number = ? AND status = 'occupied'
            ''', (exit_time, car_number))
            db.commit()
            return redirect(url_for('gate_exit'))
        else:
            car_number = request.form['car_number']
            cursor.execute("SELECT * FROM slots WHERE car_number = ?", (car_number,))
            slot = cursor.fetchone()
            if slot and slot['status'] == 'occupied':
                entry_time = datetime.datetime.strptime(slot['entry_time'], "%Y-%m-%d %H:%M:%S")
                duration = datetime.datetime.now() - entry_time
                hours = duration.total_seconds() / 3600
                amount = max(50, int(hours * 20)) # Example: Base 50 INR minimum, 20 INR/hr
                return render_template('exit.html', slot=slot, duration=str(duration).split('.')[0], amount=amount)
            else:
                flash("Car not found or not currently occupied")
                
    return render_template('exit.html', slot=None)

@app.route('/gate/exit')
def gate_exit():
    return render_template('gate_exit.html')

@app.route('/vehicles')
@login_required
def vehicle_history():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM vehicle_logs ORDER BY id DESC")
    logs = cursor.fetchall()
    return render_template('vehicles.html', logs=logs)

@app.route('/scanner')
@login_required
def scanner_page():
    return render_template('scanner.html')

@app.route('/api/scan', methods=['POST'])
@login_required
def scan_plate():
    data = request.json
    image_data = data.get('image')
    
    if not image_data:
        return jsonify({'success': False, 'error': 'No image provided'}), 400
        
    try:
        # Decode base64 image
        encoded_data = image_data.split(',')[1] if ',' in image_data else image_data
        nparr = np.frombuffer(base64.b64decode(encoded_data), np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if not OCR_AVAILABLE:
            import time
            import random
            time.sleep(1.5) # Simulate processing time
            mock_plates = ["MOCK1234", "TEST5678", "DEMO9012"]
            return jsonify({
                'success': True, 
                'vehicle_number': random.choice(mock_plates),
                'confidence': 0.95,
            })

        # Optional: pre-processing (grayscale) to improve OCR
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Run EasyOCR
        results = reader.readtext(gray)
        
        # Extract the highest confidence text
        detected_text = ""
        best_confidence = 0
        
        for (box, text, prob) in results:
            cleaned_text = ''.join(e for e in text if e.isalnum()).upper()
            if len(cleaned_text) >= 4 and prob > best_confidence:
                best_confidence = prob
                detected_text = cleaned_text
        
        if detected_text:
            return jsonify({
                'success': True, 
                'vehicle_number': detected_text,
                'confidence': float(best_confidence),
            })
        else:
            return jsonify({'success': False, 'error': 'No plate detected'})
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/submit_entry', methods=['POST'])
@login_required
def submit_entry():
    data = request.json
    vehicle_number = data.get('vehicle_number')
    phone_number = data.get('phone_number', '0000000000') # default or from form
    
    if not vehicle_number:
        return jsonify({'success': False, 'error': 'Vehicle number is required'}), 400

    db = get_db()
    cursor = db.cursor()
    
    cursor.execute("SELECT id FROM slots WHERE status = 'vacant' ORDER BY CAST(SUBSTR(id, 2) AS INTEGER) LIMIT 1")
    row = cursor.fetchone()
    
    if row:
        slot_id = row['id']
        session_id = str(uuid.uuid4())
        entry_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('''
            UPDATE slots SET status = 'reserved', car_number = ?, phone_number = ?, 
            entry_time = ?, session_id = ? WHERE id = ?
        ''', (vehicle_number, phone_number, entry_time, session_id, slot_id))
        
        # Insert into vehicle_logs
        cursor.execute('''
            INSERT INTO vehicle_logs (car_number, phone_number, slot_id, entry_time)
            VALUES (?, ?, ?, ?)
        ''', (vehicle_number, phone_number, slot_id, entry_time))
        
        db.commit()
        return jsonify({'success': True, 'redirect': url_for('led_display', session_id=session_id)})
    else:
        return jsonify({'success': False, 'error': 'PARKING FULL'}), 400

@app.route('/search', methods=['POST'])
@login_required
def search_vehicle():
    car_number = request.form.get('search_car_number', '').strip()
    db = get_db()
    cursor = db.cursor()
    
    # 1. Check if currently parked
    cursor.execute("SELECT * FROM slots WHERE car_number = ? AND status = 'occupied'", (car_number,))
    active_slot = cursor.fetchone()
    
    if active_slot:
        entry_time = datetime.datetime.strptime(active_slot['entry_time'], "%Y-%m-%d %H:%M:%S")
        duration = datetime.datetime.now() - entry_time
        hours = int(duration.total_seconds() // 3600)
        minutes = int((duration.total_seconds() % 3600) // 60)
        live_duration = f"{hours} Hours {minutes} Minutes"
        return render_template('search.html', status="parked", vehicle=active_slot, duration=live_duration, car_number=car_number)
        
    # 2. Check if in history (exited)
    cursor.execute("SELECT * FROM vehicle_logs WHERE car_number = ? ORDER BY id DESC LIMIT 1", (car_number,))
    history_log = cursor.fetchone()
    
    if history_log:
        return render_template('search.html', status="exited", vehicle=history_log, car_number=car_number)
        
    # 3. Not found
    return render_template('search.html', status="not_found", car_number=car_number)

if __name__ == '__main__':
    init_db()
    # Localhost works only in same WiFi.
    # For public QR access deploy to cloud.
    app.run(host='0.0.0.0', port=5000, debug=True)
