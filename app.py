from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
import logging
import pytz

app = Flask(__name__)
app.secret_key = 'vgh_hospital_secure_key_2026'

# Silence specific logging shutdown errors in some Python environments
logging.raiseExceptions = False
PNG_TIMEZONE = pytz.timezone('Pacific/Port_Moresby')
MAINTENANCE_TARGET = PNG_TIMEZONE.localize(datetime(2026, 5, 30, 23, 59))


@app.before_request
def maintenance_gatekeeper():
    if request.path.startswith('/static') or request.path == '/logout':
        return

    # current_time_png is "Aware" (has timezone info)
    current_time_png = datetime.now(PNG_TIMEZONE)

    # Now both sides of the >= are "Aware"
    if current_time_png >= MAINTENANCE_TARGET:
        return render_template('maintenance.html',
                               shutdown_date=MAINTENANCE_TARGET.strftime("%d %b %Y"),
                               shutdown_time=MAINTENANCE_TARGET.strftime("%I:%M %p"))


# --- DATABASE PERSISTENCE (RENDER & LOCAL) ---
if os.environ.get('RENDER'):
    # This path matches the 'Mount Path' of the Render Disk
    db_path = '/opt/render/project/src/data/wts_erp.db'
else:
    # This is for your local laptop (PyCharm)
    basedir = os.path.abspath(os.path.dirname(__file__))
    db_path = os.path.join(basedir, 'wts_erp.db')

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_path
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


# --- MODELS ---
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    barcode = db.Column(db.String(50), unique=True)
    sku = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    unit = db.Column(db.String(20), default="Units")
    stock = db.Column(db.Integer, default=0)
    min_limit = db.Column(db.Integer, default=10)
    cost_price = db.Column(db.Float, default=0.0)
    description = db.Column(db.Text)
    date_added = db.Column(db.DateTime, default=datetime.now)
    category = db.Column(db.String(100), default="General")

