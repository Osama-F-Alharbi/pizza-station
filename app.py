from flask import Flask, render_template, request, redirect, url_for, session
from datetime import date, datetime, timedelta
import hmac
import os
import re
import secrets
import psycopg2

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
DATABASE_URL = os.environ["DATABASE_URL"]

# Admin login expires after 30 minutes, and the session cookie
# is not sent with requests coming from other websites.
app.permanent_session_lifetime = timedelta(minutes=30)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FLASK_DEBUG") != "1"

PHONE_RE = re.compile(r"^05\d{8}$")


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS reservations
                 (id SERIAL PRIMARY KEY,
                  name TEXT NOT NULL,
                  phone TEXT NOT NULL,
                  date TEXT NOT NULL,
                  guests INTEGER NOT NULL)''')
    # Each reservation gets a private code that is needed to view or cancel it
    c.execute("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS code TEXT UNIQUE")
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id SERIAL PRIMARY KEY,
                  name TEXT NOT NULL,
                  email TEXT NOT NULL,
                  message TEXT NOT NULL,
                  date TEXT NOT NULL)''')
    conn.commit()
    conn.close()


init_db()


def is_admin():
    return session.get('admin_logged_in') is True


@app.route('/favicon.ico')
def favicon():
    return redirect(url_for('static', filename='favicon.svg'))


@app.errorhandler(404)
def page_not_found(e):
    return redirect(url_for('index'))


@app.route('/health')
def health():
    # Used by the GitHub Actions keep-alive job: a real query keeps Supabase active
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT 1")
    conn.close()
    return "ok"


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/menu')
def menu():
    return render_template('menu.html')


@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form['name'].strip()[:100]
        email = request.form['email'].strip()[:200]
        message = request.form['message'].strip()[:2000]
        if not name or not email or not message:
            return render_template('contact.html')
        sent_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        conn = get_conn()
        c = conn.cursor()
        c.execute("INSERT INTO messages (name, email, message, date) VALUES (%s, %s, %s, %s)",
                  (name, email, message, sent_at))
        conn.commit()
        conn.close()
        return redirect(url_for('contact_success'))
    return render_template('contact.html')


@app.route('/contact_success')
def contact_success():
    return render_template('contact_success.html')


def parse_reservation(form):
    """Check the form on the server too, because JavaScript checks can be skipped."""
    name = form.get('name', '').strip()[:100]
    phone = form.get('phone', '').strip()
    if phone.startswith('5') and len(phone) == 9:
        phone = '0' + phone
    try:
        booking_date = date(int(form['year']), int(form['month']), int(form['day']))
        guests = int(form['guests'])
    except (KeyError, ValueError):
        return None
    if not name or not PHONE_RE.match(phone):
        return None
    if booking_date < date.today() or booking_date > date.today() + timedelta(days=3 * 365):
        return None
    if not 1 <= guests <= 20:
        return None
    return name, phone, booking_date.isoformat(), guests


@app.route('/reservation', methods=['GET', 'POST'])
def reservation():
    if request.method == 'POST':
        data = parse_reservation(request.form)
        if data is None:
            return render_template('reservation.html', duplicate_error=False, invalid_error=True)
        name, phone, booking_date, guests = data
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT id FROM reservations WHERE phone=%s AND date=%s", (phone, booking_date))
        if c.fetchone():
            conn.close()
            return render_template('reservation.html', duplicate_error=True)
        code = secrets.token_hex(4).upper()
        c.execute("INSERT INTO reservations (name, phone, date, guests, code) VALUES (%s, %s, %s, %s, %s)",
                  (name, phone, booking_date, guests, code))
        conn.commit()
        conn.close()
        # Keep the details in the session so the code never appears in a URL
        session['last_booking'] = {'name': name, 'date': booking_date, 'guests': guests, 'code': code}
        return redirect(url_for('success'))
    return render_template('reservation.html', duplicate_error=False)


@app.route('/success')
def success():
    booking = session.pop('last_booking', None)
    if booking is None:
        return redirect(url_for('reservation'))
    return render_template('success.html', **booking)


@app.route('/my_reservations', methods=['GET', 'POST'])
def my_reservations():
    reservation = None
    searched = False
    code = ''
    deleted = request.args.get('deleted') == '1'

    if request.method == 'POST':
        code = request.form.get('code', '').strip().upper()
        searched = True
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT id, name, phone, date, guests FROM reservations WHERE code=%s", (code,))
        reservation = c.fetchone()
        conn.close()

    return render_template('my_reservations.html',
                           reservation=reservation,
                           code=code,
                           searched=searched,
                           deleted=deleted)


@app.route('/delete_reservation/<int:id>', methods=['POST'])
def delete_reservation(id):
    # Only the person who has the reservation code can cancel it
    code = request.form.get('code', '').strip().upper()
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM reservations WHERE id=%s AND code=%s", (id, code))
    conn.commit()
    conn.close()
    return redirect(url_for('my_reservations', deleted=1))


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'POST':
        password = request.form.get('password', '')
        if hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode()):
            session.permanent = True
            session['admin_logged_in'] = True
            return redirect(url_for('admin'))
        else:
            error = 'Incorrect password, please try again'
    return render_template('admin_login.html', error=error)


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))


@app.route('/admin')
def admin():
    if not is_admin():
        return redirect(url_for('admin_login'))
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, name, phone, date, guests FROM reservations ORDER BY id DESC")
    reservations = c.fetchall()
    c.execute("SELECT * FROM messages ORDER BY id DESC")
    messages = c.fetchall()
    conn.close()
    return render_template('admin.html', reservations=reservations, messages=messages)


@app.route('/admin/delete/<int:id>', methods=['POST'])
def admin_delete(id):
    if not is_admin():
        return redirect(url_for('admin_login'))
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM reservations WHERE id=%s", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin'))


@app.route('/admin/delete_message/<int:id>', methods=['POST'])
def admin_delete_message(id):
    if not is_admin():
        return redirect(url_for('admin_login'))
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM messages WHERE id=%s", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin'))


if __name__ == '__main__':
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
