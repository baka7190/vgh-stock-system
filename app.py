from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
import sys

app = Flask(__name__)
app.secret_key = 'wts_solutions_enterprise_2026_final'

# --- 1. MAINTENANCE KILL SWITCH CONFIGURATION ---
# Set your exact shutdown time here (Year, Month, Day, Hour, Minute)
MAINTENANCE_TIME = datetime(2026, 4, 23, 6, 40)  # Dec 31, 2026 at 11:59 PM


@app.before_request
def check_for_maintenance():
    # Allow logout even during maintenance
    if request.path == '/logout':
        return

    if datetime.now() > MAINTENANCE_TIME:
        return render_template('maintenance.html', time=MAINTENANCE_TIME.strftime("%Y-%m-%d %H:%M"))


# --- 2. DATABASE PERSISTENCE & AUTO-RESET LOGIC ---
if os.path.exists('/data'):
    db_path = '/data/wts_erp.db'
else:
    basedir = os.path.abspath(os.path.dirname(__file__))
    db_path = os.path.join(basedir, 'wts_erp.db')

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_path
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


# MODELS
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    barcode = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    stock = db.Column(db.Integer, default=0)
    min_limit = db.Column(db.Integer, default=5)
    acquisition_type = db.Column(db.String(20))
    source_name = db.Column(db.String(100))
    cost_price = db.Column(db.Float, default=0.0)
    date_added = db.Column(db.DateTime, default=datetime.now)


class Department(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_name = db.Column(db.String(100))
    dept = db.Column(db.String(100))
    trans_type = db.Column(db.String(20))
    qty = db.Column(db.Integer)
    authorized_by = db.Column(db.String(100))
    condition = db.Column(db.String(100))
    timestamp = db.Column(db.DateTime, default=datetime.now)


# --- AUTO DATABASE REBUILDER ---
with app.app_context():
    try:
        # Check if the database is healthy
        Product.query.first()
    except Exception as e:
        print(f"⚠️ SCHEMA MISMATCH DETECTED: {e}")
        print("🛠️ REBUILDING DATABASE...")
        db.session.remove()
        db.drop_all()
        db.create_all()
        # Seed default departments
        db.session.add_all([Department(name="Administration"), Department(name="Technical")])
        db.session.commit()
        print("✅ DATABASE REFRESH COMPLETE.")


# --- ROUTES ---
@app.route('/')
def login():
    if datetime.now() > MAINTENANCE_TIME:
        return render_template('maintenance.html', time=MAINTENANCE_TIME.strftime("%Y-%m-%d %H:%M"))
    return render_template('login.html')


@app.route('/auth', methods=['POST'])
def auth():
    if request.form.get('username') == 'admin' and request.form.get('password') == 'password123':
        session['user'] = 'Admin User'
        return redirect(url_for('dashboard'))
    flash('Unauthorized Access', 'error')
    return redirect(url_for('login'))


@app.route('/dashboard')
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    inventory = Product.query.all()
    alerts = Product.query.filter(Product.stock <= Product.min_limit).all()
    logs = Transaction.query.order_by(Transaction.timestamp.desc()).limit(10).all()
    depts = Department.query.all()
    return render_template('dashboard.html', inventory=inventory, alerts=alerts,
                           low_stock_count=len(alerts), total_items=len(inventory),
                           transactions=logs, depts=depts)


@app.route('/dispatch')
def dispatch_page():
    if 'user' not in session: return redirect(url_for('login'))
    depts = Department.query.all()
    return render_template('dispatch.html', depts=depts)


@app.route('/api/check_barcode/<barcode>')
def check_barcode(barcode):
    p = Product.query.filter_by(barcode=barcode).first()
    if p:
        return jsonify({"status": "exists", "id": p.id, "name": p.name, "stock": p.stock, "source": p.source_name})
    return jsonify({"status": "new"})


@app.route('/add_department', methods=['POST'])
def add_department():
    name = request.form.get('dept_name')
    if name and not Department.query.filter_by(name=name).first():
        db.session.add(Department(name=name))
        db.session.commit()
        return jsonify({"status": "success", "name": name})
    return jsonify({"status": "error"})


@app.route('/register_product', methods=['POST'])
def register_product():
    new_p = Product(
        barcode=request.form.get('barcode'),
        name=request.form.get('name'),
        stock=int(request.form.get('stock') or 0),
        min_limit=int(request.form.get('min_limit') or 5),
        acquisition_type=request.form.get('acquisition_type'),
        source_name=request.form.get('source_name'),
        cost_price=float(request.form.get('cost_price') or 0.0)
    )
    db.session.add(new_p)
    db.session.commit()
    flash("New Product Asset Registered", "success")
    return redirect(url_for('dashboard'))


@app.route('/update_stock', methods=['POST'])
def update_stock():
    product = Product.query.get(int(request.form.get('item_id')))
    trans_type = request.form.get('type')
    qty = int(request.form.get('qty'))

    if trans_type == 'out' and product.stock < qty:
        flash("Stock Deficiency Detected", "error")
        return redirect(url_for('dashboard'))

    product.stock = (product.stock + qty) if trans_type == 'in' else (product.stock - qty)

    log = Transaction(
        item_name=product.name,
        dept=request.form.get('dept'),
        trans_type=trans_type.upper(),
        qty=qty,
        authorized_by=request.form.get('authorized_by', 'System'),
        condition=request.form.get('condition', 'Good')
    )
    db.session.add(log)
    db.session.commit()
    flash(f"Inventory Logged: {product.name}", "success")
    return redirect(url_for('dashboard'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)