class Department(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    type = db.Column(db.String(50))
    description = db.Column(db.Text)


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_name = db.Column(db.String(100))
    dept = db.Column(db.String(100))
    trans_type = db.Column(db.String(20))
    qty = db.Column(db.Integer)
    voucher_no = db.Column(db.String(50))
    batch_no = db.Column(db.String(50))
    expiry_date = db.Column(db.String(20))
    authorized_by = db.Column(db.String(100))
    timestamp = db.Column(db.DateTime, default=datetime.now)


# --- UNIFIED AUTO REBUILDER ---
with app.app_context():
    try:
        # Check if tables exist, if not, create_all will handle it via the exception
        Product.query.first()
    except:
        db.create_all()
        if not Department.query.first():
            db.session.add_all([
                Department(name="Emergency Ward"),
                Department(name="Pharmacy"),
                Department(name="Maternity"),
                Department(name="General Outpatient")
            ])
            db.session.commit()


# --- ROUTES ---

def generate_next_item_code(category_name):
    # Take first 3 letters of category, default to 'VGH' if empty
    prefix = (category_name[:3].upper()) if category_name else "VGH"

    # Find the most recent product starting with this prefix
    last_product = Product.query.filter(Product.sku.like(f"{prefix}-%")).order_by(Product.id.desc()).first()

    if not last_product:
        return f"{prefix}-0001"

    try:
        # Split 'PHA-0005' into ['PHA', '0005'] and increment
        parts = last_product.sku.split('-')
        last_num = int(parts[1])
        new_num = last_num + 1
        return f"{prefix}-{new_num:04d}"
    except (IndexError, ValueError):
        # Fallback if the format was manually changed by a user
        return f"{prefix}-{datetime.now().strftime('%H%M')}"
@app.route('/')
def login(): return render_template('login.html')


@app.route('/auth', methods=['POST'])
def auth():
    if request.form.get('username') == 'admin' and request.form.get('password') == 'password123':
        session['user'] = 'Admin User'
        return redirect(url_for('dashboard'))
    flash('Unauthorized Access', 'error')
    return redirect(url_for('login'))


@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        session.pop('_flashes', None)
        return redirect(url_for('login'))
    now = datetime.now()
    first_day = now.replace(day=1, hour=0, minute=0, second=0)
    inventory = Product.query.all()
    low_stock = Product.query.filter(Product.stock <= Product.min_limit).all()
    in_month = Transaction.query.filter(Transaction.trans_type == 'IN', Transaction.timestamp >= first_day).count()
    out_month = Transaction.query.filter(Transaction.trans_type == 'OUT', Transaction.timestamp >= first_day).count()
    logs = Transaction.query.order_by(Transaction.timestamp.desc()).limit(5).all()
    return render_template('dashboard.html', total_items=len(inventory), low_stock_count=len(low_stock),
                           stock_in_month=in_month, stock_out_month=out_month, transactions=logs)


@app.route('/inventory')
def inventory():
    if 'user' not in session: return redirect(url_for('login'))
    return render_template('inventory.html', inventory=Product.query.all())


@app.route('/stock-in')
def stock_in():
    if 'user' not in session: return redirect(url_for('login'))
    all_transactions = Transaction.query.order_by(Transaction.timestamp.desc()).all()
    all_inventory = Product.query.all()
    return render_template('stock_in.html', transactions=all_transactions, inventory=all_inventory)


@app.route('/dispatch')
def dispatch_page():
    if 'user' not in session: return redirect(url_for('login'))
    all_transactions = Transaction.query.order_by(Transaction.timestamp.desc()).all()
    all_inventory = Product.query.all()
    all_depts = Department.query.all()
    return render_template('stock_out.html', transactions=all_transactions, inventory=all_inventory, depts=all_depts)


@app.route('/reports')
def reports_page():
    if 'user' not in session: return redirect(url_for('login'))
    inventory = Product.query.all()
    low_stock = Product.query.filter(Product.stock <= Product.min_limit).all()
    total_value = sum((item.stock * (item.cost_price or 0)) for item in inventory)
    return render_template('reports.html', total_items=len(inventory), low_stock_count=len(low_stock),
                           total_value=round(total_value, 2))


@app.route('/alerts')
def alerts_page():
    if 'user' not in session: return redirect(url_for('login'))
    out_of_stock = Product.query.filter(Product.stock == 0).all()
    low_stock = Product.query.filter(Product.stock > 0, Product.stock <= Product.min_limit).all()
    return render_template('alerts.html', out_of_stock_count=len(out_of_stock), low_stock_count=len(low_stock),
                           low_stock_items=low_stock)


@app.route('/scanner')
def scanner_page():
    if 'user' not in session: return redirect(url_for('login'))
    return render_template('scanner.html')


# --- API & ACTIONS ---
@app.route('/api/next_item_code')
def next_item_code():
    cat = request.args.get('category', 'VGH')
    code = generate_next_item_code(cat)
    return jsonify({"next_code": code})

@app.route('/api/check_barcode/<barcode>')
def check_barcode(barcode):
    p = Product.query.filter_by(barcode=barcode).first()
    if p:
        return jsonify({
            "status": "exists",
            "id": p.id,
            "name": p.name,
            "stock": p.stock,
            "sku": p.sku,  # <--- Make sure this is sent!
            "category": p.category,  # Add this
            "unit": p.unit
        })
    return jsonify({"status": "not_found"})


@app.route('/api/categories')
def get_categories():
    cats = Category.query.all()
    return jsonify([{"id": c.id, "name": c.name, "type": c.type} for c in cats])


@app.route('/api/add_category', methods=['POST'])
def add_category():
    name = request.form.get('name')
    cat_type = request.form.get('type')
    if name and not Category.query.filter_by(name=name).first():
        db.session.add(Category(name=name, type=cat_type))
        db.session.commit()
        return jsonify({"status": "success"})
    return jsonify({"status": "error"})


@app.route('/register_product', methods=['POST'])
def register_product():
    sku = request.form.get('sku')
    barcode = request.form.get('barcode')
    name = request.form.get('name').upper()

    # 1. Check if the Item Code (SKU) already exists in the database
    existing_sku = Product.query.filter_by(sku=sku).first()
    if existing_sku:
        flash(f"Error: Item Code '{sku}' is already used by {existing_sku.name}. Please use a different code.", "error")
        return redirect(url_for('inventory'))

    # 2. Check if the Barcode already exists (if a barcode was provided)
    if barcode:
        existing_barcode = Product.query.filter_by(barcode=barcode).first()
        if existing_barcode:
            flash(f"Error: Barcode '{barcode}' is already assigned to {existing_barcode.name}.", "error")
            return redirect(url_for('inventory'))

    try:
        cat_name = request.form.get('category')

        # 3. Check if category exists; if not, create it
        category = Category.query.filter_by(name=cat_name).first()
        if not category and cat_name:
            new_cat = Category(name=cat_name, type="General")
            db.session.add(new_cat)
            db.session.commit()

        # 4. Create the product
        new_p = Product(
            name=name,
            sku=sku,
            barcode=barcode,
            category=cat_name,
            unit=request.form.get('unit'),
            stock=int(request.form.get('stock') or 0),
            min_limit=int(request.form.get('min_limit') or 10),
            cost_price=float(request.form.get('cost_price') or 0.0),
            description=request.form.get('description')
        )

        db.session.add(new_p)
        db.session.commit()

        # 5. Log an initial transaction if opening stock was added
        if new_p.stock > 0:
            log = Transaction(
                item_name=new_p.name,
                trans_type='IN',
                qty=new_p.stock,
                dept='Opening Stock',
                authorized_by=session.get('user', 'Admin')
            )
            db.session.add(log)
            db.session.commit()

        flash(f"{new_p.name} Registered successfully with {new_p.stock} units.", "success")

    except Exception as e:
        db.session.rollback()
        flash("Database Error: Could not save item. Please check your inputs.", "error")
        print(f"Error details: {e}")

    return redirect(url_for('inventory'))


@app.before_request
def check_user_session():
    # List of routes that don't need login
    open_routes = ['login', 'auth', 'static']

    if request.endpoint not in open_routes and 'user' not in session:
        # CLEAR all stock/inventory messages before redirecting to login
        session.pop('_flashes', None)
        return redirect(url_for('login'))
@app.route('/api/get_item/<int:id>')
def get_item(id):
    p = Product.query.get_or_404(id)
    return jsonify({
        "name": p.name,
        "sku": p.sku,
        "category": p.category,
        "min_limit": p.min_limit
    })

@app.route('/update_item', methods=['POST'])
def update_item():
    p = Product.query.get(request.form.get('item_id'))
    if p:
        p.name = request.form.get('name').upper()
        p.sku = request.form.get('sku')
        p.category = request.form.get('category')
        p.min_limit = int(request.form.get('min_limit'))
        db.session.commit()
        flash(f"Updated {p.name} successfully.", "success")
    return redirect(url_for('inventory'))

@app.route('/delete_item/<int:id>')
def delete_item(id):
    p = Product.query.get_or_404(id)
    db.session.delete(p)
    db.session.commit()
    flash("Item deleted from inventory.", "success")
    return redirect(url_for('inventory'))
@app.route('/update_stock', methods=['POST'])
def update_stock():
    item_id = request.form.get('item_id')
    item_identifier = request.form.get('item_identifier')  # The name or barcode typed
    qty_val = int(request.form.get('qty') or 0)
    trans_type = request.form.get('type', 'in').upper()

    # CASE: New Item Registration during Stock In
    if item_id == "NEW_ITEM":
        new_p = Product(
            name=item_identifier.upper(),
            barcode=item_identifier,
            category=request.form.get('category', 'General'),
            sku=f"AUTO-{datetime.now().strftime('%f')}",
            stock=qty_val
        )
        db.session.add(new_p)
        db.session.commit()
        product = new_p
    else:
        product = Product.query.get(item_id)
        if not product:
            flash("Item not found", "error")
            return redirect(url_for('stock_in'))

        if trans_type == 'OUT':
            if product.stock < qty_val:
                flash(f"Insufficient stock for {product.name}", "error")
                return redirect(url_for('dispatch_page'))
            product.stock -= qty_val
        else:
            product.stock += qty_val

    # Log the transaction
    log = Transaction(
        item_name=product.name,
        dept=request.form.get('dept', 'General'),
        trans_type=trans_type,
        qty=qty_val,
        voucher_no=request.form.get('voucher_no'),
        batch_no=request.form.get('batch_no'),
        expiry_date=request.form.get('expiry_date'),
        authorized_by=session.get('user', 'Staff')
    )
    db.session.add(log)
    db.session.commit()
    flash(f"Stock {trans_type} updated successfully", "success")
    return redirect(url_for('stock_in') if trans_type == 'IN' else url_for('dispatch_page'))

@app.context_processor
def inject_alert_counts():
    if 'user' in session:
        # Count items that are out of stock or below min limit
        low_stock_count = Product.query.filter(Product.stock <= Product.min_limit).count()
        return dict(sidebar_alert_count=low_stock_count)
    return dict(sidebar_alert_count=0)
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))