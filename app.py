from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3
import hashlib
import random
import string
from datetime import datetime

app = Flask(__name__, static_folder='.')
CORS(app)

DB = 'saathyatra.db'

# ─────────────────────────────────────────
# DATABASE SETUP
# ─────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS otps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT NOT NULL,
        otp TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS trips (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        from_place TEXT NOT NULL,
        to_place TEXT NOT NULL,
        date TEXT NOT NULL,
        time TEXT NOT NULL,
        seats INTEGER NOT NULL,
        fare REAL NOT NULL,
        vehicle TEXT,
        vehicle_number TEXT,
        status TEXT DEFAULT 'active',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trip_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        seats_booked INTEGER DEFAULT 1,
        status TEXT DEFAULT 'confirmed',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (trip_id) REFERENCES trips(id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    # Emergency contacts
    c.execute('''CREATE TABLE IF NOT EXISTS emergency_contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        phone TEXT NOT NULL,
        relation TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    # SOS alert log
    c.execute('''CREATE TABLE IF NOT EXISTS sos_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        latitude REAL,
        longitude REAL,
        location_name TEXT,
        trip_id INTEGER,
        sent_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    conn.commit()
    conn.close()
    print("✅ Database ready!")

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(p):
    return hashlib.sha256(p.encode()).hexdigest()

def generate_otp():
    return ''.join(random.choices(string.digits, k=6))


# ── Serve frontend ──
@app.route('/')
def serve_frontend():
    return send_from_directory('.', 'index.html')


# ─────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────
@app.route('/api/send-otp', methods=['POST'])
def send_otp():
    data = request.json
    phone = data.get('phone', '').strip()
    if not phone or len(phone) != 10 or not phone.isdigit():
        return jsonify({'success': False, 'message': 'Enter a valid 10-digit phone number'}), 400
    otp = generate_otp()
    conn = get_db()
    conn.execute('DELETE FROM otps WHERE phone = ?', (phone,))
    conn.execute('INSERT INTO otps (phone, otp) VALUES (?, ?)', (phone, otp))
    conn.commit()
    conn.close()
    print(f"\n📱 OTP for {phone}: {otp}\n")
    return jsonify({'success': True, 'message': f'OTP sent to {phone}', 'dev_otp': otp})


@app.route('/api/verify-otp', methods=['POST'])
def verify_otp():
    data = request.json
    phone = data.get('phone', '').strip()
    otp = data.get('otp', '').strip()
    name = data.get('name', '').strip()
    if not phone or not otp:
        return jsonify({'success': False, 'message': 'Phone and OTP required'}), 400
    conn = get_db()
    otp_row = conn.execute('SELECT * FROM otps WHERE phone = ? ORDER BY id DESC LIMIT 1', (phone,)).fetchone()
    if not otp_row or otp_row['otp'] != otp:
        conn.close()
        return jsonify({'success': False, 'message': 'Wrong OTP. Try again.'}), 400
    conn.execute('DELETE FROM otps WHERE phone = ?', (phone,))
    user = conn.execute('SELECT * FROM users WHERE phone = ?', (phone,)).fetchone()
    if user:
        conn.commit(); conn.close()
        return jsonify({'success': True, 'message': f'Welcome back, {user["name"]}!',
                        'user': {'id': user['id'], 'name': user['name'], 'phone': user['phone']}, 'is_new_user': False})
    else:
        if not name:
            conn.close()
            return jsonify({'success': False, 'message': 'Name is required for new users'}), 400
        conn.execute('INSERT INTO users (name, phone, password_hash) VALUES (?, ?, ?)', (name, phone, hash_password(otp)))
        conn.commit()
        user = conn.execute('SELECT * FROM users WHERE phone = ?', (phone,)).fetchone()
        conn.close()
        return jsonify({'success': True, 'message': f'Welcome to SaathYatra, {name}!',
                        'user': {'id': user['id'], 'name': user['name'], 'phone': user['phone']}, 'is_new_user': True})


# ─────────────────────────────────────────
# TRIPS
# ─────────────────────────────────────────
@app.route('/api/trips', methods=['POST'])
def post_trip():
    data = request.json
    for field in ['user_id', 'from_place', 'to_place', 'date', 'time', 'seats', 'fare']:
        if not data.get(field):
            return jsonify({'success': False, 'message': f'Missing: {field}'}), 400
    conn = get_db()
    conn.execute('INSERT INTO trips (user_id,from_place,to_place,date,time,seats,fare,vehicle,vehicle_number) VALUES (?,?,?,?,?,?,?,?,?)',
        (data['user_id'], data['from_place'], data['to_place'], data['date'], data['time'],
         data['seats'], data['fare'], data.get('vehicle',''), data.get('vehicle_number','')))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Trip posted!'})


@app.route('/api/trips/search', methods=['GET'])
def search_trips():
    from_place = request.args.get('from', '').strip()
    to_place   = request.args.get('to', '').strip()
    date       = request.args.get('date', '').strip()
    conn = get_db()
    query = 'SELECT t.*, u.name as driver_name, u.phone as driver_phone FROM trips t JOIN users u ON t.user_id=u.id WHERE t.status="active"'
    params = []
    if from_place: query += ' AND LOWER(t.from_place) LIKE ?'; params.append(f'%{from_place.lower()}%')
    if to_place:   query += ' AND LOWER(t.to_place) LIKE ?';   params.append(f'%{to_place.lower()}%')
    if date:       query += ' AND t.date=?';                    params.append(date)
    query += ' ORDER BY t.date, t.time'
    trips = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify({'success': True, 'trips': [dict(t) for t in trips]})


@app.route('/api/trips/<int:trip_id>/share', methods=['GET'])
def get_trip_share(trip_id):
    conn = get_db()
    trip = conn.execute('SELECT t.*, u.name as driver_name FROM trips t JOIN users u ON t.user_id=u.id WHERE t.id=?', (trip_id,)).fetchone()
    conn.close()
    if not trip:
        return jsonify({'success': False, 'message': 'Trip not found'}), 404
    trip = dict(trip)
    msg = (f"🚗 SaathYatra Trip Alert!\n\n"
           f"Route: {trip['from_place']} → {trip['to_place']}\n"
           f"Date: {trip['date']} at {trip['time']}\n"
           f"Fare: ₹{trip['fare']} per seat\n"
           f"Seats left: {trip['seats']}\n"
           f"Vehicle: {trip['vehicle']} {trip['vehicle_number']}\n"
           f"Driver: {trip['driver_name']}\n\n"
           f"Book at: http://localhost:5000")
    encoded = msg.replace(' ', '%20').replace('\n', '%0A')
    return jsonify({'success': True, 'trip': trip, 'share_message': msg,
                    'whatsapp_url': f'https://wa.me/?text={encoded}'})


@app.route('/api/bookings', methods=['POST'])
def book_trip():
    data = request.json
    trip_id = data.get('trip_id'); user_id = data.get('user_id')
    if not trip_id or not user_id:
        return jsonify({'success': False, 'message': 'trip_id and user_id required'}), 400
    conn = get_db()
    trip = conn.execute('SELECT * FROM trips WHERE id=?', (trip_id,)).fetchone()
    if not trip: conn.close(); return jsonify({'success': False, 'message': 'Trip not found'}), 404
    if trip['seats'] <= 0: conn.close(); return jsonify({'success': False, 'message': 'No seats available'}), 400
    if trip['user_id'] == user_id: conn.close(); return jsonify({'success': False, 'message': "Can't book your own trip"}), 400
    conn.execute('UPDATE trips SET seats=seats-1 WHERE id=?', (trip_id,))
    conn.execute('INSERT INTO bookings (trip_id,user_id) VALUES (?,?)', (trip_id, user_id))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Seat booked!'})


# ─────────────────────────────────────────
# EMERGENCY CONTACTS
# ─────────────────────────────────────────
@app.route('/api/emergency-contacts/<int:user_id>', methods=['GET'])
def get_contacts(user_id):
    conn = get_db()
    contacts = conn.execute('SELECT * FROM emergency_contacts WHERE user_id=?', (user_id,)).fetchall()
    conn.close()
    return jsonify({'success': True, 'contacts': [dict(c) for c in contacts]})


@app.route('/api/emergency-contacts', methods=['POST'])
def add_contact():
    data = request.json
    user_id  = data.get('user_id')
    name     = data.get('name','').strip()
    phone    = data.get('phone','').strip()
    relation = data.get('relation','').strip()
    if not user_id or not name or not phone:
        return jsonify({'success': False, 'message': 'user_id, name and phone required'}), 400
    if len(phone) != 10 or not phone.isdigit():
        return jsonify({'success': False, 'message': 'Enter valid 10-digit phone'}), 400
    conn = get_db()
    count = conn.execute('SELECT COUNT(*) as c FROM emergency_contacts WHERE user_id=?', (user_id,)).fetchone()['c']
    if count >= 3:
        conn.close()
        return jsonify({'success': False, 'message': 'Maximum 3 contacts allowed'}), 400
    conn.execute('INSERT INTO emergency_contacts (user_id,name,phone,relation) VALUES (?,?,?,?)', (user_id, name, phone, relation))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': f'{name} added!'})


@app.route('/api/emergency-contacts/<int:contact_id>', methods=['DELETE'])
def delete_contact(contact_id):
    conn = get_db()
    conn.execute('DELETE FROM emergency_contacts WHERE id=?', (contact_id,))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Contact removed'})


# ─────────────────────────────────────────
# SOS
# ─────────────────────────────────────────
@app.route('/api/sos', methods=['POST'])
def log_sos():
    data = request.json
    user_id       = data.get('user_id')
    latitude      = data.get('latitude')
    longitude     = data.get('longitude')
    location_name = data.get('location_name', 'Unknown location')
    trip_id       = data.get('trip_id')

    if not user_id:
        return jsonify({'success': False, 'message': 'user_id required'}), 400

    conn = get_db()
    conn.execute('INSERT INTO sos_alerts (user_id,latitude,longitude,location_name,trip_id) VALUES (?,?,?,?,?)',
                 (user_id, latitude, longitude, location_name, trip_id))
    user     = conn.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
    contacts = conn.execute('SELECT * FROM emergency_contacts WHERE user_id=?', (user_id,)).fetchall()
    conn.commit(); conn.close()

    maps_link = f'https://maps.google.com/?q={latitude},{longitude}' if latitude and longitude else ''
    contacts_list = [dict(c) for c in contacts]

    # Print to terminal so you can see SOS was triggered
    print(f"\n🆘 SOS ALERT!")
    print(f"👤 User: {user['name']} ({user['phone']})")
    print(f"📍 Location: {location_name}")
    if maps_link: print(f"🗺️  Maps: {maps_link}")
    print(f"📱 Contacts: {[c['name']+' '+c['phone'] for c in contacts_list]}\n")

    return jsonify({
        'success': True,
        'user_name': user['name'],
        'user_phone': user['phone'],
        'location_name': location_name,
        'maps_link': maps_link,
        'contacts': contacts_list,
        'whatsapp_sos_url': build_sos_whatsapp(user, location_name, maps_link)
    })

def build_sos_whatsapp(user, location_name, maps_link):
    msg = (f"🆘 EMERGENCY ALERT!\n\n"
           f"{user['name']} needs help!\n"
           f"📱 Phone: {user['phone']}\n"
           f"📍 Location: {location_name}\n")
    if maps_link:
        msg += f"🗺️ Map: {maps_link}\n"
    msg += f"\nSent via SaathYatra Safety System"
    encoded = msg.replace(' ','%20').replace('\n','%0A')
    return f"https://wa.me/?text={encoded}"


# ─────────────────────────────────────────
# HEALTH
# ─────────────────────────────────────────
@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'message': 'SaathYatra backend running! 🚗'})


if __name__ == '__main__':
    init_db()
    import os
    port = int(os.environ.get('PORT', 5000))
    print("\n🚗 SaathYatra Backend Running!")
    print(f"🌐 Running on port {port}\n")
    app.run(host='0.0.0.0', port=port)
