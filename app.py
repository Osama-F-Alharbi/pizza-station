from flask import Flask, render_template, request, redirect, url_for, session
import psycopg2
import os

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
DATABASE_URL = os.environ["DATABASE_URL"]

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
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id SERIAL PRIMARY KEY,
                  name TEXT NOT NULL,
                  email TEXT NOT NULL,
                  message TEXT NOT NULL,
                  date TEXT NOT NULL)''')
    conn.commit()
    conn.close()

init_db()

@app.errorhandler(404)
def page_not_found(e):
    return redirect(url_for('index'))

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
        name = request.form['name']
        email = request.form['email']
        message = request.form['message']
        from datetime import datetime
        date = datetime.now().strftime("%Y-%m-%d %H:%M")
        conn = get_conn()
        c = conn.cursor()
        c.execute("INSERT INTO messages (name, email, message, date) VALUES (%s, %s, %s, %s)",
                  (name, email, message, date))
        conn.commit()
        conn.close()
        return redirect(url_for('contact_success'))
    return render_template('contact.html')

@app.route('/contact_success')
def contact_success():
    return render_template('contact_success.html')

@app.route('/reservation', methods=['GET', 'POST'])
def reservation():
    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']
        day = request.form['day']
        month = request.form['month']
        year = request.form['year']
        date = f"{year}-{month}-{day}"
        guests = request.form['guests']
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT id FROM reservations WHERE phone=%s AND date=%s", (phone, date))
        existing = c.fetchone()
        if existing:
            conn.close()
            return render_template('reservation.html', duplicate_error=True)
        c.execute("INSERT INTO reservations (name, phone, date, guests) VALUES (%s, %s, %s, %s)",
                  (name, phone, date, guests))
        conn.commit()
        conn.close()
        return redirect(url_for('success', name=name, date=date, guests=guests))
    return render_template('reservation.html', duplicate_error=False)

@app.route('/success')
def success():
    name = request.args.get('name')
    date = request.args.get('date')
    guests = request.args.get('guests')
    return render_template('success.html', name=name, date=date, guests=guests)

@app.route('/my_reservations', methods=['GET', 'POST'])
def my_reservations():
    reservations = []
    phone = request.args.get('phone', '')
    searched = False
    deleted = request.args.get('deleted', False)

    if request.method == 'POST':
        phone = request.form['phone']
        searched = True
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM reservations WHERE phone=%s ORDER BY id DESC", (phone,))
        reservations = c.fetchall()
        conn.close()
    elif phone:
        searched = True
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM reservations WHERE phone=%s ORDER BY id DESC", (phone,))
        reservations = c.fetchall()
        conn.close()

    return render_template('my_reservations.html',
                           reservations=reservations,
                           phone=phone,
                           searched=searched,
                           deleted=deleted)

@app.route('/delete_reservation/<int:id>')
def delete_reservation(id):
    phone = request.args.get('phone', '')
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM reservations WHERE id=%s", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('my_reservations') + '?deleted=1&phone=' + phone)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'POST':
        if request.form['password'] == ADMIN_PASSWORD:
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
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM reservations ORDER BY id DESC")
    reservations = c.fetchall()
    c.execute("SELECT * FROM messages ORDER BY id DESC")
    messages = c.fetchall()
    conn.close()
    return render_template('admin.html', reservations=reservations, messages=messages)

@app.route('/admin/delete/<int:id>')
def admin_delete(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM reservations WHERE id=%s", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin'))

@app.route('/admin/delete_message/<int:id>')
def admin_delete_message(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM messages WHERE id=%s", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin'))

if __name__ == '__main__':
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")